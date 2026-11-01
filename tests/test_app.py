import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from classroom import Plan, Question, parse_evaluation
from prompts import SAMPLE_NOTES
from sarvam_client import ClassroomError
from tests.fixtures import fixed_question, fake_evaluation
import json
import io
from tests.fixtures import wav_bytes

APP = str(Path(__file__).resolve().parents[1] / "app.py")


class FakeGateway:
    calls = 0
    speech_calls = 0
    fail = False
    transcription_calls = 0
    generated_notes = []
    evaluated_contexts = []

    def generate(self, notes, language):
        type(self).generated_notes.append(notes)
        return Plan(questions=tuple(fixed_question(name) for name in ("Packing", "Atom counting", "Coordination")), reason="")

    def speak(self, text, language):
        type(self).speech_calls += 1
        raise ClassroomError("Voice unavailable")

    def evaluate(self, notes, language, question, answers, previous, **kwargs):
        type(self).calls += 1
        type(self).evaluated_contexts.append((notes, question, list(answers), list(previous), kwargs.get("round_id")))
        if self.fail:
            raise ClassroomError("Temporary failure")
        status = "Needs revision" if answers[-1] == "unsure" else "Demonstrated"
        return fake_evaluation(notes, language, question, answers, previous, status=status, **kwargs)

    def transcribe(self, data):
        type(self).transcription_calls += 1
        return "Review this transcript"


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    return app


class AppTests(unittest.TestCase):
    def setUp(self):
        FakeGateway.calls = FakeGateway.speech_calls = 0
        FakeGateway.transcription_calls = 0
        FakeGateway.generated_notes = []
        FakeGateway.evaluated_contexts = []
        FakeGateway.fail = False
        self.gateway = patch("sarvam_client.Gateway", FakeGateway)
        self.key = patch("sarvam_client.configured_key", return_value="configured")
        self.gateway.start()
        self.key.start()
        self.addCleanup(self.gateway.stop)
        self.addCleanup(self.key.stop)

    def start(self):
        app = AppTest.from_file(APP, default_timeout=15).run()
        click(app, "Load sample topic")
        self.assertEqual(app.text_area[0].value, SAMPLE_NOTES)
        click(app, "Start teaching")
        self.assertFalse(app.exception)
        return app

    def test_full_three_round_typed_flow_no_duplicate_calls(self):
        app = self.start()
        for index in range(3):
            app.text_area[0].set_value("FCC packs more tightly because its occupied volume fraction is larger.")
            click(app, "Check my explanation")
            self.assertFalse(app.exception)
            app.run()
            self.assertEqual(FakeGateway.calls, index + 1)
            click(app, "Next concept" if index < 2 else "See teaching report")
        self.assertTrue(app.session_state.lesson.finished)
        # The fixture repeats identical question text; all rounds reuse its voice entry.
        self.assertEqual(FakeGateway.speech_calls, 1)
        self.assertTrue(any("Your teaching report" in m.value for m in app.markdown))
        click(app, "Teach another topic")
        self.assertEqual(app.text_area[0].value, SAMPLE_NOTES)

    def test_followup_limit_and_answer_reset(self):
        app = self.start()
        app.text_area[0].set_value("unsure")
        click(app, "Check my explanation")
        click(app, "Answer follow-up")
        self.assertEqual(app.text_area[0].value, "")
        app.text_area[0].set_value("unsure")
        click(app, "Check my explanation")
        self.assertTrue(app.session_state.lesson.rounds[0].revealed)
        self.assertFalse(any(b.label == "Answer follow-up" for b in app.button))
        click(app, "Next concept")
        self.assertEqual(app.text_area[0].value, "")

    def test_failure_preserves_answer_and_retry(self):
        app = self.start()
        FakeGateway.fail = True
        app.text_area[0].set_value("Keep this explanation")
        click(app, "Check my explanation")
        self.assertEqual(app.text_area[0].value, "Keep this explanation")
        self.assertEqual(app.session_state.lesson.rounds[0].answers, [])
        self.assertEqual(len(app.error), 1)
        FakeGateway.fail = False
        click(app, "Check my explanation")
        self.assertEqual(app.session_state.lesson.rounds[0].phase, "done")

    def test_missing_credentials_allows_notes_only(self):
        with patch("sarvam_client.configured_key", return_value=""):
            app = AppTest.from_file(APP).run()
            self.assertTrue(next(b for b in app.button if b.label == "Start teaching").disabled)
            click(app, "Load sample topic")
            self.assertEqual(app.text_area[0].value, SAMPLE_NOTES)
            self.assertFalse(app.exception)

    def test_transcription_requires_review_and_explicit_submission(self):
        with patch("streamlit.audio_input", return_value=io.BytesIO(wav_bytes())):
            app = self.start()
            click(app, "Transcribe")
            self.assertEqual(app.text_area[0].value, "Review this transcript")
            self.assertEqual(FakeGateway.calls, 0)
            click(app, "Transcribe")
            self.assertEqual(FakeGateway.transcription_calls, 1)
            app.text_area[0].set_value("My reviewed explanation")
            click(app, "Check my explanation")
            self.assertEqual(app.session_state.lesson.rounds[0].answers, ["My reviewed explanation"])

    def test_uploaded_preview_is_only_source_sent_to_generation_and_evaluation(self):
        uploaded = io.BytesIO((SAMPLE_NOTES + "\nDO NOT STUDY THIS SECTION").encode())
        uploaded.name = "notes.txt"
        with patch("streamlit.file_uploader", return_value=uploaded):
            app = AppTest.from_file(APP).run()
            app.radio[0].set_value("Upload a file").run()
            self.assertIn("DO NOT STUDY", app.text_area[0].value)
            self.assertEqual(FakeGateway.generated_notes, [])
            app.text_area[0].set_value(SAMPLE_NOTES)
            click(app, "Start teaching")
            self.assertEqual(FakeGateway.generated_notes, [SAMPLE_NOTES])
            app.text_area[0].set_value("My reviewed explanation")
            click(app, "Check my explanation")
            self.assertEqual(FakeGateway.evaluated_contexts[0][0], SAMPLE_NOTES)
            self.assertEqual(app.session_state.lesson.notes, SAMPLE_NOTES)

    def test_oversized_preview_is_preserved_and_blocked(self):
        uploaded = io.BytesIO((SAMPLE_NOTES * 12).encode())
        uploaded.name = "notes.txt"
        with patch("streamlit.file_uploader", return_value=uploaded):
            app = AppTest.from_file(APP).run()
            app.radio[0].set_value("Upload a file").run()
            self.assertEqual(app.text_area[0].value, SAMPLE_NOTES * 12)
            self.assertTrue(next(b for b in app.button if b.label == "Start teaching").disabled)
            self.assertTrue(any("8,000" in e.value for e in app.error))

    def test_source_change_clears_old_rounds_and_answers(self):
        app = self.start()
        old_id = app.session_state.lesson.rounds[0].id
        app.text_area[0].set_value("old answer")
        click(app, "Check my explanation")
        click(app, "Change source")
        self.assertEqual(app.session_state.lesson.rounds[0].id, old_id)
        updated = SAMPLE_NOTES + "\nThese are the updated notes."
        app.text_area[0].set_value(updated)
        click(app, "Start teaching")
        lesson = app.session_state.lesson
        self.assertNotEqual(lesson.rounds[0].id, old_id)
        self.assertEqual(lesson.notes, updated)
        self.assertFalse(lesson.rounds[0].answers or lesson.rounds[0].evaluations)
        self.assertEqual(app.text_area[0].value, "")

    def test_unverifiable_feedback_preserves_draft_and_round(self):
        app = self.start()
        original = app.session_state.lesson.rounds[0].question
        with patch.object(FakeGateway, "evaluate", side_effect=ClassroomError("Unable to verify this evaluation")):
            app.text_area[0].set_value("Preserve this draft")
            click(app, "Check my explanation")
            self.assertEqual(app.text_area[0].value, "Preserve this draft")
            self.assertEqual(app.error[0].value, "Unable to verify this evaluation")
            self.assertEqual(app.session_state.lesson.rounds[0].question, original)
            self.assertEqual(app.session_state.lesson.index, 0)
            self.assertFalse(app.session_state.lesson.rounds[0].evaluations)


if __name__ == "__main__":
    unittest.main()
