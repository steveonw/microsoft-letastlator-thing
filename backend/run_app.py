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

    httpd = server.ThreadingHTTPServer((server.HOST, server.PORT), server.Handler)
    print("PolicyTrace")
    print("===========")
    print(f"Open http://{server.HOST}:{server.PORT}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
