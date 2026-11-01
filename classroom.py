"""Frozen rubrics, evidence validation, and transactional session transitions."""
from dataclasses import dataclass, field
import hashlib
import json
import re
from threading import Lock
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 3


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class VerificationError(ValueError):
    """Machine-readable reason only; never a grade or a raw API response."""


class Source(Model):
    id: str = Field(pattern=r"^s[1-9][0-9]*$")
    excerpt: str = Field(min_length=1, max_length=1800)


class RubricPoint(Model):
    id: str = Field(pattern=r"^p[1-9][0-9]*$")
    requirement: str = Field(min_length=1, max_length=500)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=6)


class Question(Model):
    concept: str = Field(min_length=1, max_length=160)
    misconception: str = Field(min_length=1, max_length=500)
    student_question: str = Field(min_length=1, max_length=500)
    rubric: tuple[RubricPoint, ...] = Field(min_length=1, max_length=4)
    sources: tuple[Source, ...] = Field(min_length=1, max_length=6)

    @property
    def expected_key_points(self):
        return tuple(point.requirement for point in self.rubric)


class Plan(Model):
    questions: tuple[Question, ...] = Field(max_length=3)
    reason: str = Field(max_length=600)


class DraftQuestion(Model):
    concept: str = Field(min_length=1, max_length=160)
    misconception: str = Field(min_length=1, max_length=500)
    student_question: str = Field(min_length=1, max_length=500)
    rubric: tuple[RubricPoint, ...] = Field(min_length=1, max_length=4)


class DraftPlan(Model):
    questions: tuple[DraftQuestion, ...] = Field(max_length=3)
    reason: str = Field(max_length=600)


def source_catalog(notes):
    pieces = []
    for part in re.split(r"(?<=[.!?।])\s+|\n\s*\n", notes):
        part = part.strip()
        while len(part) > 1600:
            split = part.rfind(" ", 0, 1600)
            split = split if split > 0 else 1600
            pieces.append(part[:split])
            part = part[split:].lstrip()
        if part:
            pieces.append(part)
    return tuple(Source(id=f"s{i + 1}", excerpt=text) for i, text in enumerate(pieces))


def parse_generated_plan(raw, notes, catalog):
    draft = DraftPlan.model_validate_json(raw)
    questions = []
    for item in draft.questions:
        used = {sid for point in item.rubric for sid in point.source_ids}
        sources = tuple(s for s in catalog if s.id in used)
        question = Question(**item.model_dump(exclude={"rubric"}), rubric=item.rubric, sources=sources)
        questions.append(question)
    return parse_plan(Plan(questions=tuple(questions), reason=draft.reason).model_dump_json(), notes)


class PointAssessment(Model):
    point_id: str
    coverage: Literal["met", "partial", "missing", "incorrect"]
    explanation: str = Field(min_length=1, max_length=600)
    answer_excerpt: str = Field(max_length=1000)
    source_ids: tuple[str, ...] = Field(min_length=1, max_length=6)


class Assessment(Model):
    addresses_question: Literal["yes", "partly", "no"]
    address_reason: str = Field(min_length=1, max_length=500)
    points: tuple[PointAssessment, ...] = Field(min_length=1, max_length=4)
    unverified_information: tuple[str, ...] = Field(max_length=4)
    student_reply: str = Field(min_length=1, max_length=900)
    follow_up_point_id: str
    follow_up_question: str = Field(max_length=500)


class Evaluation(Model):
    context_id: str
    status: Literal["Demonstrated", "Partly demonstrated", "Needs revision"]
    assessment: Assessment
    evidence_support: Literal["supported"] = "supported"
    correct_points: tuple[str, ...]
    missing_or_incorrect_points: tuple[str, ...]
    source_quote: str
    student_reply: str
    follow_up_question: str
    correction: str


def normalize(text):
    return " ".join(text.split())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def verified_quote(quote, notes):
    return bool(normalize(quote)) and normalize(quote) in normalize(notes)


def validate_notes(notes):
    if not 150 <= len(notes.strip()) <= 8000:
        raise ValueError("Add 150–8,000 characters of notes, including definitions and explanations.")
    if len(set(notes.casefold().split())) < 20:
        raise ValueError("Add more substantive material: definitions, relationships, and examples.")


def validate_question(question, notes):
    sources = {s.id: s.excerpt for s in question.sources}
    if len(sources) != len(question.sources):
        raise VerificationError("duplicate_source_id")
    if any(not verified_quote(s.excerpt, notes) for s in question.sources):
        raise VerificationError("source_excerpt_not_in_notes")
    if len({p.id for p in question.rubric}) != len(question.rubric):
        raise VerificationError("duplicate_point_id")
    for point in question.rubric:
        if not point.requirement.strip() or not set(point.source_ids) <= sources.keys():
            raise VerificationError("invalid_rubric_source_reference")


def parse_plan(raw, notes):
    plan = Plan.model_validate_json(raw)
    seen = set()
    for question in plan.questions:
        validate_question(question, notes)
        concept = normalize(question.concept).casefold()
        if concept in seen:
            raise VerificationError("repeated_concept")
        seen.add(concept)
    if not plan.questions and not plan.reason.strip():
        raise VerificationError("missing_insufficient_notes_reason")
    return plan


class PointSupport(Model):
    point_id: str
    supported: bool


class QuestionSupport(Model):
    question_index: int
    question_supported: bool
    points: tuple[PointSupport, ...]


class SupportAudit(Model):
    questions: tuple[QuestionSupport, ...]


def audit_keys(plan):
    return tuple(key for i, q in enumerate(plan.questions) for key in
                 (f"q{i}_question", *(f"q{i}_{p.id}" for p in q.rubric)))


def audit_schema(plan):
    return {"type": "object", "properties": {key: {"type": "boolean"} for key in audit_keys(plan)},
            "required": list(audit_keys(plan)), "additionalProperties": False}


def parse_audit_shape(raw, plan):
    audit = json.loads(raw)
    if not isinstance(audit, dict) or set(audit) != set(audit_keys(plan)) or any(type(v) is not bool for v in audit.values()):
        raise VerificationError("incomplete_support_audit")
    return audit


def parse_support_audit(raw, plan):
    audit = parse_audit_shape(raw, plan)
    for key, supported in audit.items():
        if not supported:
            raise VerificationError("unsupported_question" if key.endswith("_question") else "unsupported_rubric_point")
    return audit


def evaluation_context(notes, language, question, answers, previous, round_id=""):
    payload = {"version": SCHEMA_VERSION, "round_id": round_id, "notes": notes,
               "output_language": language, "question": question.model_dump(),
               "answers": answers, "attempt": len(answers),
               "prior_feedback": [e.model_dump() for e in previous]}
    return payload, digest(payload)


def parse_evaluation(raw, notes, question, answers, context_id):
    validate_question(question, notes)
    result = Assessment.model_validate_json(raw)
    rubric = {p.id: p for p in question.rubric}
    if len(result.points) != len(rubric) or {p.point_id for p in result.points} != rubric.keys():
        raise VerificationError("missing_or_duplicate_point_assessment")
    correct, gaps, unresolved = [], [], []
    for point in result.points:
        requirement = rubric[point.point_id]
        if set(point.source_ids) != set(requirement.source_ids):
            raise VerificationError("invalid_evaluation_source_reference")
        if point.coverage != "missing" and not any(verified_quote(point.answer_excerpt, answer) for answer in answers):
            raise VerificationError("answer_excerpt_not_in_submission")
        detail = requirement.requirement + " — " + point.explanation
        if point.coverage == "met":
            correct.append(detail)
        else:
            gaps.append(detail)
            unresolved.append(point.point_id)
    if not unresolved:
        if result.addresses_question != "yes":
            raise VerificationError("inconsistent_relevance_and_coverage")
        status = "Demonstrated"
    elif any(p.coverage in ("met", "partial") for p in result.points):
        status = "Partly demonstrated"
    else:
        status = "Needs revision"
    follow_up = ""
    if unresolved and len(answers) == 1:
        if result.follow_up_point_id not in unresolved or not result.follow_up_question.strip():
            raise VerificationError("follow_up_not_linked_to_gap")
        follow_up = result.follow_up_question
    source_ids = {sid for point in result.points for sid in point.source_ids}
    # Evidence and corrections come exclusively from the frozen, prevalidated rubric.
    excerpts = "\n\n".join(f"[{s.id}] {s.excerpt}" for s in question.sources if s.id in source_ids)
    return Evaluation(context_id=context_id, status=status, assessment=result,
                      correct_points=tuple(correct), missing_or_incorrect_points=tuple(gaps),
                      source_quote=excerpts, student_reply=result.student_reply,
                      follow_up_question=follow_up,
                      correction=" ".join(question.expected_key_points) if unresolved else "")


@dataclass
class Round:
    question: Question
    answers: list[str] = field(default_factory=list)
    evaluations: list[Evaluation] = field(default_factory=list)
    phase: str = "answer"
    id: str = field(default_factory=lambda: uuid4().hex)
    evaluation_cache: dict = field(default_factory=dict, repr=False)
    _binding: str = field(default="", repr=False)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def submit(self, gateway, notes, language, answer):
        with self._lock:
            if self.phase not in ("answer", "followup") or len(self.answers) >= 2:
                return False
            answer = answer.strip()
            if not answer or len(answer) > 5000:
                raise ValueError("Write a short explanation (1–5,000 characters) before checking.")
            binding = digest([notes, language, self.question.model_dump()])
            if self._binding and binding != self._binding:
                raise ValueError("This round's question or notes changed. Restart to create a new rubric.")
            self._binding = binding
            evaluation = gateway.evaluate(notes, language, self.question, self.answers + [answer],
                                          self.evaluations, cache=self.evaluation_cache, round_id=self.id)
            _, expected = evaluation_context(notes, language, self.question, self.answers + [answer], self.evaluations, self.id)
            if evaluation.context_id != expected:
                raise ValueError("Unable to verify this evaluation")
            # Failure leaves answer form, phase, rubric, and saved history unchanged.
            self.answers.append(answer)
            self.evaluations.append(evaluation)
            self.phase = "feedback" if evaluation.follow_up_question and len(self.answers) == 1 else "done"
            return True

    def follow_up(self):
        if self.phase == "feedback":
            self.phase = "followup"

    @property
    def revealed(self):
        return self.phase == "done" and bool(self.evaluations) and bool(self.evaluations[-1].correction) and self.evaluations[-1].status != "Demonstrated"


@dataclass
class Session:
    notes: str
    language: str
    rounds: list[Round]
    index: int = 0
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        for item in self.rounds:
            item._binding = digest([self.notes, self.language, item.question.model_dump()])

    @property
    def finished(self):
        return self.index >= len(self.rounds)

    def next(self):
        if not self.finished and self.rounds[self.index].phase == "done":
            self.index += 1


def teaching_report(session):
    lines = ["# Your teaching report", "", "Provisional feedback against your supplied notes, not independent fact-checking.", ""]
    demonstrated = 0
    for item in session.rounds:
        if not item.evaluations:
            continue
        result = item.evaluations[-1]
        lines += [f"## {item.question.concept}", f"**{result.status}**", ""]
        if result.status == "Demonstrated":
            demonstrated += 1
            lines += ["You explained this successfully" + (" after a follow-up." if len(item.answers) == 2 else " on your first explanation."), result.student_reply]
        else:
            lines += ["The app revealed a correction; this is not counted as demonstrated.", "Revision task: explain in your own words — " + "; ".join(result.missing_or_incorrect_points), "", result.correction]
        for extra in result.assessment.unverified_information:
            lines += ["Unverified additional information (not used to lower the result): " + extra]
        lines += ["", "Source excerpts:", result.source_quote, ""]
    lines += ["## Takeaway", f"You demonstrated {demonstrated} of {len(session.rounds)} concepts in this session. Revisit the unresolved concepts and try teaching them again."]
    return "\n".join(lines)
