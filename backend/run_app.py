#!/usr/bin/env python3
"""
Run the PolicyTrace app.

This is the entry point for the product UI. It reuses the API from
run_full_stack_guide (those endpoints already work and are tested) and serves
frontend/app instead of the developer reference page, so there is exactly one
server and one set of review rules.

    python3 backend/run_app.py
    open http://127.0.0.1:8777/
"""

from __future__ import annotations

from pathlib import Path

import run_full_stack_guide as server

ROOT = Path(__file__).resolve().parents[1]
server.APP_DIR = ROOT / "frontend" / "app"


def main() -> None:
    missing = [
        name
        for name in ("index.html", "app.js", "styles.css")
        if not (server.APP_DIR / name).exists()
    ]
    if missing:
        raise SystemExit(f"missing app files: {', '.join(missing)}")

    try:
        httpd = server.ThreadingHTTPServer((server.HOST, server.PORT), server.Handler)
    except OSError as exc:
        if exc.errno not in (48, 98, 10048):  # mac, linux, windows
            raise
        raise SystemExit(
            f"\nSomething is already running on port {server.PORT}.\n\n"
            "Your browser will be talking to THAT server, not this one, so any\n"
            "changes you just made will not show up.\n\n"
            "Stop the old one first:\n"
            "  Windows (Git Bash):  taskkill //F //IM python.exe\n"
            "  macOS / Linux:       pkill -f run_app.py; pkill -f run_full_stack_guide.py\n\n"
            "Then run this again, and hard-refresh the browser with Ctrl+F5.\n"
        ) from exc

    print("PolicyTrace")
    print("===========")
    print(f"Serving the product UI from: {server.APP_DIR}")
    print(f"Open http://{server.HOST}:{server.PORT}/")
    print("Check the build marker in the header after a hard refresh.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
