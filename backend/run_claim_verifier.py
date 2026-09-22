from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from claim_verifier import run_claim_verifier
from foundry_client import FoundryChatClient, FoundryConfig
from models import AnalysisRun
from openai_client import OpenAIChatClient, OpenAIConfig
from openrouter_client import OpenRouterChatClient, OpenRouterConfig


DEFAULT_INPUT = Path("data/policy-interpreter/2024-20529.chunk4-analysis.json")
DEFAULT_OUTPUT = Path("data/claim-verifier/2024-20529.chunk6-analysis.json")
DEFAULT_RESPONSE_FIXTURE = Path(
    "data/claim-verifier/2024-20529.verifier-responses.json"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the PolicyTrace Claim Verifier over an AnalysisRun."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="Existing PolicyTrace AnalysisRun JSON to verify.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use checked-in verifier responses; no model network call is made.",
    )
    parser.add_argument(
        "--provider",
        choices=("foundry", "openai", "openrouter"),
        default="foundry",
    )
    parser.add_argument(
        "--response-fixture",
        type=Path,
        default=DEFAULT_RESPONSE_FIXTURE,
    )
    return parser.parse_args()


def _offline_model_call(fixture_path: Path):
    responses = json.loads(fixture_path.read_text(encoding="utf-8"))

    def complete_json(system_prompt: str, user_prompt: str) -> str:
        del system_prompt
        match = re.search(r"^Claim ID: (.+)$", user_prompt, flags=re.MULTILINE)
        if match is None:
            raise ValueError("offline verifier prompt did not contain Claim ID")
        claim_id = match.group(1).strip()
        if claim_id not in responses:
            raise ValueError(
                f"offline verifier fixture has no response for {claim_id}"
            )
        return json.dumps(responses[claim_id])

    return complete_json


def main() -> None:
    args = parse_args()

    analysis = AnalysisRun.model_validate_json(
        args.input.read_text(encoding="utf-8")
    )

    if args.offline:
        model_call = _offline_model_call(args.response_fixture)
        source_mode = "offline verifier responses"
    elif args.provider == "openai":
        client = OpenAIChatClient(OpenAIConfig.from_env())
        model_call = client.complete_json
        source_mode = "OpenAI API test provider"
    elif args.provider == "openrouter":
        client = OpenRouterChatClient(OpenRouterConfig.from_env())
        model_call = client.complete_json
        source_mode = "OpenRouter test provider"
    else:
        client = FoundryChatClient(FoundryConfig.from_env())
        model_call = client.complete_json
        source_mode = "Microsoft Foundry"

    verified = run_claim_verifier(analysis, model_call)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        verified.model_dump_json(indent=2),
        encoding="utf-8",
    )

    claims = [
        claim
        for step in verified.steps
        if step.id != "step-verification"
        for claim in step.claims
    ]
    counts: dict[str, int] = {}
    for claim in claims:
        key = claim.verification_status.value
        counts[key] = counts.get(key, 0) + 1

    print(
        f"Claim Verifier completed\n"
        f"mode={source_mode}\n"
        f"claims={len(claims)}\n"
        f"statuses={counts}\n"
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
