import io
import json
import os
import unittest
from urllib.error import HTTPError
from unittest.mock import patch

from ai import model
from core.identity import LEWIS_IDENTITY


def _success_response(content):
    return io.BytesIO(json.dumps({
        "choices": [{"message": {"content": content}}],
    }).encode("utf-8"))


class OpenRouterProviderTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.selection = patch.object(model, "_selected_ai_model", None)
        self.selection.start()
        self.addCleanup(self.selection.stop)

    def test_request_uses_free_router_and_parses_response(self):
        os.environ["OPENROUTER_API_KEY"] = "local-test-openrouter-key"

        with patch.object(
            model,
            "urlopen",
            return_value=_success_response("OpenRouter reply"),
        ) as request:
            self.assertEqual(
                model.ask_openrouter("hello", conversation_id="conversation"),
                "OpenRouter reply",
            )

        sent_request = request.call_args.args[0]
        self.assertEqual(sent_request.full_url, model.OPENROUTER_API_URL)
        self.assertEqual(sent_request.get_method(), "POST")
        self.assertEqual(
            sent_request.get_header("Authorization"),
            "Bearer local-test-openrouter-key",
        )
        self.assertEqual(
            sent_request.get_header("Content-type"),
            "application/json",
        )
        self.assertEqual(
            json.loads(sent_request.data),
            {
                "model": "openrouter/free",
                "messages": [
                    {"role": "system", "content": LEWIS_IDENTITY},
                    {"role": "user", "content": "hello"},
                ],
            },
        )
        request.assert_called_once_with(sent_request, timeout=60)

    def test_selected_model_is_sent_and_selection_switches_backend(self):
        os.environ["GEMINI_MODEL"] = "gemini-3.6-flash"
        os.environ["GEMINI_API_KEY"] = "test-gemini-key"
        os.environ["OPENROUTER_API_KEY"] = "test-openrouter-key"
        os.environ["OPENROUTER_MODEL"] = "openrouter/free"

        model.set_ai_selection("gemini", "gemini-3.6-flash")
        with patch.object(
            model,
            "ask_gemini",
            return_value="Gemini",
        ) as ask_gemini:
            self.assertEqual(
                model.ask_ai("first message", conversation_id="conversation"),
                "Gemini",
            )
        ask_gemini.assert_called_once_with(
            "first message",
            conversation_id="conversation",
        )

        model.set_ai_selection("openrouter", "openrouter/free")

        with patch.object(
            model,
            "urlopen",
            return_value=_success_response("OpenRouter"),
        ) as request:
            self.assertEqual(
                model.ask_ai("typed message", conversation_id="conversation"),
                "OpenRouter",
            )

        sent_request = request.call_args.args[0]
        self.assertEqual(
            json.loads(sent_request.data)["model"],
            "openrouter/free",
        )
        self.assertEqual(model.get_ai_provider(), "openrouter")

    def test_openrouter_is_available_and_reports_key_configuration(self):
        os.environ["AI_PROVIDER"] = "openrouter"
        os.environ["OPENROUTER_API_KEY"] = "test-openrouter-key"
        os.environ["OPENROUTER_MODEL"] = "configured-openrouter-model"

        self.assertEqual(
            model.get_ai_provider_info(),
            {
                "provider": "OpenRouter",
                "model": "configured-openrouter-model",
                "configured": True,
                "selection": {
                    "provider": "openrouter",
                    "model": "configured-openrouter-model",
                },
            },
        )
        self.assertIn(
            {
                "provider": "openrouter",
                "name": "OpenRouter",
                "model": "configured-openrouter-model",
            },
            model.get_available_ai_models(),
        )

    def test_missing_key_fails_without_sending_request(self):
        with patch.object(model, "urlopen") as request:
            with self.assertRaisesRegex(
                RuntimeError,
                "OPENROUTER_API_KEY",
            ):
                model.ask_openrouter("hello")

        request.assert_not_called()

    def test_connection_test_sends_fixed_probe_to_selected_provider(self):
        os.environ["OPENROUTER_API_KEY"] = "test-openrouter-key"
        model.set_ai_selection("openrouter", "openrouter/free")

        with patch.object(model, "ask_openrouter", return_value="OK") as probe:
            result = model.test_ai_connection()

        self.assertEqual(
            result,
            {"provider": "openrouter", "model": "openrouter/free"},
        )
        probe.assert_called_once_with(
            "LEWIS connection check. Reply with the word OK.",
            model_name="openrouter/free",
        )

    def test_invalid_key_http_error_is_provider_specific(self):
        api_key = "invalid-openrouter-key"
        os.environ["OPENROUTER_API_KEY"] = api_key
        unauthorized = HTTPError(
            model.OPENROUTER_API_URL,
            401,
            "Unauthorized",
            {},
            io.BytesIO(json.dumps({
                "error": {
                    "message": f"Invalid API key {api_key}",
                    "type": "authentication_error",
                },
            }).encode("utf-8")),
        )

        with patch.object(model, "urlopen", side_effect=unauthorized):
            with self.assertRaises(model.OpenRouterAPIError) as raised:
                model.ask_openrouter("hello")

        self.assertEqual(raised.exception.status_code, 401)
        self.assertIn("Invalid API key [REDACTED]", str(raised.exception))
        self.assertNotIn(api_key, str(raised.exception))
        self.assertFalse(model.is_transient_api_error(raised.exception))

    def test_http_error_body_is_preserved_and_key_is_redacted(self):
        api_key = "test-openrouter-secret"
        os.environ["OPENROUTER_API_KEY"] = api_key
        forbidden = HTTPError(
            model.OPENROUTER_API_URL,
            403,
            "Forbidden",
            {},
            io.BytesIO(
                f"Request denied for {api_key}".encode("utf-8")
            ),
        )

        with patch.object(model, "urlopen", side_effect=forbidden):
            with self.assertRaises(model.OpenRouterAPIError) as raised:
                model.ask_openrouter("hello")

        self.assertEqual(raised.exception.status_code, 403)
        self.assertIn(
            "Request denied for [REDACTED]",
            str(raised.exception),
        )
        self.assertNotIn(api_key, str(raised.exception))

    def test_api_server_error_is_transient_and_http_error_body_is_reported(self):
        error = HTTPError(
            model.OPENROUTER_API_URL,
            503,
            "Service Unavailable",
            {},
            io.BytesIO(b'{"error":{"message":"Upstream unavailable"}}'),
        )
        os.environ["OPENROUTER_API_KEY"] = "test-openrouter-key"

        with patch.object(model, "urlopen", side_effect=error):
            with self.assertRaises(model.OpenRouterAPIError) as raised:
                model.ask_openrouter("hello")

        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("Upstream unavailable", str(raised.exception))
        self.assertTrue(model.is_transient_api_error(raised.exception))

    def test_unsupported_response_content_is_reported(self):
        os.environ["OPENROUTER_API_KEY"] = "test-openrouter-key"
        response = io.BytesIO(json.dumps({
            "choices": [{"message": {"content": ["not", "text"]}}],
        }).encode("utf-8"))

        with patch.object(model, "urlopen", return_value=response):
            with self.assertRaisesRegex(
                RuntimeError,
                "unsupported format",
            ):
                model.ask_openrouter("hello")


if __name__ == "__main__":
    unittest.main()
