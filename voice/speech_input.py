
import json
import queue
import time
from pathlib import Path
from types import SimpleNamespace

try:
    import sounddevice as sd
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    class _MissingInputStream:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("sounddevice is unavailable")

    sd = SimpleNamespace(RawInputStream=_MissingInputStream)

try:
    from vosk import Model, KaldiRecognizer
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    class _MissingModel:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("vosk model is unavailable")

    class _MissingKaldiRecognizer:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("vosk is unavailable")

        def AcceptWaveform(self, *args, **kwargs):
            raise RuntimeError("vosk is unavailable")

        def FinalResult(self):
            raise RuntimeError("vosk is unavailable")

    Model = _MissingModel
    KaldiRecognizer = _MissingKaldiRecognizer

from core.event_logger import log_event


MODEL_PATH = (
    Path(__file__).resolve().parent.parent
    / "models"
    / "vosk-model-small-en-us-0.15"
)

SAMPLE_RATE = 16000
BLOCK_SIZE = 4000
LISTEN_TIMEOUT = 15


_model = None


def _get_model():
    global _model

    if _model is None:
        if not MODEL_PATH.is_dir():
            raise FileNotFoundError(
                f"Vosk model folder not found: {MODEL_PATH}"
            )

        _model = Model(str(MODEL_PATH))

    return _model


def listen_once(
    timeout=LISTEN_TIMEOUT,
    stop_event=None,
    interrupt_event=None,
    on_capture_start=None,
    return_on_silence=True,
):
    """Listen for speech, checking session events between audio queue waits.

    With return_on_silence=False, accepted segments are collected until stop
    or timeout for push-to-talk capture. Device startup and model loading are
    blocking; stop is observed at most one queue wait after capture starts.
    """
    audio_queue = queue.Queue()
    recognizer = KaldiRecognizer(_get_model(), SAMPLE_RATE)

    def audio_callback(indata, frames, time_info, status):
        if status:
            print(f"\nMicrophone status: {status}")

        audio_queue.put(bytes(indata))

    print("Listening... Speak now.")

    deadline = time.monotonic() + timeout
    recognized_segments = []

    if stop_event and stop_event.is_set():
        return ""

    capture_started = time.perf_counter()
    transcription_seconds = 0.0
    try:
        with sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            dtype="int16",
            channels=1,
            callback=audio_callback,
        ):
            if on_capture_start:
                on_capture_start()

            while (
                time.monotonic() < deadline
                and not (stop_event and stop_event.is_set())
                and not (interrupt_event and interrupt_event.is_set())
            ):
                try:
                    remaining = max(0, deadline - time.monotonic())
                    audio_data = audio_queue.get(timeout=min(0.25, remaining))
                except queue.Empty:
                    continue

                recognition_started = time.perf_counter()
                accepted = recognizer.AcceptWaveform(audio_data)
                transcription_seconds += (
                    time.perf_counter() - recognition_started
                )
                if accepted:
                    recognition_started = time.perf_counter()
                    result = json.loads(recognizer.Result())
                    transcription_seconds += (
                        time.perf_counter() - recognition_started
                    )
                    text = result.get("text", "").strip()

                    if text:
                        if return_on_silence:
                            return text
                        recognized_segments.append(text)

            recognition_started = time.perf_counter()
            result = json.loads(recognizer.FinalResult())
            transcription_seconds += (
                time.perf_counter() - recognition_started
            )
            final_segment = result.get("text", "").strip()
            if final_segment:
                recognized_segments.append(final_segment)
            return " ".join(recognized_segments)
    finally:
        total_seconds = time.perf_counter() - capture_started
        log_event(
            "VOICE INPUT CAPTURE: "
            f"{max(0.0, total_seconds - transcription_seconds) * 1000:.0f} ms"
        )
        log_event(
            "VOICE TRANSCRIPTION: "
            f"{transcription_seconds * 1000:.0f} ms"
        )
