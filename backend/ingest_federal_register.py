from __future__ import annotations

import argparse
from pathlib import Path

from federal_register import fetch_and_normalize, load_fixture_and_normalize


DEFAULT_DOCUMENT_NUMBER = "2024-20529"
DEFAULT_OUTPUT = Path("data/federal-register/2024-20529.normalized.json")
DEFAULT_FIXTURE = Path("data/federal-register/2024-20529.fixture.json")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch and normalize one Federal Register document for PolicyTrace."
    )
    parser.add_argument(
        "document_number",
        nargs="?",
        default=DEFAULT_DOCUMENT_NUMBER,
        help=f"Federal Register document number (default: {DEFAULT_DOCUMENT_NUMBER})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--chunk-chars",
        type=int,
        default=4500,
        help="Approximate maximum characters per normalized chunk.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the checked-in fixture instead of making a network request.",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help=f"Offline fixture path (default: {DEFAULT_FIXTURE})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.offline:
        document = load_fixture_and_normalize(
            args.fixture,
            max_chunk_chars=args.chunk_chars,
        )
    else:
        document = fetch_and_normalize(
            args.document_number,
            max_chunk_chars=args.chunk_chars,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        document.model_dump_json(indent=2),
        encoding="utf-8",
    )

    print(
        f"Normalized {document.document_number}: {document.title}\n"
        f"agency={', '.join(document.agency_names) or 'unknown'}\n"
        f"publication_date={document.publication_date}\n"
        f"chunks={len(document.chunks)}\n"
        f"source={'offline fixture' if args.offline else 'live Federal Register'}\n"
        f"output={args.output}"
    )


if __name__ == "__main__":
    main()
