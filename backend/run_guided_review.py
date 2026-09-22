from __future__ import annotations

import argparse
from pathlib import Path

from foundry_client import FoundryChatClient, FoundryConfig
from guided_review import (
    begin_guided_review,
    clarify_current_step,
    edit_current_claim,
    flag_current_claim,
    next_guided_step,
    verify_current_claim,
)
from models import AnalysisRun
from openai_client import OpenAIChatClient, OpenAIConfig
from openrouter_client import OpenRouterChatClient, OpenRouterConfig


DEFAULT_INPUT = Path("data/claim-verifier/2024-20529.chunk6-analysis.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply one explicit human Guided Mode action to an AnalysisRun."
    )
    parser.add_argument(
        "action",
        choices=("begin", "clarify", "edit", "flag", "verify", "next"),
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON path. Defaults to overwriting --input.",
    )
    parser.add_argument("--step-id")
    parser.add_argument("--claim-id")
    parser.add_argument("--text")
    parser.add_argument(
        "--provider",
        choices=("foundry", "openai", "openrouter"),
        default="foundry",
        help="Provider used only by the verify action.",
    )
    return parser.parse_args()


def _require(value: str | None, flag: str) -> str:
    if value is None or not value.strip():
        raise SystemExit(f"{flag} is required for this action")
    return value.strip()


def _model_call(provider: str):
    if provider == "openai":
        return OpenAIChatClient(OpenAIConfig.from_env()).complete_json
    if provider == "openrouter":
        return OpenRouterChatClient(OpenRouterConfig.from_env()).complete_json
    return FoundryChatClient(FoundryConfig.from_env()).complete_json


def main() -> None:
    args = parse_args()
    analysis = AnalysisRun.model_validate_json(
        args.input.read_text(encoding="utf-8")
    )

    if args.action == "begin":
        updated = begin_guided_review(analysis, step_id=args.step_id)
    elif args.action == "clarify":
        updated = clarify_current_step(
            analysis,
            _require(args.text, "--text"),
        )
    elif args.action == "edit":
        updated = edit_current_claim(
            analysis,
            _require(args.claim_id, "--claim-id"),
            _require(args.text, "--text"),
        )
    elif args.action == "flag":
        updated = flag_current_claim(
            analysis,
            _require(args.claim_id, "--claim-id"),
            args.text,
        )
    elif args.action == "verify":
        updated = verify_current_claim(
            analysis,
            _require(args.claim_id, "--claim-id"),
            _model_call(args.provider),
        )
    else:
        updated = next_guided_step(analysis)

    output = args.output or args.input
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(updated.model_dump_json(indent=2), encoding="utf-8")

    current = updated.current_step_id or "complete"
    print(
        f"Guided Mode action completed\n"
        f"action={args.action}\n"
        f"current_step={current}\n"
        f"output={output}"
    )


if __name__ == "__main__":
    main()
