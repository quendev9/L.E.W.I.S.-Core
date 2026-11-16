import threading
import unittest
from unittest.mock import Mock, patch

from voice import speech_output


class FakeSpeechEngine:
    def __init__(self, completed=True, finish_on_iterate=True):
        self.callbacks = {}
        self.completed = completed
        self.finish_on_iterate = finish_on_iterate
        self.busy = False
        self.spoken_text = None

    def connect(self, event, callback):
        self.callbacks[event] = callback
        return event

    def disconnect(self, token):
        self.callbacks.pop(token, None)

    def say(self, text):
        self.spoken_text = text
        self.busy = True
        self.callbacks["started-utterance"]("test")

    def startLoop(self, use_driver_loop):
        pass

    def iterate(self):
        if self.finish_on_iterate:
            self.busy = False
            self.callbacks["finished-utterance"]("test", self.completed)
        else:
            self.busy = False

    def isBusy(self):
        return self.busy

    def endLoop(self):
        pass

    def stop(self):
        self.completed = False


class SpeechOutputTests(unittest.TestCase):
    def test_prepare_speech_removes_markdown_without_losing_content(self):
        markdown = (
            "# Release notes\n\n"
            "**Bold** and *italic* text, plus ~~removed~~ text.\n"
            "[Documentation](https://example.com/guide?q=42)\n"
            "- First item\n"
            "2. Second item with 12 steps.\n"
            "> Quoted text.\n"
            "`openai/gpt-oss-120b`\n"
            "```python\nprint('value 42')\n```"
        )

        spoken = speech_output._prepare_speech(markdown)

        self.assertIn("Release notes", spoken)
        self.assertIn("Bold and italic text", spoken)
        self.assertIn("removed text", spoken)
        self.assertIn(
            "Documentation (https://example.com/guide?q=42)",
            spoken,
        )
        self.assertIn("First item", spoken)
        self.assertIn("2. Second item with 12 steps.", spoken)
        self.assertIn("Quoted text.", spoken)
        self.assertIn("openai/gpt-oss-120b", spoken)
        self.assertIn("print('value 42')", spoken)
        self.assertNotIn("#", spoken)
        self.assertNotIn("**", spoken)
        self.assertNotIn("```", spoken)
        self.assertNotIn("`", spoken)

    def test_local_speech_reports_start_and_completed_utterance(self):
        engine = FakeSpeechEngine()
        playback_started = Mock()

        with (
            patch.object(speech_output, "_get_engine", return_value=engine),
            patch.object(speech_output, "log_event"),
        ):
            completed = speech_output._speak_local(
                "A bold response.",
                on_playback_start=playback_started,
            )

        self.assertTrue(completed)
        self.assertEqual(engine.spoken_text, "A bold response.")
        playback_started.assert_called_once_with()
        self.assertEqual(engine.callbacks, {})

    def test_speak_uses_local_voice_and_propagates_failure(self):
        with (
            patch.object(speech_output, "_speak_local", return_value=True) as speak_local,
        ):
            self.assertTrue(speech_output.speak("A bold response."))

        speak_local.assert_called_once()

    def test_speak_does_not_report_success_when_local_engine_fails(self):
        with (
            patch.object(
                speech_output,
                "_speak_local",
                side_effect=RuntimeError("No Windows speech voice is available."),
            ),
            patch.object(speech_output, "log_event") as log_event,
            patch("builtins.print") as print_error,
        ):
            self.assertFalse(speech_output.speak("A response."))

        self.assertIn("No Windows speech voice is available.", str(print_error.call_args))
        self.assertIn("No Windows speech voice is available.", str(log_event.call_args))

    def test_local_engine_uses_one_thread_across_callers(self):
        worker_threads = []
        results = []

        def fake_speak(text, cancel_event=None, on_playback_start=None):
            worker_threads.append(threading.current_thread().ident)
            return True

        def call_speak():
            results.append(speech_output.speak("A response."))

        with patch.object(speech_output, "_speak_local", side_effect=fake_speak):
            callers = [
                threading.Thread(target=call_speak),
                threading.Thread(target=call_speak),
            ]
            for caller in callers:
                caller.start()
            for caller in callers:
                caller.join(timeout=2)

        self.assertEqual(results, [True, True])
        self.assertEqual(len(set(worker_threads)), 1)

    def test_local_speech_reports_interruption_as_incomplete(self):
        cancel_event = threading.Event()
        engine = FakeSpeechEngine(completed=False)
        engine.iterate = lambda: (
            cancel_event.set(),
            setattr(engine, "busy", False),
            engine.callbacks["finished-utterance"]("test", False),
        )

        with (
            patch.object(speech_output, "_get_engine", return_value=engine),
            patch.object(speech_output, "log_event"),
        ):
            completed = speech_output._speak_local(
                "A response.",
                cancel_event=cancel_event,
            )

        self.assertFalse(completed)

    def test_local_speech_rejects_missing_completion_event(self):
        engine = FakeSpeechEngine(finish_on_iterate=False)

        with (
            patch.object(speech_output, "_get_engine", return_value=engine),
            patch.object(speech_output, "log_event"),
        ):
            with self.assertRaisesRegex(RuntimeError, "without completing"):
                speech_output._speak_local("A response.")


if __name__ == "__main__":
    unittest.main()
