import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memory import conversations


class VoiceStateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        patcher = patch.object(
            conversations,
            "CONVERSATIONS_FILE",
            Path(self.temp_dir.name) / "conversations.json",
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        conversations.create_conversation("Voice state test", "ATLAS")

        from ui import server

        self.server = server
        self.original_state = server.get_state_snapshot()
        self.addCleanup(lambda: server.update_state(**self.original_state))
        server.update_state(
            listening=False,
            speaking=False,
            processing=False,
            voice_session_stopping=False,
            last_error="",
        )

    def test_pipeline_state_tracks_activity_and_recovers_after_error(self):
        self.assertEqual(self.server.get_state_snapshot()["activity"], "READY")

        self.server.update_state(listening=True)
        self.assertEqual(self.server.get_state_snapshot()["activity"], "LISTENING")

        self.server.update_state(listening=False, processing=True)
        self.assertEqual(self.server.get_state_snapshot()["activity"], "PROCESSING")

        self.server.update_state(processing=False, speaking=True)
        self.assertEqual(self.server.get_state_snapshot()["activity"], "SPEAKING")

        self.server.update_state(
            speaking=False,
            last_error="Playback failed.",
        )
        state = self.server.get_state_snapshot()
        self.assertEqual(state["activity"], "READY")
        self.assertEqual(state["last_error"], "Playback failed.")

    def test_core_processing_is_reported_only_while_core_is_running(self):
        state_during_processing = {}
        self_test = self

        class FakeLewis:
            def process(self, message):
                state_during_processing.update(
                    {
                        "message": message,
                        **self_test.server.get_status(),
                    }
                )
                raise RuntimeError("Core request failed.")

        with (
            patch.object(self.server, "core_lock", threading.Lock()),
            patch.object(self.server, "LEWIS_AVAILABLE", True),
            patch.object(self.server, "lewis", FakeLewis()),
            patch.object(self.server, "AI_AVAILABLE", False),
            patch.object(self.server, "get_memory_count", return_value=None),
            patch.object(self.server, "get_system_data", return_value={}),
            self.assertRaisesRegex(RuntimeError, "Core request failed"),
        ):
            self.server.process_with_lewis("test request")

        self.assertEqual(state_during_processing["message"], "test request")
        self.assertEqual(state_during_processing["activity"], "PROCESSING")
        self.assertTrue(state_during_processing["processing"])
        state_after_failure = self.server.get_state_snapshot()
        self.assertEqual(state_after_failure["activity"], "READY")
        self.assertFalse(state_after_failure["processing"])

    def test_speaking_begins_only_after_playback_starts(self):
        def fake_speak(text, cancel_event=None, on_playback_start=None):
            self.assertEqual(
                self.server.get_state_snapshot()["activity"],
                "PROCESSING",
            )
            on_playback_start()
            self.assertEqual(
                self.server.get_state_snapshot()["activity"],
                "SPEAKING",
            )
            return True

        with patch.object(self.server, "speak", side_effect=fake_speak):
            self.server._speak_session_text("spoken text", threading.Event())

        self.assertEqual(self.server.get_state_snapshot()["activity"], "READY")


if __name__ == "__main__":
    unittest.main()
