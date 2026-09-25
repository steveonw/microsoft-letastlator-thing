from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _completion_url(endpoint: str) -> str:
    value = endpoint.rstrip("/")
    if "/api/projects/" in value:
        raise ValueError(
            "POLICYTRACE_FOUNDRY_ENDPOINT must be a Microsoft Foundry Models "
            "resource endpoint, not a project endpoint, for Chat Completions"
        )
    if value.endswith("/openai/v1/chat/completions"):
        return value
    if value.endswith("/openai/v1"):
        return value + "/chat/completions"
    return value + "/openai/v1/chat/completions"


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
class FoundryConfig:
    endpoint: str
    model: str
    api_key: str | None = None
    bearer_token: str | None = None
    timeout_seconds: int = 90

    @classmethod
    def from_env(cls) -> "FoundryConfig":
        endpoint = os.environ.get("POLICYTRACE_FOUNDRY_ENDPOINT")
        model = os.environ.get("POLICYTRACE_FOUNDRY_MODEL")
        api_key = os.environ.get("POLICYTRACE_FOUNDRY_API_KEY")
        bearer_token = os.environ.get("POLICYTRACE_FOUNDRY_BEARER_TOKEN")

        if not endpoint:
            raise ValueError("POLICYTRACE_FOUNDRY_ENDPOINT is required")
        if not model:
            raise ValueError("POLICYTRACE_FOUNDRY_MODEL is required")
        if bool(api_key) == bool(bearer_token):
            raise ValueError(
                "set exactly one of POLICYTRACE_FOUNDRY_API_KEY or "
                "POLICYTRACE_FOUNDRY_BEARER_TOKEN"
            )

        return cls(
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            bearer_token=bearer_token,
        )


class FoundryChatClient:
    def __init__(self, config: FoundryConfig) -> None:
        self.config = config

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PolicyTrace/0.1",
        }
        if self.config.api_key:
            headers["api-key"] = self.config.api_key
        else:
            headers["Authorization"] = f"Bearer {self.config.bearer_token}"

        payload = {
            "model": self.config.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        request = Request(
            _completion_url(self.config.endpoint),
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
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
                f"Foundry request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise RuntimeError(f"Foundry request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError("Foundry request timed out") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Foundry response was not valid JSON") from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "Foundry response did not contain choices[0].message.content"
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Foundry returned empty model content")

        cleaned = _strip_json_fence(content)

        try:
            json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Foundry model did not return valid JSON") from exc

        return cleaned
