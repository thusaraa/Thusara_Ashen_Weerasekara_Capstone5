"""Run the course demo: 'Brief me on NVDA earnings risk'.

The default run uses live prices and the chat model when a key is set.
`--offline` writes the same handoff from fixture data so the route, the
critique, and the refine step are visible without the network.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from config import ROOT, has_chat_key
from coordinator import render, run
from llm import build_complete
from market import FixtureMarket, YFinanceMarket
from mcp_client import LocalToolClient

GOAL = "Brief me on NVDA earnings risk"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write demo_run.md for the NVDA brief")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "demo_run.md"))
    args = parser.parse_args(argv)

    mode = "offline fixture"
    if args.offline or not has_chat_key():
        brief = run(GOAL, LocalToolClient(FixtureMarket()))
        if not args.offline and not has_chat_key():
            mode = "offline fixture, no chat key"
    else:
        brief = run(GOAL, LocalToolClient(YFinanceMarket()), build_complete())
        mode = "live market data and chat model"

    body = f"Mode: {mode}\n\n" + render(brief)
    Path(args.output).write_text(body, encoding="utf-8")
    print(f"Wrote {args.output} ({mode})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
