from __future__ import annotations

import argparse
from pathlib import Path

from foundry_client import FoundryChatClient, FoundryConfig
from openai_client import OpenAIChatClient, OpenAIConfig
from federal_register import fetch_and_normalize, load_fixture_and_normalize
from policy_interpreter import (
    PolicyInterpreterOutput,
    build_analysis_from_interpreter_output,
    run_policy_interpreter,
)


DEFAULT_DOCUMENT_NUMBER = "2024-20529"
DEFAULT_SOURCE_FIXTURE = Path("data/federal-register/2024-20529.fixture.json")
DEFAULT_RESPONSE_FIXTURE = Path(
    "data/policy-interpreter/2024-20529.interpreter-response.json"
)
DEFAULT_OUTPUT = Path("data/policy-interpreter/2024-20529.chunk4-analysis.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the PolicyTrace Policy Interpreter over one policy."
    )
    parser.add_argument(
        "document_number",
        nargs="?",
        default=DEFAULT_DOCUMENT_NUMBER,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Use the checked-in source + interpreter response fixtures. "
            "No network or model call is made."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=("foundry", "openai"),
        default="foundry",
        help=(
            "Live model provider. 'openai' is a temporary API-key test path; "
            "'foundry' remains the hackathon target."
        ),
    )
    parser.add_argument(
        "--source-fixture",
        type=Path,
        default=DEFAULT_SOURCE_FIXTURE,
    )
    parser.add_argument(
        "--response-fixture",
        type=Path,
        default=DEFAULT_RESPONSE_FIXTURE,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.offline:
        document = load_fixture_and_normalize(args.source_fixture)
        output = PolicyInterpreterOutput.model_validate_json(
            args.response_fixture.read_text(encoding="utf-8")
        )
        analysis = build_analysis_from_interpreter_output(
            document,
            output,
        )
        source_mode = "offline fixtures"
    else:
        document = fetch_and_normalize(args.document_number)

        if args.provider == "openai":
            client = OpenAIChatClient(OpenAIConfig.from_env())
            source_mode = "live Federal Register + OpenAI API test provider"
        else:
            client = FoundryChatClient(FoundryConfig.from_env())
            source_mode = "live Federal Register + Microsoft Foundry"

        analysis = run_policy_interpreter(
            document,
            client.complete_json,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        analysis.model_dump_json(indent=2),
        encoding="utf-8",
    )

    claim_count = sum(len(step.claims) for step in analysis.steps)
    print(
        f"Policy Interpreter completed for {args.document_number}\n"
        f"mode={source_mode}\n"
        f"steps={len(analysis.steps)}\n"
        f"claims={claim_count}\n"
        f"evidence={len(analysis.evidence)}\n"
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
