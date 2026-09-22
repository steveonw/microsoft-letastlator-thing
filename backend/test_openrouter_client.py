import json
import os
import unittest
from unittest.mock import patch

from openrouter_client import (
    DEFAULT_OPENROUTER_BASE_URL,
    DEFAULT_OPENROUTER_MODEL,
    OpenRouterConfig,
    _completion_url,
    _extract_json,
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


if __name__ == "__main__":
    unittest.main()
