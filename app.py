import hashlib
import html

import streamlit as st

from classroom import Round, Session, teaching_report, SCHEMA_VERSION
from prompts import LANGUAGES, SAMPLE_NOTES
from sarvam_client import ClassroomError, Gateway, configured_key
from note_uploads import extract_notes, UploadError, confirm_source

st.set_page_config(page_title="Ulta Classroom", page_icon="↗", layout="centered")
st.markdown("""<style>
.block-container {max-width: 860px; padding-top: 2.7rem; padding-bottom: 4rem;}
h1 {font-size: clamp(2.4rem, 6vw, 3.5rem) !important; letter-spacing: -.06em; line-height: 1.1 !important;}
h2 {letter-spacing: -.035em;}
.eyebrow {color:#D9F577; font-size:.75rem; font-weight:700; letter-spacing:.16em; margin-bottom:1.4rem;}
.intro {color:#B4BBC4; font-size:1.1rem; max-width:38rem; line-height:1.6;}
.student-card {background:#1C2632; border:1px solid #344353; border-radius:20px; padding:1.6rem; margin:1rem 0;}
.badge {display:inline-flex; align-items:center; justify-content:center; width:34px; height:34px; border-radius:50%; background:#D9F577; color:#111820; font-weight:800; margin-right:10px;}
.student-name {color:#F4EEDD; font-weight:600; font-size:.9rem;}
.student-question {font-size:1.4rem; line-height:1.6; color:#F4EEDD; margin:1rem 0 .2rem; white-space:pre-wrap;}
.steps {display:flex; gap:1rem; flex-wrap:wrap; color:#AEB8C5; font-size:.85rem; padding:1rem 0 1.5rem;}
.steps b {color:#D9F577; margin-right:.35rem;}
div[data-testid="stForm"] {border-color:#344353; border-radius:16px;}
button[kind="primary"], button[kind="primaryFormSubmit"],
button[kind="primaryFormSubmit"] p {color:#111820 !important; font-weight:700 !important;}
</style>""", unsafe_allow_html=True)


def reset():
    lesson = st.session_state.get("lesson")
    if lesson:
        # Streamlit drops hidden widget state; restore the source before returning to setup.
        st.session_state.notes = lesson.notes
        st.session_state.language = lesson.language
    for key in list(st.session_state):
        if key not in ("notes", "language"):
            del st.session_state[key]


def cleanup_turn():
    for key in list(st.session_state):
        if key.startswith(("answer_", "record_", "transcript_")):
            del st.session_state[key]


def edit_source():
    st.session_state.notes = st.session_state.lesson.notes
    st.session_state.source_mode = "Paste notes"
    st.session_state.source_edit = True


def student_card(text):
    st.markdown('<div class="student-card"><span class="badge">U</span>'
                '<span class="student-name">Your curious classmate</span>'
                f'<div class="student-question">{html.escape(text)}</div></div>', unsafe_allow_html=True)


def voice(text, language):
    cache = st.session_state.setdefault("voice_cache", {})
    key = hashlib.sha256((language + text).encode()).hexdigest()
    if key not in cache:
        with st.spinner("Preparing voice…"):
            try:
                cache[key] = {"audio": Gateway().speak(text, language)}
            except ClassroomError as exc:
                cache[key] = {"error": str(exc)}
    entry = cache[key]
    if "audio" in entry:
        st.audio(entry["audio"], format="audio/wav")
    else:
        st.caption("Voice unavailable. " + entry["error"])
        if st.button("Retry voice", key="voice_" + key):
            del cache[key]
            st.rerun()


def setup():
    st.markdown('<div class="eyebrow">THE BEST WAY TO LEARN? SWITCH SIDES.</div>', unsafe_allow_html=True)
    st.title("Ulta Classroom")
    st.markdown("### You haven’t understood it until you can teach it.")
    st.markdown('<p class="intro">Your AI classmate has misunderstood something. Can you explain it clearly?</p>', unsafe_allow_html=True)
    st.markdown('<div class="steps"><span><b>01</b> Bring your notes</span><span><b>02</b> Teach a classmate</span><span><b>03</b> Find your gaps</span></div>', unsafe_allow_html=True)
    ready = bool(configured_key())
    if not ready:
        st.info("Add SARVAM_API_KEY to your local .env file to start. You can prepare your notes below.")
    with st.container(border=True):
        left, right = st.columns([3, 2])
        left.markdown("#### What are we learning?")
        if right.button("Load sample topic", use_container_width=True):
            st.session_state.notes = SAMPLE_NOTES
            st.session_state.source_mode = "Paste notes"
        st.caption("Try BCC vs FCC crystal structures, or bring your own study notes.")
        mode = st.radio("Notes source", ("Paste notes", "Upload a file"), key="source_mode", horizontal=True)
        source_ready = True
        if mode == "Upload a file":
            uploaded = st.file_uploader("Upload one PDF, DOCX, or TXT · up to 10 MB", type=["pdf", "docx", "txt"], accept_multiple_files=False, key="notes_file")
            source_ready = False
            if uploaded is not None:
                data = uploaded.getvalue()
                fingerprint = hashlib.sha256(uploaded.name.encode() + data).hexdigest()
                if st.session_state.get("upload_fingerprint") != fingerprint:
                    st.session_state.upload_fingerprint = fingerprint
                    st.session_state.upload_preview = ""
                    st.session_state.pop("upload_error", None)
                    try:
                        st.session_state.upload_preview = extract_notes(uploaded.name, data)
                    except UploadError as exc:
                        st.session_state.upload_error = str(exc)
                if st.session_state.get("upload_error"):
                    st.error(st.session_state.upload_error)
                else:
                    source_ready = True
            else:
                st.session_state.pop("upload_fingerprint", None)
                st.session_state.upload_preview = ""
                st.session_state.pop("upload_error", None)
            notes = st.text_area("Editable extracted text · keep the section you want to study", key="upload_preview", height=235, disabled=not source_ready)
            st.caption("Review the extraction, correct mistakes, and remove sections you do not want to study. Nothing is silently shortened.")
        else:
            notes = st.text_area("Study notes", key="notes", height=235,
                                 placeholder="Paste definitions, explanations, and examples. Give your classmate something to learn from.")
        st.caption(f"{len(notes.strip()):,} characters selected · allowed: 150–8,000")
        too_long = len(notes.strip()) > 8000
        if too_long:
            st.error("Your selected text exceeds 8,000 characters. Shorten the preview or select a smaller section before starting.")
        language = st.selectbox("AI reply language", list(LANGUAGES), key="language")
        st.caption("Speak or type in English, Hindi, Marathi, or a mix. Up to 3 concepts · one follow-up each.")
        st.caption("By choosing Start teaching, you confirm this preview. The selected text and your answers will be sent to Sarvam for processing. Confirming a source starts a fresh lesson and clears the previous questions, rubric, answers, and report.")
        if st.button("Start teaching", type="primary", use_container_width=True, disabled=not ready or not source_ready or too_long):
            try:
                confirm_source(st.session_state, notes, language)
                with st.spinner("Thinking…"):
                    plan = Gateway().generate(notes, language)
                if not plan.questions:
                    st.warning(plan.reason)
                else:
                    st.session_state.lesson = Session(notes, language, [Round(q) for q in plan.questions])
                    st.rerun()
            except (ClassroomError, ValueError) as exc:
                st.error(str(exc))
        if "lesson" in st.session_state and st.session_state.get("source_edit"):
            if st.button("Keep current lesson"):
                del st.session_state.source_edit
                st.rerun()
    st.caption("Feedback is based on your notes. It helps you practise explaining; it is not a mastery score or independent fact-check.")


def feedback(result, revealed):
    status_renderer = st.success if result.status == "Demonstrated" else st.warning
    status_renderer(result.status)
    st.caption("Addresses the question: " + result.assessment.addresses_question + ". " + result.assessment.address_reason)
    for extra in result.assessment.unverified_information:
        st.caption("Unverified additional information (not used to lower your result): " + extra)
    if result.correct_points:
        st.markdown("**What you explained well**")
        for point in result.correct_points:
            st.write("✓ " + point)
    if result.missing_or_incorrect_points:
        st.markdown("**What needs another look**")
        for point in result.missing_or_incorrect_points:
            st.write("• " + point)
    if result.source_quote:
        with st.expander("Supporting excerpt · verified against your notes"):
            st.text(result.source_quote)
    else:
        st.caption("No supporting excerpt is available; this is not a supported judgment.")
    st.write(result.student_reply)
    if revealed:
        st.info("A correction from your notes\n\n" + result.correction)
        st.caption("This correction was revealed by the app. It is not counted as understanding you demonstrated.")


def answer_form(lesson, current):
    attempt = len(current.answers)
    turn = f"{current.id}_{attempt}"
    answer_key = "answer_" + turn
    st.markdown("#### Your turn to teach")
    st.caption("Explain the reasoning in your own words. Type below, or record up to 30 seconds.")
    recording = st.audio_input("Record an explanation", sample_rate=16000, key="record_" + turn)
    if st.button("Transcribe", disabled=recording is None, key="transcribe_" + turn):
        try:
            data = recording.getvalue()
            fingerprint = hashlib.sha256(data).hexdigest()
            cache_key = "transcript_" + turn
            cached = st.session_state.get(cache_key)
            if not cached or cached[0] != fingerprint:
                with st.spinner("Transcribing…"):
                    transcript = Gateway().transcribe(data)
                st.session_state[cache_key] = (fingerprint, transcript)
            st.session_state[answer_key] = st.session_state[cache_key][1]
            st.success("Transcript ready. Review and edit it before checking your explanation.")
        except ClassroomError as exc:
            st.warning(str(exc) + " You can still type below.")
    with st.form("explanation_" + turn):
        answer = st.text_area("Your explanation / editable transcript", key=answer_key, height=160, max_chars=5000,
                              placeholder="I see why you might think that. Here’s what’s actually happening…")
        st.caption("Review any transcript first. Only this text is evaluated when you click below.")
        check = st.form_submit_button("Check my explanation", type="primary", use_container_width=True)
    if check:
        try:
            with st.spinner("Thinking…"):
                current.submit(Gateway(), lesson.notes, lesson.language, answer)
            st.rerun()
        except (ClassroomError, ValueError) as exc:
            st.error(str(exc))


def classroom(lesson):
    top, action = st.columns([4, 1])
    top.markdown("### ↗ Ulta Classroom")
    action.button("Restart", on_click=reset)
    st.button("Change source", on_click=edit_source)
    if lesson.finished:
        st.markdown('<div class="eyebrow">YOU TOOK THE TEACHER’S SEAT.</div>', unsafe_allow_html=True)
        report = teaching_report(lesson)
        st.markdown(report)
        st.download_button("Download your report", data=report, file_name="ulta-teaching-report.md", mime="text/markdown")
        st.button("Teach another topic", type="primary", on_click=reset)
        return
    current = lesson.rounds[lesson.index]
    st.progress(lesson.index / len(lesson.rounds), text=f"Round {lesson.index + 1} of {len(lesson.rounds)} · {lesson.language}")
    st.caption(current.question.concept)
    with st.expander("Your source notes"):
        st.text(lesson.notes)
    st.markdown("**Deliberate misconception — your task is to correct it.**")
    student_card(current.question.student_question)
    voice(current.question.student_question, lesson.language)
    for i, (answer, evaluation) in enumerate(zip(current.answers, current.evaluations)):
        with st.container(border=True):
            st.caption("YOUR EXPLANATION" if i == 0 else "YOUR FOLLOW-UP")
            st.text(answer)
            feedback(evaluation, current.revealed and i == len(current.evaluations) - 1)
    if current.phase == "feedback":
        st.markdown("**One more thought…**")
        st.write(current.evaluations[-1].follow_up_question)
        if st.button("Answer follow-up", type="primary"):
            cleanup_turn()
            current.follow_up()
            st.rerun()
    elif current.phase == "followup":
        student_card(current.evaluations[-1].follow_up_question)
        voice(current.evaluations[-1].follow_up_question, lesson.language)
        answer_form(lesson, current)
    elif current.phase == "answer":
        answer_form(lesson, current)
    else:
        label = "See teaching report" if lesson.index == len(lesson.rounds) - 1 else "Next concept"
        if st.button(label, type="primary", use_container_width=True):
            cleanup_turn()
            lesson.next()
            st.rerun()
    st.caption("Provisional feedback against your notes · explain the idea, not just the answer.")


if "lesson" in st.session_state and st.session_state.lesson.__dict__.get("schema_version") != SCHEMA_VERSION:
    st.warning("This lesson uses an older rubric. Your notes and current answer are preserved below. Restart to create a verified rubric before continuing.")
    st.text(st.session_state.lesson.notes)
    for key in list(st.session_state):
        if key.startswith("answer_") and st.session_state[key]:
            st.text(st.session_state[key])
    st.button("Restart", on_click=reset)
elif "lesson" in st.session_state and not st.session_state.get("source_edit"):
    classroom(st.session_state.lesson)
else:
    setup()
