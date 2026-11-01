# Evaluation reliability and upload verification

Checked on 1 November 2026.

## What was reproduced

The original evaluator had to generate a new verbatim source quote on every answer. A controlled response with a correct assessment but a paraphrased quote reproduced the exact reported message after two attempts: “The AI response could not be verified against your notes. Please retry; no judgment was saved.” The generic error also covered schema failures, so it did not establish that the learner's answer was unsupported.

Live tests against a fixed packing-factor question reproduced a separate semantic problem. A paraphrase explaining 74 occupied units out of 100 and an answer explicitly mentioning occupied volume fraction were both marked partial for failing to give an explicit definition. Their quotes were valid. Thus this was not merely a citation-format issue. Later live testing also exposed missing follow-up fields, motivating API-level response schemas and safe field-level validation diagnostics.

The running website's complete visible import error was `ImportError: cannot import name 'SCHEMA_VERSION' from 'classroom'`, at app.py's classroom import. A fresh process imported that exact local module and all nested dependencies successfully. The existing Streamlit worker had stale module state. Its port ownership and launch command were verified, then that worker was restarted. The new server's terminal startup logs and actual browser page were checked. Source polling is enabled; debug error details were restored to disabled after diagnosis.

## Changes

- A source catalog is cut directly from the confirmed notes. Exact excerpt membership is checked locally; models select source IDs instead of generating fresh quotations.
- Questions contain immutable required points with per-point evidence IDs. A separate pre-presentation support audit uses a schema whose boolean keys are generated from the exact question/point IDs. Unsupported questions are regenerated once. A real but irrelevant quote is not sufficient support.
- Evaluation checks relevance and each rubric point independently. The server validates reference ownership and cited answer excerpts, attaches the original notes excerpts, and derives the overall status. Source support is a separate validation outcome, never a learner correctness category.
- Non-complete assessments receive one semantic review. This can correct overly literal grading, but cannot bypass source-reference or answer-excerpt validation. A failed review does not save the provisional grade.
- Specific missing points and a follow-up linked to one unresolved point replace vague partial judgments. Corrections come from the audited factual rubric.
- Round IDs, immutable rubrics, source bindings, context hashes, transactional commits, and per-round caches prevent stale/cross-round results and duplicate successful submissions. A changed source clears the whole lesson only after valid explicit confirmation.
- Upload extraction is in memory. The editable preview is never silently truncated. Only its confirmed contents become the session's source; original uploaded text excluded by the user is not sent for generation or grading.

## Test results

42 offline tests passed using synthetic documents and mocked Sarvam responses. They cover PDF/TXT/DOCX extraction (including nested tables and encodings), size limits, corrupt/empty/password-protected files, image-only PDFs, source confirmation, source replacement, state transitions, transcript review, evidence rejection, bounded retries, semantic-review failures, cached submissions, and follow-up context.

Final live checks with a fixed question and frozen rubric:

| Case | Result |
| --- | --- |
| Fully correct | Demonstrated |
| Correct but incomplete | Partly demonstrated |
| Incorrect | Needs revision |
| Correct paraphrase | Demonstrated |
| Correct answer with harmless extras | Demonstrated |
| Code-mixed correct answer | Demonstrated |
| Follow-up using the original rubric and history | Demonstrated |
| Repeated identical request | Reused the saved result |

Unsupported questions, invalid source references, malformed responses, and stale contexts were tested with controlled mocked failures. The system refused to grade or advance on continued verification failure. Live generation/audit and evaluation from extracted TXT also passed. The full three-round live smoke test passed, as did TTS-to-STT round trips in English, Hindi, and Marathi using generated audio.

Browser verification used installed Edge in headless mode against the running Streamlit server: page load without ImportError, real file-picker upload for TXT/PDF/DOCX, editable previews, preview editing, and starting a live question with audio controls and the answer form. Desktop and mobile screenshots were inspected; no horizontal overflow was detected in the mobile upload screen.

## Limits

Semantic grading and rubric support auditing still use a model; they are not proofs and fresh requests are not inherently deterministic. Cached identical contexts are stable only while the session exists. The checks above are controlled regression cases, not a comprehensive accuracy benchmark.

Physical microphone capture/browser permissions and real-world accented or code-mixed audio were not tested. Speech API checks used synthetic audio. PDF reading order and unusual Word features can require manual correction in the preview; no OCR is implemented. DOCX extraction covers body paragraphs and tables, not every possible text box, header, or tracked-change representation. Password-protected documents must be unlocked externally.
