"""Server-side Sarvam access. Never display exception bodies or credentials."""
import base64
import io
import json
import logging
import os
from pathlib import Path
import time
import wave

import httpx
from dotenv import dotenv_values
from sarvamai import SarvamAI
from sarvamai.core.api_error import ApiError
from pydantic import ValidationError

from classroom import (parse_plan, parse_evaluation, validate_notes, validate_question,
                       parse_support_audit, DraftPlan, Assessment, evaluation_context, VerificationError,
                       source_catalog, parse_generated_plan, audit_schema, parse_audit_shape)
from prompts import GENERATE, EVALUATE, REVIEW_EVALUATION, AUDIT_RUBRIC, LANGUAGES

OPTIONS = {"max_retries": 0, "timeout_in_seconds": 45}
SCHEMA_FIELDS = set("questions reason concept misconception student_question rubric sources id excerpt requirement source_ids points point_id coverage explanation answer_excerpt addresses_question address_reason unverified_information student_reply follow_up_point_id follow_up_question status correction source_quote evidence_support support_reason question_index question_supported supported".split())


def validation_reason(exc):
    if isinstance(exc, VerificationError):
        return str(exc)
    if isinstance(exc, ValidationError):
        details = []
        for error in exc.errors(include_input=False, include_url=False)[:5]:
            location = ".".join(str(part) if isinstance(part, int) or part in SCHEMA_FIELDS else "unknown_field" for part in error["loc"])
            details.append(error["type"] + "@" + location)
        return "invalid_response_schema:" + ",".join(details)
    return "invalid_response_schema"


class ClassroomError(Exception):
    """Safe, user-visible error message."""


def configured_key():
    key = os.environ.get("SARVAM_API_KEY")
    if key is None:
        key = dotenv_values(Path(__file__).with_name(".env")).get("SARVAM_API_KEY")
    return (key or "").strip()


def audio_duration(data):
    if not data or len(data) > 5 * 1024 * 1024:
        raise ClassroomError("Use a non-empty recording under 5 MB.")
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            duration = wav.getnframes() / wav.getframerate()
            if wav.getcomptype() != "NONE" or wav.getsampwidth() != 2:
                raise ClassroomError("Use a PCM 16-bit WAV recording from the microphone.")
    except (wave.Error, EOFError, ZeroDivisionError):
        raise ClassroomError("That audio could not be read. Record again, or type your answer.") from None
    if not 0 < duration <= 30:
        raise ClassroomError("Keep your recording between 1 and 30 seconds, or type a longer explanation.")
    return duration


class Gateway:
    def __init__(self):
        key = configured_key()
        if not key:
            raise ClassroomError("Add SARVAM_API_KEY to the local .env file, then try again.")
        self.client = SarvamAI(api_subscription_key=key, timeout=45)
        self.evaluation_cache = {}

    def _call(self, operation):
        for attempt in range(2):
            try:
                return operation()
            except ApiError as exc:
                code = exc.status_code
                if attempt == 0 and (code == 429 or (code and code >= 500)):
                    time.sleep(1)
                    continue
                message = {
                    401: "Sarvam could not authenticate. Check the API key in .env.",
                    403: "Sarvam denied access. Check the key, model access, and account credits.",
                    429: "Sarvam is rate-limiting requests. Wait a moment, then retry.",
                    400: "Sarvam rejected this request. Try a shorter answer or a new recording.",
                    422: "Sarvam could not process this input. Try a shorter answer or a new recording.",
                }.get(code, "Sarvam is temporarily unavailable. Your work is preserved; try again.")
                raise ClassroomError(message) from None
            except (httpx.HTTPError, TimeoutError):
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise ClassroomError("Could not reach Sarvam. Check your connection and retry.") from None
            except Exception:
                raise ClassroomError("The request could not be completed. Your work is preserved; retry.") from None

    def _json(self, prompt, payload, validator, purpose="evaluation", response_model=Assessment, schema=None):
        messages = [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        for attempt in range(2):
            response = self._call(lambda: self.client.chat.completions(
                model="sarvam-105b-conversations", messages=messages,
                temperature=0, max_tokens=3500,
                response_format={"type": "json_schema", "json_schema": {
                    "name": response_model.__name__.lower(), "strict": True,
                    "schema": schema or response_model.model_json_schema()}},
                request_options=OPTIONS,
            ))
            try:
                return validator(response.choices[0].message.content or "")
            except (ValueError, TypeError, IndexError, AttributeError) as exc:
                # Log only bounded internal reason codes, never document text or API bodies.
                reason = validation_reason(exc)
                logging.getLogger(__name__).warning("Sarvam validation: %s / %s", purpose, reason)
                if attempt == 0:
                    messages[0]["content"] = prompt + "\nValidation failed: " + reason + ". Regenerate the JSON using only the supplied rubric and valid source IDs. Include all required fields."
        message = "Unable to verify this evaluation" if purpose == "evaluation" else "Unable to create a supported question and rubric. Please revise the notes or retry."
        raise ClassroomError(message)

    def generate(self, notes, language):
        validate_notes(notes)
        catalog = source_catalog(notes)
        def supported_plan(raw):
            plan = parse_generated_plan(raw, notes, catalog)
            if plan.questions:
                try:
                    schema = audit_schema(plan)
                    audit = self._json(AUDIT_RUBRIC, {"notes": notes, "plan": plan.model_dump(), "required_checks": schema["required"]},
                                       lambda raw: parse_audit_shape(raw, plan), purpose="rubric audit", schema=schema)
                except ClassroomError:
                    raise VerificationError("rubric_audit_failed") from None
                parse_support_audit(json.dumps(audit), plan)
            return plan
        return self._json(GENERATE, {"notes": notes, "source_catalog": [s.model_dump() for s in catalog], "output_language": language}, supported_plan, purpose="generation", response_model=DraftPlan)

    def evaluate(self, notes, language, question, answers, previous, *, cache=None, round_id=""):
        try:
            validate_question(question, notes)
        except ValueError:
            raise ClassroomError("Unable to verify this evaluation") from None
        if len(answers) not in (1, 2) or len(previous) != len(answers) - 1:
            raise ClassroomError("Unable to verify this evaluation")
        if previous:
            _, prior_context = evaluation_context(notes, language, question, answers[:-1], [], round_id)
            if previous[0].context_id != prior_context:
                raise ClassroomError("Unable to verify this evaluation")
        payload, key = evaluation_context(notes, language, question, answers, previous, round_id)
        saved = cache if cache is not None else self.evaluation_cache
        if key not in saved:
            validator = lambda raw: parse_evaluation(raw, notes, question, answers, key)
            result = self._json(EVALUATE, payload, validator)
            if result.status != "Demonstrated":
                review = {**payload, "proposed_assessment": result.assessment.model_dump()}
                result = self._json(REVIEW_EVALUATION, review, validator)
            saved[key] = result
        return saved[key]

    def speak(self, text, language):
        if not text.strip() or len(text) > 2500:
            raise ClassroomError("This message is too long for voice. You can read it below.")
        response = self._call(lambda: self.client.text_to_speech.convert(
            text=text, language_code=LANGUAGES[language], model="bulbul:v3", speaker="shubh",
            speech_sample_rate=16000, output_audio_codec="wav", request_options=OPTIONS,
        ))
        try:
            audio = base64.b64decode(response.audios[0], validate=True)
            if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
                raise ValueError()
            return audio
        except (ValueError, IndexError, AttributeError):
            raise ClassroomError("Voice could not be prepared. Continue with the visible question.") from None

    def transcribe(self, data):
        audio_duration(data)
        response = self._call(lambda: self.client.speech_to_text.transcribe(
            file=("answer.wav", data, "audio/wav"), model="saaras:v4", mode="codemix",
            language_code="unknown", request_options=OPTIONS,
        ))
        transcript = (response.transcript or "").strip()
        if not transcript:
            raise ClassroomError("No speech was recognized. Try recording again, or type your answer.")
        return transcript
