import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from pydantic import ValidationError
from classroom import (Round, Session, Plan, parse_plan, parse_evaluation,
                       parse_support_audit, teaching_report, validate_notes, evaluation_context)
from prompts import SAMPLE_NOTES
from sarvam_client import ClassroomError, Gateway, audio_duration
from sarvamai.core.api_error import ApiError
from tests.fixtures import (question_data, fixed_question, assessment_data, fake_evaluation,
                            audit_data, draft_plan_data, wav_bytes, FULL_ANSWER, ANSWERS)


def response(data):
    raw = data if isinstance(data, str) else json.dumps(data)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])


def gateway_with(*responses):
    gateway = Gateway.__new__(Gateway)
    gateway.client = Mock()
    gateway.evaluation_cache = {}
    gateway.client.chat.completions.side_effect = [response(r) for r in responses]
    return gateway


class ClassroomTests(unittest.TestCase):
    def setUp(self):
        self.q = fixed_question()
        self.plan = Plan(questions=(self.q,), reason="")

    def parse(self, data, answer=FULL_ANSWER):
        return parse_evaluation(json.dumps(data), SAMPLE_NOTES, self.q, [answer], "test-context")

    def test_fixed_question_cases(self):
        for label, (answer, status) in ANSWERS.items():
            with self.subTest(label=label):
                result = self.parse(assessment_data(status, answer), answer)
                self.assertEqual(result.status, status)
                if status == "Partly demonstrated":
                    self.assertIn(self.q.rubric[1].requirement, result.missing_or_incorrect_points[0])
                    self.assertEqual(result.assessment.follow_up_point_id, "p2")

    def test_extra_information_does_not_change_status(self):
        data = assessment_data()
        data["unverified_information"] = ["My textbook has a blue cover."]
        self.assertEqual(self.parse(data).status, "Demonstrated")

    def test_unsupported_is_not_incorrect_and_does_not_advance(self):
        data = assessment_data()
        data["evidence_support"] = "insufficient"
        gateway = gateway_with(data, data)
        current = Round(self.q)
        with self.assertRaisesRegex(ClassroomError, "Unable to verify this evaluation"):
            current.submit(gateway, SAMPLE_NOTES, "English", FULL_ANSWER)
        self.assertEqual(current.phase, "answer")
        self.assertFalse(current.answers or current.evaluations or current.evaluation_cache)
        self.assertEqual(gateway.client.chat.completions.call_count, 2)

    def test_invalid_source_reference_preserves_round_and_retries_once(self):
        data = assessment_data()
        data["points"][0]["source_ids"] = ["s999"]
        current = Round(self.q)
        gateway = gateway_with(data, data)
        with self.assertRaisesRegex(ClassroomError, "Unable to verify this evaluation"):
            current.submit(gateway, SAMPLE_NOTES, "English", FULL_ANSWER)
        self.assertEqual(current.phase, "answer")
        self.assertFalse(current.answers or current.evaluations)
        self.assertEqual(gateway.client.chat.completions.call_count, 2)

    def test_fresh_quote_not_required_and_saved_excerpts_attached(self):
        result = self.parse(assessment_data())
        for source in self.q.sources:
            self.assertIn(source.excerpt, result.source_quote)
        self.assertNotIn("source_quote", assessment_data())
        self.assertIn("[s1]", result.source_quote)

    def test_paraphrased_source_rejected_before_question_shown(self):
        data = question_data()
        data["sources"][0]["excerpt"] = "BCC has a packing factor of 0.68."
        with self.assertRaisesRegex(ValueError, "source_excerpt_not_in_notes"):
            parse_plan(json.dumps({"questions": [data], "reason": ""}), SAMPLE_NOTES)

    def test_rubric_and_nested_evidence_are_immutable(self):
        with self.assertRaises(ValidationError):
            self.q.student_question = "Different question"
        with self.assertRaises(ValidationError):
            self.q.rubric[0].requirement = "Different point"
        with self.assertRaises(ValidationError):
            self.q.sources[0].excerpt = "Different evidence"

    def test_real_but_unrelated_quote_does_not_pass_semantic_audit(self):
        data = audit_data(self.plan)
        data["q0_p1"] = False
        with self.assertRaisesRegex(ValueError, "unsupported_rubric_point"):
            parse_support_audit(json.dumps(data), self.plan)

    def test_unsupported_question_regenerates_before_return(self):
        gateway = gateway_with(draft_plan_data(self.plan), audit_data(self.plan, False),
                               draft_plan_data(self.plan), audit_data(self.plan))
        self.assertEqual(gateway.generate(SAMPLE_NOTES, "English").questions[0].concept, self.q.concept)
        self.assertEqual(gateway.client.chat.completions.call_count, 4)

    def test_unsupported_question_never_returned_after_retry(self):
        gateway = gateway_with(draft_plan_data(self.plan), audit_data(self.plan, False),
                               draft_plan_data(self.plan), audit_data(self.plan, False))
        with self.assertRaisesRegex(ClassroomError, "Unable to create a supported"):
            gateway.generate(SAMPLE_NOTES, "English")

    def test_invalid_json_retries_and_recovers(self):
        gateway = gateway_with("invalid", assessment_data())
        self.assertEqual(gateway.evaluate(SAMPLE_NOTES, "English", self.q, [FULL_ANSWER], []).status, "Demonstrated")
        self.assertEqual(gateway.client.chat.completions.call_count, 2)

    def test_invented_answer_quote_rejected(self):
        data = assessment_data()
        data["points"][0]["answer_excerpt"] = "This was never said"
        with self.assertRaisesRegex(ValueError, "answer_excerpt_not_in_submission"):
            self.parse(data)

    def test_missing_point_and_wrong_followup_rejected(self):
        data = assessment_data("Partly demonstrated")
        data["follow_up_point_id"] = "p1"
        with self.assertRaisesRegex(ValueError, "follow_up_not_linked"):
            self.parse(data)
        data = assessment_data()
        data["points"].pop()
        with self.assertRaisesRegex(ValueError, "missing_or_duplicate"):
            self.parse(data)

    def test_identical_submission_reuses_saved_evaluation(self):
        gateway = gateway_with(assessment_data())
        first = gateway.evaluate(SAMPLE_NOTES, "English", self.q, [FULL_ANSWER], [])
        second = gateway.evaluate(SAMPLE_NOTES, "English", self.q, [FULL_ANSWER], [])
        self.assertIs(first, second)
        self.assertEqual(gateway.client.chat.completions.call_count, 1)
        self.assertEqual(gateway.client.chat.completions.call_args.kwargs["temperature"], 0)

    def test_cache_is_bound_to_full_context(self):
        gateway = gateway_with(*[assessment_data()] * 5)
        for notes, language, q, round_id in [
            (SAMPLE_NOTES, "English", self.q, "r1"),
            (SAMPLE_NOTES + "\nAdditional source.", "English", self.q, "r1"),
            (SAMPLE_NOTES, "Hindi", self.q, "r1"),
            (SAMPLE_NOTES, "English", fixed_question("New concept"), "r1"),
            (SAMPLE_NOTES, "English", self.q, "r2"),
        ]:
            gateway.evaluate(notes, language, q, [FULL_ANSWER], [], round_id=round_id)
        self.assertEqual(gateway.client.chat.completions.call_count, 5)

    def test_followup_uses_same_question_and_correct_history(self):
        first_answer = "FCC packs more tightly."
        gateway = gateway_with(assessment_data("Partly demonstrated", first_answer),
                               assessment_data("Partly demonstrated", first_answer), assessment_data())
        current = Round(self.q)
        lesson = Session(SAMPLE_NOTES, "English", [current])
        current.submit(gateway, lesson.notes, lesson.language, first_answer)
        self.assertFalse(current.submit(gateway, lesson.notes, lesson.language, first_answer))
        current.follow_up()
        current.submit(gateway, lesson.notes, lesson.language, FULL_ANSWER)
        payload = json.loads(gateway.client.chat.completions.call_args.kwargs["messages"][1]["content"])
        self.assertEqual(payload["answers"], [first_answer, FULL_ANSWER])
        self.assertEqual(payload["question"], self.q.model_dump(mode="json"))
        self.assertEqual(payload["round_id"], current.id)
        self.assertEqual(payload["attempt"], 2)
        self.assertEqual(payload["prior_feedback"][0]["assessment"]["follow_up_point_id"], "p2")
        self.assertEqual(current.phase, "done")
        self.assertEqual(len(current.answers), 2)
        self.assertFalse(current.submit(gateway, lesson.notes, lesson.language, "third"))
        lesson.next()
        self.assertTrue(lesson.finished)

    def test_wrong_round_prior_feedback_rejected(self):
        prior = fake_evaluation(SAMPLE_NOTES, "English", self.q, [FULL_ANSWER], [], round_id="other")
        gateway = gateway_with()
        with self.assertRaises(ClassroomError):
            gateway.evaluate(SAMPLE_NOTES, "English", self.q, [FULL_ANSWER, FULL_ANSWER], [prior], round_id="current")
        gateway.client.chat.completions.assert_not_called()

    def test_semantic_review_corrects_literal_grading_and_is_cached(self):
        gateway = gateway_with(assessment_data("Partly demonstrated"), assessment_data())
        result = gateway.evaluate(SAMPLE_NOTES, "English", self.q, [FULL_ANSWER], [])
        self.assertEqual(result.status, "Demonstrated")
        self.assertEqual(gateway.client.chat.completions.call_count, 2)
        self.assertIs(gateway.evaluate(SAMPLE_NOTES, "English", self.q, [FULL_ANSWER], []), result)
        self.assertEqual(gateway.client.chat.completions.call_count, 2)

    def test_semantic_review_failure_does_not_save_provisional_grade(self):
        invalid = assessment_data()
        invalid["points"][0]["source_ids"] = ["s999"]
        gateway = gateway_with(assessment_data("Partly demonstrated"), invalid, invalid)
        current = Round(self.q)
        with self.assertRaisesRegex(ClassroomError, "Unable to verify this evaluation"):
            current.submit(gateway, SAMPLE_NOTES, "English", FULL_ANSWER)
        self.assertFalse(current.answers or current.evaluations or current.evaluation_cache)
        self.assertEqual(current.phase, "answer")

    def test_changed_source_is_not_evaluated_in_old_round(self):
        current = Round(self.q)
        lesson = Session(SAMPLE_NOTES, "English", [current])
        with self.assertRaisesRegex(ValueError, "changed"):
            current.submit(Mock(), SAMPLE_NOTES + " new source", "English", FULL_ANSWER)

    def test_session_next_requires_done_and_report_distinguishes_reveal(self):
        current = Round(self.q)
        lesson = Session(SAMPLE_NOTES, "English", [current])
        lesson.next()
        self.assertEqual(lesson.index, 0)
        current.evaluations = [fake_evaluation(SAMPLE_NOTES, "English", self.q, ["wrong"], [], status="Needs revision")]
        current.phase = "done"
        lesson.next()
        lesson.next()
        self.assertEqual(lesson.index, 1)
        self.assertIn("not counted as demonstrated", teaching_report(lesson))

    def test_notes_and_plan_limits(self):
        for notes in ("short", "word " * 100, "long " * 2000):
            with self.assertRaises(ValueError):
                validate_notes(notes)
        self.assertFalse(parse_plan('{"questions": [], "reason": "Add definitions."}', SAMPLE_NOTES).questions)

    def test_audio_limits(self):
        self.assertEqual(audio_duration(wav_bytes()), 1)
        for data in (b"", b"not wav", wav_bytes(31)):
            with self.assertRaises(ClassroomError):
                audio_duration(data)

    def test_missing_credentials(self):
        with patch("sarvam_client.configured_key", return_value=""):
            with self.assertRaises(ClassroomError):
                Gateway()

    def test_rate_limit_is_bounded_and_errors_are_sanitized(self):
        gateway = gateway_with()
        for code, expected in ((429, 2), (503, 2), (403, 1)):
            operation = Mock(side_effect=ApiError(status_code=code, body="private details"))
            with patch("sarvam_client.time.sleep"), self.assertRaises(ClassroomError) as caught:
                gateway._call(operation)
            self.assertEqual(operation.call_count, expected)
            self.assertNotIn("private details", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
