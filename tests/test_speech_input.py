import json
import unittest
import threading
from unittest.mock import patch

from voice import speech_input


class FakeRecognizer:
    def AcceptWaveform(self, audio_data):
        return False

    def FinalResult(self):
        return '{"text":"recognized words"}'


class SegmentedRecognizer:
    def __init__(self):
        self.results = iter(("first segment", "second segment"))

    def AcceptWaveform(self, audio_data):
        return True

    def Result(self):
        return json.dumps({"text": next(self.results)})

    def FinalResult(self):
        return '{"text":"final segment"}'


class FakeInputStream:
    active = False

    def __init__(self, **options):
        pass

    def __enter__(self):
        FakeInputStream.active = True
        return self

    def __exit__(self, *args):
        FakeInputStream.active = False


class SpeechInputTests(unittest.TestCase):
    def test_capture_callback_and_timings_do_not_log_transcript(self):
        capture_state = []
        events = []

        def mark_capturing():
            capture_state.append(FakeInputStream.active)

        with (
            patch.object(speech_input, "_get_model", return_value=object()),
            patch.object(
                speech_input,
                "KaldiRecognizer",
                return_value=FakeRecognizer(),
            ),
            patch.object(speech_input.sd, "RawInputStream", FakeInputStream),
            patch.object(speech_input, "log_event", side_effect=events.append),
        ):
            transcript = speech_input.listen_once(
                timeout=0,
                on_capture_start=mark_capturing,
            )

        self.assertEqual(transcript, "recognized words")
        self.assertEqual(capture_state, [True])
        self.assertEqual(len(events), 2)
        self.assertIn("VOICE INPUT CAPTURE:", events[0])
        self.assertIn("VOICE TRANSCRIPTION:", events[1])
        self.assertNotIn("recognized words", " ".join(events))

    def test_push_to_talk_collects_segments_until_release(self):
        stop_event = threading.Event()

        class CaptureQueue:
            def __init__(self):
                self.audio = [b"one", b"two"]

            def get(self, timeout=None):
                audio_data = self.audio.pop(0)
                if not self.audio:
                    stop_event.set()
                return audio_data

        with (
            patch.object(speech_input, "_get_model", return_value=object()),
            patch.object(
                speech_input,
                "KaldiRecognizer",
                return_value=SegmentedRecognizer(),
            ),
            patch.object(speech_input.sd, "RawInputStream", FakeInputStream),
            patch.object(speech_input.queue, "Queue", return_value=CaptureQueue()),
            patch.object(speech_input, "log_event"),
        ):
            transcript = speech_input.listen_once(
                timeout=5,
                stop_event=stop_event,
                return_on_silence=False,
            )

        self.assertEqual(
            transcript,
            "first segment second segment final segment",
        )


if __name__ == "__main__":
    unittest.main()
