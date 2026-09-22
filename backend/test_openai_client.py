import os
import unittest
from unittest.mock import patch

from openai_client import (
    DEFAULT_OPENAI_BASE_URL,
    OpenAIConfig,
    _completion_url,
    _strip_json_fence,
)


class OpenAIClientTests(unittest.TestCase):
    def test_completion_url_from_default_base(self) -> None:
        self.assertEqual(
            _completion_url(DEFAULT_OPENAI_BASE_URL),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_completion_url_keeps_full_route(self) -> None:
        value = "https://api.openai.com/v1/chat/completions"
        self.assertEqual(_completion_url(value), value)

    def test_json_fence_is_removed(self) -> None:
        fenced = "```json\n{\"plain_language\": []}\n```"
        self.assertEqual(
            _strip_json_fence(fenced),
            "{\"plain_language\": []}",
        )

    def test_env_config_requires_key_and_model(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                OpenAIConfig.from_env()

        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-only-key"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                OpenAIConfig.from_env()

    def test_env_config_loads_without_storing_key_in_repo(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-only-key",
                "POLICYTRACE_OPENAI_MODEL": "test-model",
            },
            clear=True,
        ):
            config = OpenAIConfig.from_env()

        self.assertEqual(config.api_key, "test-only-key")
        self.assertEqual(config.model, "test-model")
        self.assertEqual(config.base_url, DEFAULT_OPENAI_BASE_URL)


if __name__ == "__main__":
    unittest.main()
