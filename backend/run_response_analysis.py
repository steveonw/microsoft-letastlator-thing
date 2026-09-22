from __future__ import annotations

import argparse
from pathlib import Path

from federal_register import fetch_and_normalize, load_fixture_and_normalize
from foundry_client import FoundryChatClient, FoundryConfig
from openai_client import OpenAIChatClient, OpenAIConfig
from openrouter_client import OpenRouterChatClient, OpenRouterConfig
from response_sources import (
    fetch_comments_for_docket,
    load_response_fixture,
    source_from_response_record,
)
from response_viewpoint_analyst import (
    ResponseViewpointOutput,
    build_response_analysis,
    run_response_viewpoint_analyst,
)


DEFAULT_DOCUMENT_NUMBER = "2024-20529"
DEFAULT_DOCKET_ID = "BIS-2024-0047"
DEFAULT_SOURCE_FIXTURE = Path("data/federal-register/2024-20529.fixture.json")
DEFAULT_RESPONSE_FIXTURE = Path(
    "data/response-analysis/BIS-2024-0047.responses.fixture.json"
)
DEFAULT_ANALYST_FIXTURE = Path(
    "data/response-analysis/BIS-2024-0047.analyst-response.json"
)
DEFAULT_OUTPUT = Path("data/response-analysis/2024-20529.chunk5-analysis.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the PolicyTrace Response & Viewpoint Analyst."
    )
    parser.add_argument(
        "document_number",
        nargs="?",
        default=DEFAULT_DOCUMENT_NUMBER,
    )
    parser.add_argument(
        "--docket-id",
        default=DEFAULT_DOCKET_ID,
    )
    parser.add_argument(
        "--max-comments",
        type=int,
        default=12,
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
            "Use synthetic checked-in response fixtures. "
            "No Regulations.gov or model network calls are made."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=("foundry", "openai", "openrouter"),
        default="foundry",
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
    parser.add_argument(
        "--analyst-fixture",
        type=Path,
        default=DEFAULT_ANALYST_FIXTURE,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.offline:
        document = load_fixture_and_normalize(args.source_fixture)
        response_records = load_response_fixture(args.response_fixture)
        response_sources = [
            source_from_response_record(record)
            for record in response_records
        ]
        output = ResponseViewpointOutput.model_validate_json(
            args.analyst_fixture.read_text(encoding="utf-8")
        )
        analysis = build_response_analysis(
            document,
            response_sources,
            output,
        )
        source_mode = "synthetic offline response fixtures"
    else:
        document = fetch_and_normalize(args.document_number)
        response_records = fetch_comments_for_docket(
            args.docket_id,
            max_comments=args.max_comments,
        )
        response_sources = [
            source_from_response_record(record)
            for record in response_records
        ]

        if args.provider == "openai":
            client = OpenAIChatClient(OpenAIConfig.from_env())
            provider_name = "OpenAI API test provider"
        elif args.provider == "openrouter":
            client = OpenRouterChatClient(OpenRouterConfig.from_env())
            provider_name = "OpenRouter test provider"
        else:
            client = FoundryChatClient(FoundryConfig.from_env())
            provider_name = "Microsoft Foundry"

        analysis = run_response_viewpoint_analyst(
            document,
            response_sources,
            client.complete_json,
        )
        source_mode = (
            f"live Regulations.gov + {provider_name} "
            f"({len(response_sources)} response sources)"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        analysis.model_dump_json(indent=2),
        encoding="utf-8",
    )

    claim_count = sum(len(step.claims) for step in analysis.steps)
    print(
        f"Response & Viewpoint Analyst completed for {args.document_number}\n"
        f"mode={source_mode}\n"
        f"steps={len(analysis.steps)}\n"
        f"claims={claim_count}\n"
        f"evidence={len(analysis.evidence)}\n"
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
