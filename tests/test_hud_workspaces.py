import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from memory import conversations
from memory import memory as personal_memory
from memory import project_memory


class HUDWorkspaceAPITests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.patches = [
            patch.object(
                conversations,
                "CONVERSATIONS_FILE",
                Path(self.temp_dir.name) / "conversations.json",
            ),
            patch.object(
                personal_memory,
                "MEMORY_FILE",
                Path(self.temp_dir.name) / "memory.json",
            ),
            patch.object(
                project_memory,
                "PROJECT_MEMORY_FILE",
                Path(self.temp_dir.name) / "project_memory.json",
            ),
        ]
        for storage_patch in self.patches:
            storage_patch.start()
            self.addCleanup(storage_patch.stop)

        self.conversation = conversations.create_conversation("Robot plans")
        conversations.add_message(
            self.conversation["id"],
            "user",
            "The robotic arm uses a silver motor.",
        )
        personal_memory.remember(
            "preferred color",
            "silver",
            category="preference",
        )
        project_memory.remember_project_fact(
            "ATLAS Robotics",
            "arm",
            "motor",
            "silver motor",
            category="decision",
            status="decision",
        )

        from ui import server

        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            server.LewisHandler,
        )
        self.thread = threading.Thread(
            target=self.httpd.serve_forever,
            daemon=True,
        )
        self.thread.start()
        self.addCleanup(self._stop_server)
        self.base_url = f"http://127.0.0.1:{self.httpd.server_port}"

    def _stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def _get(self, path):
        request = Request(self.base_url + path)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(
                    response.read().decode("utf-8")
                )
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def _post(self, path, payload):
        request = Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(
                    response.read().decode("utf-8")
                )
        except HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def test_conversation_search_returns_matching_saved_message(self):
        status, payload = self._get(
            "/api/conversations/search?q=silver%20motor"
        )

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["results"]), 1)
        result = payload["results"][0]
        self.assertEqual(result["conversation_id"], self.conversation["id"])
        self.assertEqual(result["title"], "Robot plans")
        self.assertIn("silver motor", result["message"]["content"])

    def test_memory_workspace_reads_and_filters_core_memory(self):
        status, payload = self._get("/api/memory?category=preference&q=silver")

        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["memories"][0]["value"], "silver")
        self.assertIn("preference", payload["categories"])
        self.assertEqual(
            personal_memory.get_all_memories()[0]["value"],
            "silver",
        )

    def test_project_workspace_lists_only_persisted_facts(self):
        status, payload = self._get("/api/projects?q=silver")

        self.assertEqual(status, 200)
        self.assertEqual(len(payload["projects"]), 1)
        project = payload["projects"][0]
        self.assertEqual(project["name"], "ATLAS Robotics")
        self.assertEqual(project["facts"][0]["value"], "silver motor")

    def test_project_workspace_includes_linked_conversations(self):
        conversations.update_conversation_metadata(
            self.conversation["id"],
            {"project": "ATLAS Robotics"},
        )

        status, payload = self._get("/api/projects?project=ATLAS%20Robotics")

        self.assertEqual(status, 200)
        project = payload["projects"][0]
        self.assertEqual(project["conversations"][0]["id"], self.conversation["id"])
        self.assertEqual(project["conversations"][0]["title"], "Robot plans")

    def test_conversation_metadata_preserves_messages_and_updates_organization(self):
        status, payload = self._post(
            "/api/conversations/metadata",
            {
                "id": self.conversation["id"],
                "updates": {
                    "pinned": True,
                    "folder": "Engineering",
                    "project": "ATLAS Robotics",
                },
            },
        )

        self.assertEqual(status, 200)
        updated = conversations.get_conversation(self.conversation["id"])
        self.assertEqual(updated["messages"][0]["content"], "The robotic arm uses a silver motor.")
        self.assertTrue(updated["pinned"])
        self.assertEqual(updated["folder"], "Engineering")
        self.assertEqual(updated["project"], "ATLAS Robotics")
        self.assertEqual(payload["conversation"]["id"], self.conversation["id"])

    def test_unlinking_active_conversation_clears_runtime_project_context(self):
        from ui import server

        lewis = SimpleNamespace(
            active_conversation_id=self.conversation["id"],
            active_project="ATLAS Robotics",
        )
        with (
            patch.object(server, "LEWIS_AVAILABLE", True),
            patch.object(server, "lewis", lewis),
        ):
            status, payload = self._post(
                "/api/conversations/metadata",
                {
                    "id": self.conversation["id"],
                    "updates": {"project": None},
                },
            )

        self.assertEqual(status, 200)
        self.assertIsNone(payload["conversation"]["project"])
        self.assertIsNone(lewis.active_project)

    def test_memory_workspace_updates_a_record_and_preserves_history(self):
        record = personal_memory.get_all_memories()[0]
        status, payload = self._post(
            "/api/memory/update",
            {
                "id": record["id"],
                "updates": {"value": "graphite", "status": "preference"},
            },
        )

        self.assertEqual(status, 200)
        stored = personal_memory.get_all_memories()[0]
        self.assertEqual(stored["value"], "graphite")
        self.assertEqual(stored["history"][-1]["value"], "silver")
        self.assertEqual(payload["memory"]["id"], record["id"])

    def test_memory_workspace_rejects_delete_or_unrecognized_fields(self):
        record = personal_memory.get_all_memories()[0]
        status, payload = self._post(
            "/api/memory/update",
            {"id": record["id"], "updates": {"delete": True}},
        )

        self.assertEqual(status, 400)
        self.assertIn("invalid", payload["error"].casefold())
        self.assertEqual(personal_memory.get_all_memories()[0]["value"], "silver")

    def test_ai_connection_test_uses_the_configured_provider_probe(self):
        from ui import server

        with (
            patch.object(server, "AI_AVAILABLE", True),
            patch.object(
                server.ai.model,
                "test_ai_connection",
                return_value={
                    "provider": "groq",
                    "model": "openai/gpt-oss-20b",
                },
            ) as test_connection,
        ):
            status, payload = self._post("/api/ai/test", {})

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["provider"], "groq")
        test_connection.assert_called_once_with()

    def test_workspace_search_rejects_oversized_query(self):
        status, payload = self._get(
            "/api/memory?q=" + ("x" * 201)
        )

        self.assertEqual(status, 400)
        self.assertIn("error", payload)


if __name__ == "__main__":
    unittest.main()
