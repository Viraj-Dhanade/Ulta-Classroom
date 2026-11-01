import io
import json
import wave
from classroom import Question, evaluation_context, parse_evaluation
from prompts import SAMPLE_NOTES

FULL_ANSWER = "FCC packs more tightly: 0.74 of its cell volume is occupied by atoms versus 0.68 in BCC. A body-centre atom alone does not determine packing."
ANSWERS = {
    "fully correct": (FULL_ANSWER, "Demonstrated"),
    "incomplete": ("FCC packs more tightly because its packing factor is 0.74 versus 0.68 for BCC.", "Partly demonstrated"),
    "incorrect": ("BCC packs more tightly because it has a centre atom. Its packing fraction is 0.74 while FCC is 0.68.", "Needs revision"),
    "paraphrase": ("Out of a hundred units of cell volume, atoms fill about 74 in FCC and 68 in BCC. Having an atom in the middle is not enough to tell how full the cell is.", "Demonstrated"),
    "harmless extra": (FULL_ANSWER + " I remember this using coloured marbles. My textbook has a blue cover.", "Demonstrated"),
    "code mixed": ("FCC zyada tightly packed hai: atoms occupy 74 percent cell volume, BCC mein 68 percent. Sirf centre mein atom hone se packing decide nahi hoti.", "Demonstrated"),
}


def question_data(concept="Packing fraction"):
    return dict(concept=concept, misconception="BCC packs more tightly.",
                student_question="Does a body-centre atom make BCC more tightly packed than FCC? Explain using occupied volume fractions.",
                sources=[{"id": "s1", "excerpt": SAMPLE_NOTES.split("\n\n")[0]},
                         {"id": "s2", "excerpt": SAMPLE_NOTES.split("\n\n")[1]},
                         {"id": "s3", "excerpt": SAMPLE_NOTES.split("\n\n")[2]}],
                rubric=[{"id": "p1", "requirement": "FCC packs more tightly: its packing factor is 0.74 versus BCC at 0.68.", "source_ids": ["s1", "s2"]},
                        {"id": "p2", "requirement": "Packing factor represents the fraction of cell volume occupied by atoms.", "source_ids": ["s3"]},
                        {"id": "p3", "requirement": "A body-centre atom alone does not determine how tightly the structure is packed.", "source_ids": ["s3"]}])


def fixed_question(concept="Packing fraction"):
    return Question.model_validate_json(json.dumps(question_data(concept)))


def assessment_data(status="Demonstrated", answer=FULL_ANSWER):
    coverage = ["met"] * 3 if status == "Demonstrated" else (["met", "missing", "missing"] if status == "Partly demonstrated" else ["incorrect"] * 3)
    return dict(addresses_question="yes", address_reason="The answer discusses packing.",
                points=[dict(point_id=p["id"], coverage=c, explanation="The required reasoning is expressed." if c == "met" else "Explain this required point.",
                             answer_excerpt=answer if c != "missing" else "", source_ids=p["source_ids"])
                        for p, c in zip(question_data()["rubric"], coverage)],
                unverified_information=[], student_reply="Thanks for explaining.",
                follow_up_point_id="" if status == "Demonstrated" else ("p2" if status == "Partly demonstrated" else "p1"),
                follow_up_question="" if status == "Demonstrated" else "How does the occupied volume fraction answer this point?")


def fake_evaluation(notes, language, question, answers, previous, *, cache=None, round_id="", status="Demonstrated"):
    _, context = evaluation_context(notes, language, question, answers, previous, round_id)
    return parse_evaluation(json.dumps(assessment_data(status, answers[-1])), notes, question, answers, context)


def audit_data(plan, supported=True):
    from classroom import audit_keys
    return dict.fromkeys(audit_keys(plan), supported)


def draft_plan_data(plan):
    data = plan.model_dump(mode="json")
    for question in data["questions"]:
        del question["sources"]
    return data


def wav_bytes(seconds=1):
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\0\0" * int(16000 * seconds))
    return out.getvalue()
