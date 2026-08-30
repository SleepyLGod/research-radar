"""Narrow command-line entrypoint for the bundled macOS bridge."""

from __future__ import annotations

import argparse
from pathlib import Path

from research_radar.app_bridge.runner import run_bridge


def main() -> int:
    """Run exactly one file-protocol request."""

    parser = argparse.ArgumentParser(prog="research-radar-engine")
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--error", type=Path, required=True)
    args = parser.parse_args()
    return run_bridge(
        request_path=args.request,
        events_path=args.events,
        result_path=args.result,
        error_path=args.error,
    )


if __name__ == "__main__":
    raise SystemExit(main())
