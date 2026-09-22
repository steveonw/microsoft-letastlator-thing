from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENROUTER_MODEL = "openrouter/free"


def _completion_url(base_url: str) -> str:
    value = base_url.rstrip("/")
    if value.endswith("/chat/completions"):
        return value
    if value.endswith("/api/v1"):
        return value + "/chat/completions"
    if value.endswith("/v1"):
        return value + "/chat/completions"
    return value + "/api/v1/chat/completions"


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


def _extract_json(value: str) -> str:
    """
    Return one valid JSON value from model output.

    Some routed models prepend prose or reasoning tags even when JSON mode was
    requested. First accept clean JSON, then fall back to decoding from the first
    JSON object/array marker. The returned string is normalized valid JSON.
    """
    text = _strip_json_fence(value)

    try:
        parsed = json.loads(text)
        return json.dumps(parsed, ensure_ascii=False)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    candidates = [
        index
        for marker in ("{", "[")
        if (index := text.find(marker)) >= 0
    ]

    for start in sorted(candidates):
        try:
            parsed, _ = decoder.raw_decode(text[start:])
            return json.dumps(parsed, ensure_ascii=False)
        except json.JSONDecodeError:
            continue

    preview = text[:180].replace("\n", "\\n")
    raise ValueError(
        "OpenRouter model did not return extractable JSON. "
        f"Response began with: {preview!r}"
    )


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str
    model: str = DEFAULT_OPENROUTER_MODEL
    base_url: str = DEFAULT_OPENROUTER_BASE_URL
    timeout_seconds: int = 90

    @classmethod
    def from_env(cls) -> "OpenRouterConfig":
        api_key = os.environ.get("OPENROUTER_API_KEY")
        model = os.environ.get(
            "POLICYTRACE_OPENROUTER_MODEL",
            DEFAULT_OPENROUTER_MODEL,
        )
        base_url = os.environ.get(
            "POLICYTRACE_OPENROUTER_BASE_URL",
            DEFAULT_OPENROUTER_BASE_URL,
        )

        if not api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required for the openrouter provider"
            )

        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )


class OpenRouterChatClient:
    def __init__(self, config: OpenRouterConfig) -> None:
        self.config = config

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.config.model,
            "response_format": {"type": "json_object"},
            "provider": {"require_parameters": True},
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
                "X-Title": "PolicyTrace",
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
                f"OpenRouter request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(
                f"OpenRouter request failed: {exc.reason}"
            ) from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "OpenRouter response did not contain "
                "choices[0].message.content"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("OpenRouter returned empty model content")

        try:
            return _extract_json(content)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc
