from __future__ import annotations

import argparse
from pathlib import Path

from evidence import build_chunk3_demo_analysis
from federal_register import fetch_and_normalize, load_fixture_and_normalize


DEFAULT_DOCUMENT_NUMBER = "2024-20529"
DEFAULT_QUERY = "Covered U.S. persons are required to submit a notification"
DEFAULT_OUTPUT = Path("data/evidence/2024-20529.chunk3-demo.json")
DEFAULT_FIXTURE = Path("data/federal-register/2024-20529.fixture.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a real-source PolicyTrace evidence demo from a Federal "
            "Register document."
        )
    )
    parser.add_argument(
        "document_number",
        nargs="?",
        default=DEFAULT_DOCUMENT_NUMBER,
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help="Literal substantive source phrase used to select inspectable evidence.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the checked-in Federal Register fixture instead of the network.",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.offline:
        document = load_fixture_and_normalize(args.fixture)
    else:
        document = fetch_and_normalize(args.document_number)

    analysis = build_chunk3_demo_analysis(
        document,
        query=args.query,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        analysis.model_dump_json(indent=2),
        encoding="utf-8",
    )

    evidence = analysis.evidence[0]
    claim = analysis.steps[0].claims[0]
    print(
        f"Chunk 3 evidence demo built for {args.document_number}\n"
        f"claim={claim.id}\n"
        f"evidence={evidence.id}\n"
        f"locator={evidence.locator}\n"
        f"source={'offline fixture' if args.offline else 'live Federal Register'}\n"
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
