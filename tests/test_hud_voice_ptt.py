import threading
import unittest
from unittest.mock import ANY, patch

from ui import server


class FakeThread:
    def __init__(self, target, args=(), **kwargs):
        self.target = target
        self.args = args

    def start(self):
        return None


class HUDPushToTalkTests(unittest.TestCase):
    def setUp(self):
        self.previous_lock = server.voice_lock
        self.previous_state = server.get_state_snapshot()
        self.previous_stop_requested = server.push_to_talk_stop_event.is_set()
        server.voice_lock = threading.Lock()
        server.push_to_talk_stop_event.clear()
        server.update_state(
            push_to_talk_active=False,
            push_to_talk_processing=False,
            voice_session_active=False,
            voice_session_stopping=False,
            listening=False,
            speaking=False,
            voice_output_pending=False,
            processing=False,
            voice_event_id=0,
            voice_response_id=0,
            last_transcript="",
            last_response="",
            last_error="",
        )

    def tearDown(self):
        if server.voice_lock.locked():
            server.voice_lock.release()
        server.voice_lock = self.previous_lock
        server.server_state.update(self.previous_state)
        if self.previous_stop_requested:
            server.push_to_talk_stop_event.set()
        else:
            server.push_to_talk_stop_event.clear()

    def test_push_to_talk_start_and_release_use_real_server_state(self):
        with (
            patch.object(server, "VOICE_INPUT_AVAILABLE", True),
            patch.object(server, "LEWIS_AVAILABLE", True),
            patch.object(server, "lewis", object()),
            patch.object(server.threading, "Thread", FakeThread),
        ):
            started, start_message = server.start_push_to_talk()

            self.assertTrue(started)
            self.assertEqual(start_message, "Push-to-talk capture started.")
            self.assertTrue(server.get_state_snapshot()["push_to_talk_active"])

            stopped = server.stop_push_to_talk()

        self.assertTrue(stopped)
        self.assertTrue(server.push_to_talk_stop_event.is_set())
        self.assertFalse(server.get_state_snapshot()["push_to_talk_active"])
        self.assertTrue(
            server.get_state_snapshot()["push_to_talk_processing"]
        )

    def test_released_capture_processes_final_transcript(self):
        server.voice_lock.acquire()
        stop_event = threading.Event()
        stop_event.set()

        with (
            patch.object(server, "listen_once", return_value="open the project") as listen,
            patch.object(server, "process_with_lewis", return_value="Project opened"),
            patch.object(server, "VOICE_OUTPUT_AVAILABLE", False),
            patch.object(server, "log_event"),
        ):
            server.push_to_talk_worker(stop_event)

        listen.assert_called_once_with(
            stop_event=stop_event,
            on_capture_start=ANY,
            return_on_silence=False,
        )
        state = server.get_state_snapshot()
        self.assertEqual(state["last_transcript"], "open the project")
        self.assertEqual(state["last_response"], "Project opened")
        self.assertEqual(state["voice_event_id"], 1)
        self.assertEqual(state["voice_response_id"], 1)
        self.assertFalse(state["push_to_talk_active"])
        self.assertFalse(state["push_to_talk_processing"])

    def test_empty_capture_clears_processing_and_reports_it(self):
        server.voice_lock.acquire()
        stop_event = threading.Event()
        stop_event.set()

        with (
            patch.object(server, "listen_once", return_value=""),
            patch.object(server, "log_event"),
        ):
            server.push_to_talk_worker(stop_event)

        state = server.get_state_snapshot()
        self.assertEqual(state["last_error"], "No speech was captured.")
        self.assertFalse(state["push_to_talk_active"])
        self.assertFalse(state["push_to_talk_processing"])


if __name__ == "__main__":
    unittest.main()
