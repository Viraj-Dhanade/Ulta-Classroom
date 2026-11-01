"""Explicit live regression cases on a fixed rubric. Uses Sarvam credits."""
from sarvam_client import Gateway, ClassroomError
from classroom import Round, Session
from prompts import SAMPLE_NOTES
from tests.fixtures import fixed_question, ANSWERS, FULL_ANSWER
from note_uploads import extract_notes


def main():
    gateway = Gateway()
    question = fixed_question()
    failures = []
    for name, (answer, expected) in ANSWERS.items():
        try:
            result = gateway.evaluate(SAMPLE_NOTES, "English", question, [answer], [])
            print(f"{name}: {result.status} (expected {expected})", flush=True)
            if result.status != expected:
                failures.append(name)
                print(result.missing_or_incorrect_points, flush=True)
            assert gateway.evaluate(SAMPLE_NOTES, "English", question, [answer], []) is result
        except ClassroomError as exc:
            print(name + ": " + str(exc), flush=True)
            failures.append(name)
    current = Round(question)
    lesson = Session(SAMPLE_NOTES, "English", [current])
    current.submit(gateway, lesson.notes, lesson.language, ANSWERS["incomplete"][0])
    assert current.phase == "feedback"
    current.follow_up()
    current.submit(gateway, lesson.notes, lesson.language, FULL_ANSWER)
    assert current.evaluations[-1].status == "Demonstrated" and current.phase == "done"
    print("Follow-up with frozen round state: PASS", flush=True)
    selected = extract_notes("sample.txt", SAMPLE_NOTES.encode())
    plan = gateway.generate(selected, "English")
    assert plan.questions
    print(f"Uploaded TXT source generation and rubric audit: {len(plan.questions)} supported questions", flush=True)
    answer = " ".join(plan.questions[0].expected_key_points)
    result = gateway.evaluate(selected, "English", plan.questions[0], [answer], [])
    assert result.status == "Demonstrated"
    print("Evaluation uses confirmed uploaded source: PASS", flush=True)
    assert not failures, "Live regressions failed: " + ", ".join(failures)


if __name__ == "__main__":
    try:
        main()
    except ClassroomError as exc:
        raise SystemExit(str(exc)) from None
