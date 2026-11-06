"""Print a game log written by the tournament runner.

  python scripts/replay.py results/<run-id>/round_1/games/g0001.jsonl
  python scripts/replay.py results/<run-id>/round_1/games/g0001.jsonl --reveal
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coup.runner.reporting import hands_path, is_hands_log  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a Coup game log.")
    parser.add_argument("log", type=Path)
    parser.add_argument(
        "--reveal",
        action="store_true",
        help="Print face-down hands after each event (reads the .hands.jsonl sibling)",
    )
    args = parser.parse_args()
    if not args.log.is_file():
        print(f"file not found: {args.log}")
        sys.exit(1)
    source = args.log
    if args.reveal and not is_hands_log(source):
        source = hands_path(args.log)
        if not source.is_file():
            print(f"no hands file next to this log: {source}")
            sys.exit(1)
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        if row["type"] == "game":
            print(f"Game {row['id']}  seed {row['seed']}")
            print("Players: " + ", ".join(row["players"]))
            print()
        elif row["type"] == "event":
            print(row["message"])
            if args.reveal:
                hands = _hands(row)
                if hands:
                    print(f"    hands: {hands}")
        elif row["type"] == "result":
            print()
            print(f"Turns: {row['turns']}  capped: {row['capped']}  winner: {row['winner']}")
            for placement in row["placements"]:
                print(
                    f"{placement['place']}. {placement['name']}  "
                    f"{placement['points']} pts  influence {placement['influence']}  coins {placement['coins']}"
                )


def _hands(row: dict) -> str:
    players = (row.get("state") or {}).get("players") or []
    parts = [
        f"{player.get('name')}=[{', '.join(player['hand'])}]"
        for player in players
        if isinstance(player, dict) and player.get("hand")
    ]
    return "  ".join(parts)


if __name__ == "__main__":
    main()
