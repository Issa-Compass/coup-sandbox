"""Check an agent the way the event will.

Exit 0 and print READY when the file is legal. Win rate is informational.

  python scripts/test_agent.py agents/template/agent.py
  python scripts/test_agent.py agents/submissions/ada/agent.py --games 200
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coup.runner.testing import evaluate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a Coup agent.")
    parser.add_argument("agent", type=Path, help="Path to the agent file.")
    parser.add_argument("--games", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument(
        "--sandbox-games",
        type=int,
        default=3,
        help="Extra games in a subprocess, to catch import and timeout problems.",
    )
    args = parser.parse_args()
    path = args.agent if args.agent.is_file() else ROOT / args.agent
    if not path.is_file():
        print(f"file not found: {args.agent}")
        sys.exit(1)
    report = evaluate(path, games=args.games, timeout=args.timeout, sandbox_games=args.sandbox_games)
    print(report.text())
    sys.exit(0 if report.ready else 1)


if __name__ == "__main__":
    main()
