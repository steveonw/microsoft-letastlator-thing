from __future__ import annotations

import json
import os

from model_json import extract_json_value, strip_json_fence
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
    return strip_json_fence(value)


def _extract_json(value: str) -> str:
    try:
        return extract_json_value(value)
    except ValueError as exc:
        message = str(exc).replace(
            "model did not return extractable JSON.",
            "OpenRouter model did not return extractable JSON.",
        )
        raise ValueError(message) from exc


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


def _is_parameter_routing_error(code: int, detail: str) -> bool:
    if code not in {400, 404}:
        return False

    lowered = detail.lower()
    return (
        "filter by parameters" in lowered
        or "no endpoints found that can handle the requested parameters" in lowered
        or "\"failed_routing_step\":\"Filter by Parameters\"".lower() in lowered
    )


class OpenRouterChatClient:
    def __init__(self, config: OpenRouterConfig) -> None:
        self.config = config

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
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
                return json.loads(response.read().decode("utf-8"))
        except HTTPError:
            raise
        except URLError as exc:
            raise RuntimeError(
                f"OpenRouter request failed: {exc.reason}"
            ) from exc

    def complete_json(self, system_prompt: str, user_prompt: str) -> str:
        base_payload: dict[str, object] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

        attempts = [
            {
                **base_payload,
                "response_format": {"type": "json_object"},
                "provider": {"require_parameters": True},
            },
            {
                **base_payload,
                "response_format": {"type": "json_object"},
            },
            base_payload,
        ]

        body: dict[str, object] | None = None
        last_error: HTTPError | None = None
        last_detail = ""

        for attempt_index, payload in enumerate(attempts):
            try:
                body = self._post(payload)
                break
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = exc
                last_detail = detail

                if not _is_parameter_routing_error(exc.code, detail):
                    raise RuntimeError(
                        f"OpenRouter request failed with HTTP {exc.code}: {detail}"
                    ) from exc

                if attempt_index == len(attempts) - 1:
                    break

        if body is None:
            assert last_error is not None
            raise RuntimeError(
                "OpenRouter could not find a compatible endpoint after retrying "
                "with relaxed parameter requirements. "
                f"Last HTTP {last_error.code}: {last_detail}"
            ) from last_error

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
