import unittest
from unittest.mock import patch

from foundry_client import (
    FoundryChatClient,
    FoundryConfig,
    _completion_url,
    _strip_json_fence,
)


class FoundryClientTests(unittest.TestCase):
    def test_completion_url_appends_openai_route(self) -> None:
        self.assertEqual(
            _completion_url("https://example.services.ai.azure.com"),
            (
                "https://example.services.ai.azure.com"
                "/openai/v1/chat/completions"
            ),
        )

    def test_project_endpoint_is_rejected_for_chat_completions(self) -> None:
        with self.assertRaises(ValueError):
            _completion_url(
                "https://example.services.ai.azure.com/api/projects/demo"
            )

    def test_completion_url_keeps_full_route(self) -> None:
        value = (
            "https://example.services.ai.azure.com"
            "/openai/v1/chat/completions"
        )
        self.assertEqual(_completion_url(value), value)

    def test_json_fence_is_removed(self) -> None:
        fenced = "```json\n{\"plain_language\": []}\n```"
        self.assertEqual(
            _strip_json_fence(fenced),
            "{\"plain_language\": []}",
        )

    def test_timeout_becomes_controlled_runtime_error(self) -> None:
        client = FoundryChatClient(
            FoundryConfig(
                endpoint="https://example.services.ai.azure.com",
                model="demo",
                api_key="secret",
            )
        )
        with patch("foundry_client.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                client.complete_json("system", "user")

    def test_malformed_outer_response_becomes_controlled_runtime_error(self) -> None:
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"not-json"

        client = FoundryChatClient(
            FoundryConfig(
                endpoint="https://example.services.ai.azure.com",
                model="demo",
                api_key="secret",
            )
        )
        with patch("foundry_client.urlopen", return_value=FakeResponse()):
            with self.assertRaisesRegex(RuntimeError, "not valid JSON"):
                client.complete_json("system", "user")


if __name__ == "__main__":
    unittest.main()
