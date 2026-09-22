from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


def _completion_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    if value.endswith("/v1"):
        return value + "/chat/completions"
    return value + "/v1/chat/completions"


def _strip_json_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str
    model: str
    base_url: str = DEFAULT_OPENAI_BASE_URL
    timeout_seconds: int = 90

    @classmethod
    def from_env(cls) -> "OpenAIConfig":
        api_key = os.environ.get("OPENAI_API_KEY")
        model = os.environ.get("POLICYTRACE_OPENAI_MODEL")
        base_url = os.environ.get(
            "POLICYTRACE_OPENAI_BASE_URL",
            DEFAULT_OPENAI_BASE_URL,
        )

        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for the openai provider")
        if not model:
            raise ValueError(
                "POLICYTRACE_OPENAI_MODEL is required for the openai provider"
            )

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )


class OpenAIChatClient:
    def __init__(self, config: OpenAIConfig) -> None:
        self.config = config

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.config.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        request = Request(
            _completion_url(self.config.base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "PolicyTrace/0.1",
            },
            method="POST",
        )

        try:
            with urlopen(
                request,
                timeout=self.config.timeout_seconds,
            ) as response:
                body = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"OpenAI request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"OpenAI request failed: {exc.reason}") from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "OpenAI response did not contain choices[0].message.content"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenAI returned empty model content")

        cleaned = _strip_json_fence(content)

        try:
            json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError("OpenAI model did not return valid JSON") from exc

        return cleaned
