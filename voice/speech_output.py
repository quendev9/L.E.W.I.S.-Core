
import os
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

try:
    import pyttsx3
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pyttsx3 = None

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    def load_dotenv():
        return False

try:
    from fishaudio import FishAudio
    from fishaudio.utils import save
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    FishAudio = None

    def save(*args, **kwargs):
        raise RuntimeError("fishaudio is unavailable")

from core.event_logger import log_event


load_dotenv()

VOICE_ID = "e13fa398a7f445a685316a3de6089ce7"
FISH_MODEL = "s2.1-pro-free"

_engine = None
_fish_client = None
_speech_lock = threading.Lock()
_stop_requested = threading.Event()


def _speech_cancelled(cancel_event=None):
    return _stop_requested.is_set() or bool(
        cancel_event and cancel_event.is_set()
    )


def _mci_command(command):
    from ctypes import create_unicode_buffer, windll

    output = create_unicode_buffer(256)
    error_code = int(
        windll.winmm.mciSendStringW(command, output, len(output), 0)
    )

    if error_code:
        error = create_unicode_buffer(256)
        windll.winmm.mciGetErrorStringW(error_code, error, len(error))
        raise RuntimeError(
            error.value or f"Windows audio command failed ({error_code})."
        )

    return output.value


def _play_fish_audio(audio_path, cancel_event=None, on_playback_start=None):
    if os.name != "nt":
        from playsound import playsound

        if on_playback_start:
            on_playback_start()
        playsound(str(audio_path))
        return not _speech_cancelled(cancel_event)

    alias = f"lewis_{uuid.uuid4().hex}"
    opened = False

    try:
        _mci_command(f'open "{audio_path}" alias {alias}')
        opened = True
        _mci_command(f"set {alias} time format milliseconds")

        if _speech_cancelled(cancel_event):
            return False

        _mci_command(f"play {alias}")
        if on_playback_start:
            on_playback_start()

        while True:
            if _speech_cancelled(cancel_event):
                _mci_command(f"stop {alias}")
                return False

            if _mci_command(f"status {alias} mode").lower() == "stopped":
                return True

            time.sleep(0.05)
    finally:
        if opened:
            _mci_command(f"close {alias}")


def _get_engine():
    """Initialize the local fallback voice when needed."""
    global _engine

    if pyttsx3 is None:
        raise RuntimeError("pyttsx3 is unavailable")

    if _engine is None:
        _engine = pyttsx3.init()
        _engine.setProperty("rate", 175)
        _engine.setProperty("volume", 1.0)

    return _engine


def _get_fish_client():
    """Create the Fish Audio client using the key stored in .env."""
    global _fish_client

    if FishAudio is None:
        raise RuntimeError("Fish Audio SDK is unavailable")

    if _fish_client is None:
        api_key = os.getenv("FISH_API_KEY")

        if not api_key:
            raise RuntimeError("FISH_API_KEY is missing from .env")

        _fish_client = FishAudio(api_key=api_key)

    return _fish_client


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


def _speak_fish(text, cancel_event=None, on_playback_start=None):
    """Generate and play speech using Fish Audio."""
    client = _get_fish_client()

    generation_started = time.perf_counter()
    audio = client.tts.convert(
        text=text,
        reference_id=VOICE_ID,
        model=FISH_MODEL,
        format="mp3",
    )

    # Save to a temporary file rather than leaving audio files in the repo.
    with tempfile.NamedTemporaryFile(
        suffix=".mp3", delete=False
    ) as audio_file:
        audio_path = Path(audio_file.name)

    try:
        save(audio, str(audio_path))
        log_event(
            "VOICE TTS GENERATION: "
            f"{(time.perf_counter() - generation_started) * 1000:.0f} ms"
        )

        if _speech_cancelled(cancel_event):
            return

        log_event(
            "VOICE PLAYBACK STARTUP: "
            f"{(time.perf_counter() - generation_started) * 1000:.0f} ms"
        )
        _play_fish_audio(audio_path, cancel_event, on_playback_start)
    finally:
        try:
            audio_path.unlink(missing_ok=True)
        except OSError:
            pass


def _speak_local(text, on_playback_start=None):
    """Speak with the existing offline Windows/system voice."""
    playback_started = time.perf_counter()
    engine = _get_engine()
    engine.say(text)
    if on_playback_start:
        on_playback_start()
    log_event(
        "VOICE PLAYBACK STARTUP: local voice "
        f"{(time.perf_counter() - playback_started) * 1000:.0f} ms"
    )
    engine.runAndWait()


def speak(text, cancel_event=None, on_playback_start=None):
    """Speak with Fish Audio, falling back to the local voice on errors."""
    clean_text = _prepare_speech(text)
    if not clean_text:
        return False

    with _speech_lock:
        if cancel_event and cancel_event.is_set():
            return False

        _stop_requested.clear()
        if cancel_event and cancel_event.is_set():
            return False

        try:
            _speak_fish(clean_text, cancel_event, on_playback_start)
        except Exception as error:
            print(f"[LEWIS voice] Fish Audio unavailable: {error}")
            print("[LEWIS voice] Using local fallback voice.")

            try:
                if not _stop_requested.is_set() and not (
                    cancel_event and cancel_event.is_set()
                ):
                    _speak_local(clean_text, on_playback_start)
            except Exception as fallback_error:
                print(f"[LEWIS voice] Local speech failed: {fallback_error}")
                log_event("VOICE PLAYBACK FAILED")
                return False

        return not _speech_cancelled(cancel_event)


def stop_speaking():
    """Request speech to stop and stop the local engine if initialized."""
    _stop_requested.set()

    if _engine is not None:
        try:
            _engine.stop()
        except Exception:
            pass


def was_stop_requested():
    """Report whether the most recent speech operation was interrupted."""
    return _stop_requested.is_set()
