#!/usr/bin/env python3
"""
drive.py - a command-line driver for the PolicyTrace guide server.

This is the harness I use to exercise the running app the way a reviewer would:
call an endpoint, print the resulting state as a table, and see immediately
whether the rules held. It is a testing tool, not part of the product.

Why it exists
-------------
Unit tests prove a function behaves. They do not prove the *running system*
behaves, because the server, the state machine and the HTTP layer can each
drift from what the tests assert. This driver talks to the real server over
real HTTP, so what you see is what a browser would get.

The important habit it encodes: after every call, print the whole state, not
just the field you were interested in. Most of the bugs found in this project
showed up in a column nobody was looking at -- a step still marked
`not_reviewed` after an approval, a version that did not increment, a
dependent step that stayed `draft` when it should have gone stale.

Usage
-----
    # start the server first, in another terminal:
    python3 backend/run_full_stack_guide.py

    python3 tools/drive.py state
    python3 tools/drive.py rush
    python3 tools/drive.py edit STEP "text"
    python3 tools/drive.py chain
    python3 tools/drive.py brief
    python3 tools/drive.py gate
    python3 tools/drive.py demo
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8777"
TIMEOUT = 60

DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
STATUS_COLOUR = {
    "draft": "\033[33m",
    "needs_refresh": "\033[31m",
    "verified": "\033[36m",
    "not_reviewed": "\033[33m",
    "in_review": "\033[36m",
    "reviewed": "\033[32m",
    "approved": "\033[32m",
}


def paint(value: str) -> str:
    return f"{STATUS_COLOUR.get(value, '')}{value}{RESET}"


def call(path: str, payload: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if data is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"error": f"HTTP {exc.code}: {body[:200]}"}
    except urllib.error.URLError as exc:
        sys.exit(
            f"Cannot reach {BASE_URL} ({exc.reason}).\n"
            "Start it with:  python3 backend/run_full_stack_guide.py"
        )


def analysis_of(result: dict) -> dict:
    return result.get("analysis", result)


def show(result: dict, heading: str = "") -> dict:
    if heading:
        print(f"\n{BOLD}{heading}{RESET}")

    if result.get("error"):
        print(f"  {STATUS_COLOUR['needs_refresh']}REFUSED{RESET}: {result['error']}")
        return {}

    run = analysis_of(result)
    print(
        f"  mode={run.get('mode')}  "
        f"final_review={paint(str(run.get('final_review_status')))}  "
        f"current={run.get('current_step_id')}"
    )
    print(
        f"  {DIM}{'section':<24}{'v':<4}{'status':<16}"
        f"{'review':<14}{'claims':<8}edited{RESET}"
    )
    for step in run.get("steps", []):
        edited = step["human_review"].get("edited_claim_ids") or []
        status = paint(step["status"]).ljust(16 + len(paint("")) - 0)
        review = paint(step["human_review"]["status"])
        print(
            f"  {step['kind']:<24}{step['version']:<4}"
            f"{status}{review:<14}"
            f"{len(step['claims']):<8}{','.join(edited) or '-'}"
        )
    return run


def cmd_state(_: argparse.Namespace) -> None:
    show(call("/api/analysis"), "current state")


def cmd_rush(_: argparse.Namespace) -> None:
    call("/api/reset", {})
    show(call("/api/rush/run", {}), "rush run (AI analysis, stops before approval)")


def cmd_edit(args: argparse.Namespace) -> None:
    show(
        call(
            "/api/reanalysis/step",
            {"step_id": args.step, "text": args.text, "human_edited": True},
        ),
        f"human edit of {args.step} -> dependents should go needs_refresh",
    )


def cmd_chain(_: argparse.Namespace) -> None:
    run = analysis_of(call("/api/analysis"))
    for step in run.get("steps", []):
        step_id = step["id"]
        if step["status"] == "needs_refresh":
            call("/api/reanalysis/refresh", {"step_id": step_id})
        call("/api/reanalysis/review", {"step_id": step_id})
    show(call("/api/analysis"), "after refreshing and reviewing every section")


def cmd_brief(_: argparse.Namespace) -> None:
    result = call("/api/brief", {})
    run = show(result, "final brief")
    for step in run.get("steps", []):
        if step["kind"] == "draft_brief":
            print(f"\n{DIM}{'-' * 68}{RESET}")
            print(step.get("ai_output") or "(empty)")


def cmd_gate(_: argparse.Namespace) -> None:
    call("/api/reset", {})
    call("/api/rush/run", {})
    probes = [("approve with nothing reviewed", "/api/rush/approve", {})]

    call(
        "/api/reanalysis/step",
        {
            "step_id": "step-policy-understanding",
            "text": "Probe edit to make downstream sections stale.",
            "human_edited": True,
        },
    )

    probes += [
        (
            "refresh out of dependency order",
            "/api/reanalysis/refresh",
            {"step_id": "step-public-response"},
        ),
        (
            "review a stale section",
            "/api/reanalysis/review",
            {"step_id": "step-major-provisions"},
        ),
        ("brief while sections are stale", "/api/brief", {}),
    ]

    print(f"\n{BOLD}guard rails (every line should be REFUSED){RESET}")
    for label, path, payload in probes:
        result = call(path, payload)
        if result.get("error"):
            print(f"  {STATUS_COLOUR['reviewed']}refused{RESET}  {label}")
            print(f"           {DIM}{result['error'][:100]}{RESET}")
        else:
            print(f"  {STATUS_COLOUR['needs_refresh']}ALLOWED{RESET}  {label}  <-- BUG")


def cmd_demo(_: argparse.Namespace) -> None:
    call("/api/reset", {})
    show(call("/api/rush/run", {}), "1. rush run -- AI analysed, nothing approved yet")

    show(
        call("/api/rush/approve", {}),
        "2. try to approve without reading it -- refused",
    )

    show(
        call(
            "/api/reanalysis/step",
            {
                "step_id": "step-policy-understanding",
                "text": "Human rewrite: the rule would require quarterly reporting.",
                "human_edited": True,
            },
        ),
        "3. a human edits one finding -- everything downstream goes stale",
    )

    show(call("/api/brief", {}), "4. try to brief on stale work -- refused")
    cmd_chain(argparse.Namespace())
    cmd_brief(argparse.Namespace())


COMMANDS = {
    "state": cmd_state,
    "rush": cmd_rush,
    "edit": cmd_edit,
    "chain": cmd_chain,
    "brief": cmd_brief,
    "gate": cmd_gate,
    "demo": cmd_demo,
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Drive the PolicyTrace guide server from the command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("state", "rush", "chain", "brief", "gate", "demo"):
        sub.add_parser(name)

    edit = sub.add_parser("edit")
    edit.add_argument("step", help="step id, e.g. step-policy-understanding")
    edit.add_argument("text", help="replacement claim text")

    args = parser.parse_args()
    COMMANDS[args.command](args)


if __name__ == "__main__":
    main()
