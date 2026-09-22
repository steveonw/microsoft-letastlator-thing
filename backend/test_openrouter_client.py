import json
import os
import unittest
from io import BytesIO
from urllib.error import HTTPError
from unittest.mock import patch

from openrouter_client import (
    DEFAULT_OPENROUTER_BASE_URL,
    DEFAULT_OPENROUTER_MODEL,
    OpenRouterChatClient,
    OpenRouterConfig,
    _completion_url,
    _extract_json,
    _is_parameter_routing_error,
    _strip_json_fence,
)


class OpenRouterClientTests(unittest.TestCase):
    def test_completion_url_from_default_base(self) -> None:
        self.assertEqual(
            _completion_url(DEFAULT_OPENROUTER_BASE_URL),
            "https://openrouter.ai/api/v1/chat/completions",
        )

    def test_completion_url_keeps_full_route(self) -> None:
        value = "https://openrouter.ai/api/v1/chat/completions"
        self.assertEqual(_completion_url(value), value)

    def test_default_model_uses_free_router(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "test-only-key"},
            clear=True,
        ):
            config = OpenRouterConfig.from_env()

        self.assertEqual(config.model, DEFAULT_OPENROUTER_MODEL)
        self.assertEqual(config.model, "openrouter/free")

    def test_env_can_override_free_router_with_specific_model(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test-only-key",
                "POLICYTRACE_OPENROUTER_MODEL": "vendor/model:free",
            },
            clear=True,
        ):
            config = OpenRouterConfig.from_env()

        self.assertEqual(config.model, "vendor/model:free")

    def test_env_requires_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                OpenRouterConfig.from_env()

    def test_json_fence_is_removed(self) -> None:
        fenced = "```json\n{\"plain_language\": []}\n```"
        self.assertEqual(
            _strip_json_fence(fenced),
            "{\"plain_language\": []}",
        )

    def test_extract_json_accepts_prose_prefix(self) -> None:
        result = _extract_json(
            "Here is the JSON you requested:\n"
            "{\"plain_language\": [], \"major_provisions\": []}"
        )
        self.assertEqual(
            json.loads(result),
            {"plain_language": [], "major_provisions": []},
        )

    def test_extract_json_accepts_reasoning_tag_prefix(self) -> None:
        result = _extract_json(
            "<think>Need to answer in JSON.</think>\n"
            "{\"plain_language\": []}"
        )
        self.assertEqual(
            json.loads(result),
            {"plain_language": []},
        )

    def test_extract_json_rejects_non_json_with_preview(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "Response began with",
        ):
            _extract_json("I could not produce the requested structure.")

    def test_parameter_routing_error_detection(self) -> None:
        detail = (
            '{"error":{"message":"No endpoints found that can handle the requested '
            'parameters.","metadata":{"failed_routing_step":"Filter by Parameters"}}}'
        )
        self.assertTrue(_is_parameter_routing_error(404, detail))
        self.assertFalse(_is_parameter_routing_error(401, detail))

    def test_client_relaxes_parameters_after_filter_by_parameters_404(self) -> None:
        detail = (
            b'{"error":{"message":"No endpoints found that can handle the requested '
            b'parameters.","metadata":{"failed_routing_step":"Filter by Parameters"}}}'
        )
        first_error = HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=BytesIO(detail),
        )

        successful_body = {
            "choices": [
                {
                    "message": {
                        "content": '{"plain_language":[],"major_provisions":[],'
                        '"stakeholders":[],"affected_programs":[]}'
                    }
                }
            ]
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(successful_body).encode("utf-8")

        client = OpenRouterChatClient(
            OpenRouterConfig(
                api_key="test-only-key",
                model="test-model",
            )
        )

        with patch(
            "openrouter_client.urlopen",
            side_effect=[first_error, FakeResponse()],
        ) as mocked_urlopen:
            result = client.complete_json("system", "user")

        self.assertEqual(
            json.loads(result),
            {
                "plain_language": [],
                "major_provisions": [],
                "stakeholders": [],
                "affected_programs": [],
            },
        )
        self.assertEqual(mocked_urlopen.call_count, 2)

        first_request = mocked_urlopen.call_args_list[0].args[0]
        second_request = mocked_urlopen.call_args_list[1].args[0]
        first_payload = json.loads(first_request.data.decode("utf-8"))
        second_payload = json.loads(second_request.data.decode("utf-8"))

        self.assertEqual(
            first_payload["provider"],
            {"require_parameters": True},
        )
        self.assertNotIn("provider", second_payload)
        self.assertIn("response_format", second_payload)

    def test_client_does_not_retry_auth_error(self) -> None:
        auth_error = HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=BytesIO(b'{"error":{"message":"bad key"}}'),
        )
        client = OpenRouterChatClient(
            OpenRouterConfig(
                api_key="test-only-key",
                model="test-model",
            )
        )

        with patch(
            "openrouter_client.urlopen",
            side_effect=auth_error,
        ) as mocked_urlopen:
            with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
                client.complete_json("system", "user")

        self.assertEqual(mocked_urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
