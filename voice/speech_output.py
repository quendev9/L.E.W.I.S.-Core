
import queue
import re
import threading
import time

try:
    import pyttsx3
except ModuleNotFoundError as error:  # pragma: no cover - optional dependency
    pyttsx3 = None
    _PYTTSX3_IMPORT_ERROR = str(error)
else:
    _PYTTSX3_IMPORT_ERROR = None

from core.event_logger import log_event


_engine = None
_speech_lock = threading.Lock()
_stop_requested = threading.Event()
_speech_requests = queue.Queue()
_speech_worker_lock = threading.Lock()
_speech_worker_thread = None


def _speech_cancelled(cancel_event=None):
    return _stop_requested.is_set() or bool(
        cancel_event and cancel_event.is_set()
    )


def _get_engine():
    """Initialize the installed local system speech voice."""
    global _engine

    if pyttsx3 is None:
        raise RuntimeError(
            "pyttsx3 is unavailable in this Python environment: "
            f"{_PYTTSX3_IMPORT_ERROR}"
        )

    if _engine is None:
        _engine = pyttsx3.init()
        _engine.setProperty("rate", 175)
        _engine.setProperty("volume", 1.0)

    return _engine


def _prepare_speech(text):
    """Return readable speech text without changing the displayed Markdown."""
    if not isinstance(text, str) or not text.strip():
        return ""

    preserved = []

    def hold(value):
        token = f"LEWISPRESERVED{len(preserved)}TOKEN"
        preserved.append(value)
        return token

    def keep_code_block(match):
        return hold(match.group(2).strip())

    text = re.sub(
        r"```[ \t]*([^\n]*)\n?(.*?)```",
        keep_code_block,
        text,
        flags=re.S,
    )
    text = re.sub(r"`([^`\n]*)`", lambda match: hold(match.group(1)), text)
    text = re.sub(
        r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+[^)]*)?\)",
        lambda match: match.group(1),
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)(?:\s+[^)]*)?\)",
        lambda match: f"{match.group(1)} ({match.group(2)})",
        text,
    )
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(?<!\w)[*_](.*?)[*_](?!\w)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
    text = re.sub(
        r"(?m)^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$",
        "",
        text,
    )
    text = re.sub(r"^\s*[-*+]\s+", ". ", text, flags=re.M)
    text = re.sub(r"^\s*(\d+[.)])\s+", r"\1 ", text, flags=re.M)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    text = re.sub(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", "", text, flags=re.M)
    text = re.sub(
        r"(?m)^\s*\|(.+)\|\s*$",
        lambda match: match.group(1).replace("|", ", "),
        text,
    )
    text = re.sub(r"(?<!\w)[*_~]+|[*_~]+(?!\w)", "", text)
    text = re.sub(r"\n{2,}", ". ", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^\.\s+", "", text)

    for index, value in enumerate(preserved):
        text = text.replace(f"LEWISPRESERVED{index}TOKEN", value)

    return text.strip()


def _speak_local(text, cancel_event=None, on_playback_start=None):
    """Speak with the offline system voice and confirm utterance completion."""
    playback_started = time.perf_counter()
    engine = _get_engine()
    finished_utterances = []
    started_utterance = threading.Event()
    engine_errors = []

    def handle_started(name):
        started_utterance.set()
        if on_playback_start:
            on_playback_start()
        log_event(
            "VOICE PLAYBACK STARTUP: local voice "
            f"{(time.perf_counter() - playback_started) * 1000:.0f} ms"
        )

    def handle_finished(name, completed):
        finished_utterances.append(completed)

    def handle_error(name, exception):
        engine_errors.append(exception)

    started_token = engine.connect("started-utterance", handle_started)
    finished_token = engine.connect("finished-utterance", handle_finished)
    error_token = engine.connect("error", handle_error)
    loop_started = False
    stop_sent = False

    try:
        if _speech_cancelled(cancel_event):
            return False

        engine.say(text)
        if _speech_cancelled(cancel_event):
            engine.stop()
            return False
        engine.startLoop(False)
        loop_started = True
        deadline = time.monotonic() + max(30.0, len(text) * 0.25 + 15.0)

        while not finished_utterances:
            if _speech_cancelled(cancel_event) and not stop_sent:
                engine.stop()
                stop_sent = True
            engine.iterate()

            if engine_errors:
                raise RuntimeError(
                    f"The local speech engine failed: {engine_errors[0]}"
                ) from engine_errors[0]
            if finished_utterances:
                break
            if (
                started_utterance.is_set()
                and not engine.isBusy()
                and not _speech_cancelled(cancel_event)
            ):
                raise RuntimeError(
                    "The local speech engine returned without completing "
                    "an utterance."
                )
            if time.monotonic() >= deadline:
                engine.stop()
                raise RuntimeError("Local speech playback timed out.")
            if not finished_utterances:
                time.sleep(0.01)

        if _speech_cancelled(cancel_event):
            return False
        if not finished_utterances[-1]:
            raise RuntimeError(
                "The local speech engine reported incomplete playback."
            )
        return True
    finally:
        if loop_started:
            engine.endLoop()
        engine.disconnect(started_token)
        engine.disconnect(finished_token)
        engine.disconnect(error_token)


def _speech_worker():
    while True:
        request = _speech_requests.get()
        try:
            request["completed"] = _speak_local(
                request["text"],
                request["cancel_event"],
                request["on_playback_start"],
            )
        except Exception as error:
            request["error"] = error
        finally:
            request["finished"].set()
            _speech_requests.task_done()


def _start_speech_worker():
    global _speech_worker_thread

    with _speech_worker_lock:
        if _speech_worker_thread is None or not _speech_worker_thread.is_alive():
            _speech_worker_thread = threading.Thread(
                target=_speech_worker,
                name="LEWIS-Local-TTS",
                daemon=True,
            )
            _speech_worker_thread.start()


def speak(text, cancel_event=None, on_playback_start=None):
    """Speak locally without requiring network access or cloud credentials."""
    clean_text = _prepare_speech(text)
    if not clean_text:
        return False

    with _speech_lock:
        if cancel_event and cancel_event.is_set():
            return False

        _stop_requested.clear()
        if cancel_event and cancel_event.is_set():
            return False

        request = {
            "text": clean_text,
            "cancel_event": cancel_event,
            "on_playback_start": on_playback_start,
            "finished": threading.Event(),
        }
        _start_speech_worker()
        _speech_requests.put(request)
        request["finished"].wait()

        error = request.get("error")
        if error is not None:
            print(f"[LEWIS voice] Local speech failed: {error}")
            log_event(f"VOICE PLAYBACK FAILED: {error}")
            return False

        return request["completed"] and not _speech_cancelled(cancel_event)


def stop_speaking():
    """Request speech to stop; the owning SAPI thread performs the stop."""
    _stop_requested.set()


def was_stop_requested():
    """Report whether the most recent speech operation was interrupted."""
    return _stop_requested.is_set()
