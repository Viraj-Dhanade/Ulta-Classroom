# Ulta Classroom

**You haven’t understood it until you can teach it.**

A local Streamlit app where you correct a curious AI classmate using your study notes. It supports English, Hindi, Marathi, and code-mixed spoken answers. No database, accounts, or public deployment.

Choose **Paste notes** or **Upload a file**. Upload one PDF, DOCX, or TXT up to 10 MB, then correct the extracted preview and keep the section you want to study. **Start teaching** confirms that text and sends it to Sarvam. **Change source** lets you confirm different notes and resets the previous lesson.

PDF extraction uses pypdf; DOCX extraction uses python-docx and includes tables; TXT supports UTF-8, BOM-marked Unicode, and Windows-1252 fallback. Scanned PDFs need OCR, which is not included. Encrypted, empty, corrupt, and unsupported documents produce actionable messages. Files stay in memory; the app does not save uploads or log their contents. Text over 8,000 characters stays intact in the preview and must be shortened before starting.

## Run

From this project directory in PowerShell:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Open <http://localhost:8501>. Keep the terminal running; Ctrl+C stops the app.

Put your key in the project's `.env` file:

```dotenv
SARVAM_API_KEY=
```

Paste the actual value after `=` locally. `.env` is ignored by Git. An existing process environment variable takes precedence. The key stays server-side; errors never display raw API responses. `.env.example` provides the empty setting for a new checkout.

## Demo: BCC vs FCC

1. Click **Load sample topic**, choose a reply language, then **Start teaching**.
2. For the packing misconception, try: “BCC has an atom in the centre, so it must pack more tightly.” Check the explanation to see targeted feedback.
3. Answer the follow-up: “Packing factor is the fraction of volume occupied by atoms. FCC is about 0.74 and BCC about 0.68, so the centre atom alone does not determine packing.”
4. For atom counting, explain corner sharing (1/8 each), face sharing (1/2 each), and totals of 2 for BCC and 4 for FCC.
5. For coordination, distinguish nearest neighbours (8 or 12) from atoms per unit cell (2 or 4).
6. Complete the concepts and download the Markdown teaching report. The model chooses the question order.

To use voice, record up to **30 seconds**, click **Transcribe**, edit the text, then click **Check my explanation**. Transcription is never graded automatically. Questions have an explicit audio play control. Typed answers remain available when either speech API fails.

## Behavior and limits

- Notes: 150–8,000 characters, with substantive definitions or explanations.
- Up to three distinct supported concepts; fewer if the notes cannot support three.
- At most two explanations per concept: initial answer and one follow-up.
- Generation and evaluation use schema-constrained JSON and server-side validation. The server creates a source catalog directly from the confirmed text; the model references IDs rather than rewriting quotations. Each question's immutable rubric is checked for source support before presentation. Unsupported questions regenerate once, then produce a recoverable error.
- Relevance, coverage of each required point, and evidence support are separate. Grades are derived from per-point coverage. Non-complete judgments receive one semantic review to catch demands for exact wording. Harmless additional information is labeled unverified when relevant and does not lower the grade merely because it is absent from notes.
- Invalid evidence IDs or malformed responses retry once per stage. Continued failure displays **Unable to verify this evaluation**, preserves the answer, and saves no grade or round transition. Evidence failure never means the student is incorrect.
- Identical evaluations are reused within their round, keyed by the complete notes, frozen question/rubric, language, answer history, and attempt context. Temperature is zero; this does not make fresh model calls inherently deterministic.
- A quote match verifies the excerpt's presence, not the correctness of the notes or the model's interpretation. Feedback is provisional.
- Unresolved concepts get a correction and revision task. Revealed answers are not counted as demonstrated understanding.
- Sarvam requests use a 45-second timeout, with one retry for transient network, rate-limit, or server errors. A JSON validation retry can make the chat operation longer.
- Questions and voice are cached in the current session; checking an answer is an explicit form submission. Recordings and transcripts are held in memory and cleared on advancing/restarting. The app writes no recordings to disk.
- Recordings must be PCM 16-bit WAV, at most 30 seconds and 5 MB. The browser microphone widget records at 16 kHz. Longer recordings are rejected with a typed-answer fallback.
- Session state is temporary; a fresh browser session or server restart can lose progress. Notes and submitted answers/audio are sent to Sarvam for processing.

## APIs

Verified against the official docs and installed SDK:

- [Chat completion](https://docs.sarvam.ai/api/token-factory/chat-completions): `sarvam-105b-conversations`, JSON output.
- [Speech recognition](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/rest-api): `saaras:v4`, `codemix`, automatic language detection; synchronous requests up to 30 seconds.
- [Speech synthesis](https://docs.sarvam.ai/api-reference/text-to-speech/convert): stable `bulbul:v3`, `shubh`, WAV at 16 kHz; language codes `en-IN`, `hi-IN`, `mr-IN`.

## Verification

Verified on 1 November 2026: all 42 offline tests passed; live generation, evaluation,
one follow-up, three-round completion, and report creation passed. Live TTS and STT
round trips passed for English, Hindi, and Marathi using generated speech. The local
server health check returned `ok`. Desktop and mobile setup screens and a live question
screen were inspected in headless Edge; the mobile setup had no horizontal overflow.
All three file formats were uploaded through the actual browser, their editable previews appeared,
and a confirmed uploaded preview started a live lesson. Fixed-rubric live cases covered correct,
incomplete, incorrect, paraphrased, code-mixed, and harmless-extra answers. Physical microphone
capture and permissions remain a manual check on your device. See [investigation and results](docs/verification.md).

Offline tests use fake API responses and do not spend credits:

```powershell
python -m unittest discover -s tests -v
```

Explicit live verification uses the saved key and spends Sarvam credits:

```powershell
python live_smoke.py
python live_evaluation_checks.py
```

It exercises generation, a misconception and follow-up, three-round completion, and synthetic speech-to-text round trips in all three languages. Synthetic round trips do not verify the physical microphone, browser permission prompt, or recognition quality for real code-mixed speech.

Files: `app.py` (interface), `classroom.py` (validation and state), `sarvam_client.py` (API calls), `prompts.py` (prompts and sample), `tests/` (offline checks), `live_smoke.py` (explicit live checks). The original `sarvam_chat.py` remains available for the minimal first-call example.

If an already-running server reports an import that exists in the source, stop it with Ctrl+C and restart using the run command above. The project uses Streamlit's polling watcher to detect source changes in synced folders. Old rubric sessions are explicitly gated rather than silently migrated into new grading state.
