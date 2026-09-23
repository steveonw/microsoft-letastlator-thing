from __future__ import annotations

import json


def strip_json_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def extract_json_value(value: str) -> str:
    """
    Return one valid JSON value from model output.

    Accept clean JSON first, then recover a JSON object/array that follows
    harmless model chatter such as "Sure! Here is the JSON:". The returned
    string is normalized valid JSON.
    """
    text = strip_json_fence(value)

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
        "model did not return extractable JSON. "
        f"Response began with: {preview!r}"
    )
