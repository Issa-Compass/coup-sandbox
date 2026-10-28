"""Print a game log written by the tournament runner.

  python scripts/replay.py results/<run-id>/round_1/games/g0001.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a Coup game log.")
    parser.add_argument("log", type=Path)
    args = parser.parse_args()
    if not args.log.is_file():
        print(f"file not found: {args.log}")
        sys.exit(1)
    rows = [json.loads(line) for line in args.log.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        if row["type"] == "game":
            print(f"Game {row['id']}  seed {row['seed']}")
            print("Players: " + ", ".join(row["players"]))
            print()
        elif row["type"] == "event":
            print(row["message"])
        elif row["type"] == "result":
            print()
            print(f"Turns: {row['turns']}  capped: {row['capped']}  winner: {row['winner']}")
            for placement in row["placements"]:
                print(
                    f"{placement['place']}. {placement['name']}  "
                    f"{placement['points']} pts  influence {placement['influence']}  coins {placement['coins']}"
                )


if __name__ == "__main__":
    main()
