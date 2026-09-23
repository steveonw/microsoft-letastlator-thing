from __future__ import annotations

import argparse
import json
from pathlib import Path

from federal_register import fetch_and_normalize, load_fixture_and_normalize
from foundry_client import FoundryChatClient, FoundryConfig
from models import AnalysisMode, AnalysisRun
from openai_client import OpenAIChatClient, OpenAIConfig
from openrouter_client import OpenRouterChatClient, OpenRouterConfig
from policy_interpreter import (
    PolicyInterpreterOutput,
    build_analysis_from_interpreter_output,
    run_policy_interpreter,
)
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
from rush_mode import (
    approve_rush_final_review,
    open_rush_step_for_review,
    return_to_rush_final_review,
    run_rush_analysis,
)


DEFAULT_DOCUMENT_NUMBER = "2024-20529"
DEFAULT_DOCKET_ID = "BIS-2024-0047"
DEFAULT_SOURCE_FIXTURE = Path("data/federal-register/2024-20529.fixture.json")
DEFAULT_POLICY_FIXTURE = Path(
    "data/policy-interpreter/2024-20529.interpreter-response.json"
)
DEFAULT_RESPONSE_FIXTURE = Path(
    "data/response-analysis/BIS-2024-0047.responses.fixture.json"
)
DEFAULT_ANALYST_FIXTURE = Path(
    "data/response-analysis/BIS-2024-0047.analyst-response.json"
)
DEFAULT_OUTPUT = Path("data/rush/2024-20529.chunk8-analysis.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or review a PolicyTrace Rush Analysis."
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="run",
        choices=("run", "open", "final", "approve"),
    )
    parser.add_argument("document_number", nargs="?", default=DEFAULT_DOCUMENT_NUMBER)
    parser.add_argument("--docket-id", default=DEFAULT_DOCKET_ID)
    parser.add_argument("--max-comments", type=int, default=12)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--step-id")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument(
        "--provider",
        choices=("foundry", "openai", "openrouter"),
        default="foundry",
    )
    parser.add_argument("--source-fixture", type=Path, default=DEFAULT_SOURCE_FIXTURE)
    parser.add_argument("--policy-fixture", type=Path, default=DEFAULT_POLICY_FIXTURE)
    parser.add_argument("--response-fixture", type=Path, default=DEFAULT_RESPONSE_FIXTURE)
    parser.add_argument("--analyst-fixture", type=Path, default=DEFAULT_ANALYST_FIXTURE)
    return parser.parse_args()


def _client(provider: str):
    if provider == "openai":
        return OpenAIChatClient(OpenAIConfig.from_env())
    if provider == "openrouter":
        return OpenRouterChatClient(OpenRouterConfig.from_env())
    return FoundryChatClient(FoundryConfig.from_env())


def _offline_verifier(system_prompt: str, user_prompt: str) -> str:
    del system_prompt, user_prompt
    return json.dumps(
        {
            "status": "supported",
            "explanation": "Offline fixture verification response for deterministic CI.",
            "narrower_wording": None,
        }
    )


def _run_pipeline(args: argparse.Namespace) -> AnalysisRun:
    if args.offline:
        document = load_fixture_and_normalize(args.source_fixture)

        policy_output = PolicyInterpreterOutput.model_validate_json(
            args.policy_fixture.read_text(encoding="utf-8")
        )
        policy_analysis = build_analysis_from_interpreter_output(
            document,
            policy_output,
            mode=AnalysisMode.RUSH,
        )

        response_records = load_response_fixture(args.response_fixture)
        response_sources = [
            source_from_response_record(record)
            for record in response_records
        ]
        response_output = ResponseViewpointOutput.model_validate_json(
            args.analyst_fixture.read_text(encoding="utf-8")
        )
        response_analysis = build_response_analysis(
            document,
            response_sources,
            response_output,
            mode=AnalysisMode.RUSH,
        )

        return run_rush_analysis(
            policy_analysis,
            response_analysis,
            _offline_verifier,
        )

    document = fetch_and_normalize(args.document_number)
    client = _client(args.provider)

    policy_analysis = run_policy_interpreter(
        document,
        client.complete_json,
        mode=AnalysisMode.RUSH,
    )

    response_records = fetch_comments_for_docket(
        args.docket_id,
        max_comments=args.max_comments,
    )
    response_sources = [
        source_from_response_record(record)
        for record in response_records
    ]
    response_analysis = run_response_viewpoint_analyst(
        document,
        response_sources,
        client.complete_json,
        mode=AnalysisMode.RUSH,
    )

    return run_rush_analysis(
        policy_analysis,
        response_analysis,
        client.complete_json,
    )


def _load_review_input(args: argparse.Namespace) -> tuple[AnalysisRun, Path]:
    path = args.input or args.output
    analysis = AnalysisRun.model_validate_json(path.read_text(encoding="utf-8"))
    return analysis, path


def main() -> None:
    args = parse_args()

    if args.action == "run":
        analysis = _run_pipeline(args)
        destination = args.output
    else:
        analysis, source_path = _load_review_input(args)

        if args.action == "open":
            if not args.step_id:
                raise SystemExit("--step-id is required for the open action")
            analysis = open_rush_step_for_review(analysis, args.step_id)
        elif args.action == "final":
            analysis = return_to_rush_final_review(analysis)
        else:
            analysis = approve_rush_final_review(analysis)

        destination = args.output if args.output != DEFAULT_OUTPUT else source_path

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        analysis.model_dump_json(indent=2),
        encoding="utf-8",
    )

    print(
        "Rush Mode action completed\n"
        f"action={args.action}\n"
        f"mode={analysis.mode.value}\n"
        f"current_step={analysis.current_step_id or 'human-final-review'}\n"
        f"final_review_status={analysis.final_review_status.value}\n"
        f"steps={len(analysis.steps)}\n"
        f"output={destination}"
    )


if __name__ == "__main__":
    main()
