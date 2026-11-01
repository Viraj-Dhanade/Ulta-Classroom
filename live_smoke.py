"""Explicit live verification. Uses credits; never runs during unit tests."""
from classroom import Round, Session, teaching_report
from prompts import SAMPLE_NOTES
from sarvam_client import ClassroomError, Gateway, audio_duration


def main():
    gateway = Gateway()
    plan = gateway.generate(SAMPLE_NOTES, "English")
    assert len(plan.questions) == 3, "Sample should support three distinct concepts"
    print(f"LIVE generation: {len(plan.questions)} verified concepts", flush=True)
    lesson = Session(SAMPLE_NOTES, "English", [Round(q) for q in plan.questions])
    for index, current in enumerate(lesson.rounds):
        if index == 0:
            current.submit(gateway, SAMPLE_NOTES, "English", "I think the atom in the middle means BCC must be packed most tightly. I am not sure why.")
            assert current.phase == "feedback", "Incorrect answer should receive one follow-up"
            current.follow_up()
        answer = " ".join(current.question.expected_key_points)
        current.submit(gateway, SAMPLE_NOTES, "English", answer)
        assert current.phase == "done" and current.evaluations[-1].status == "Demonstrated"
        lesson.next()
        print(f"LIVE evaluation round {index + 1}: {current.evaluations[-1].status}", flush=True)
    assert lesson.finished and "3 of 3" in teaching_report(lesson)
    print("LIVE complete teaching loop and report: PASS", flush=True)
    samples = {
        "English": "BCC contains two atoms per unit cell, while FCC contains four.",
        "Hindi": "बी सी सी में दो परमाणु होते हैं। एफ सी सी में चार परमाणु होते हैं।",
        "Marathi": "बी सी सी मध्ये दोन अणू असतात. एफ सी सी मध्ये चार अणू असतात.",
    }
    for language, text in samples.items():
        audio = gateway.speak(text, language)
        duration = audio_duration(audio)
        transcript = gateway.transcribe(audio)
        assert transcript
        print(f"LIVE {language}: TTS WAV {duration:.1f}s; STT returned {len(transcript)} characters", flush=True)
    print("Synthetic speech round-trip verified; physical microphone/browser permission remains a manual check.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except ClassroomError as exc:
        raise SystemExit(str(exc)) from None
