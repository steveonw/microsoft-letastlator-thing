import unittest

from foundry_client import _completion_url, _strip_json_fence


class FoundryClientTests(unittest.TestCase):
    def test_completion_url_appends_openai_route(self) -> None:
        self.assertEqual(
            _completion_url(
                "https://example.services.ai.azure.com/api/projects/demo"
            ),
            (
                "https://example.services.ai.azure.com/api/projects/demo"
                "/openai/v1/chat/completions"
            ),
        )

    def test_completion_url_keeps_full_route(self) -> None:
        value = (
            "https://example.services.ai.azure.com/api/projects/demo"
            "/openai/v1/chat/completions"
        )
        self.assertEqual(_completion_url(value), value)

    def test_json_fence_is_removed(self) -> None:
        fenced = "```json\n{\"plain_language\": []}\n```"
        self.assertEqual(
            _strip_json_fence(fenced),
            "{\"plain_language\": []}",
        )


if __name__ == "__main__":
    unittest.main()
