"""Run one game and print the public log.

Examples:
  python scripts/play.py
  python scripts/play.py --agents template,random,honest --seed 3 --reveal
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coup.runner.catalog import resolve_agent  # noqa: E402
from coup.runner.load_agent import agent_name_from_path  # noqa: E402
from coup.runner.match import play_game  # noqa: E402
from coup.runner.players import open_player  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Play one Coup game.")
    parser.add_argument(
        "--agents",
        default="random,honest,guard,turtle,greedy",
        help="Comma-separated aliases (random, honest, guard, turtle, greedy, bluffer, challenger, template) or file paths.",
    )
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--sandbox", action="store_true", help="Run each agent in a subprocess.")
    parser.add_argument("--reveal", action="store_true", help="Print hidden cards. Organizer debugging only.")
    args = parser.parse_args()
    tokens = [token.strip() for token in args.agents.split(",") if token.strip()]
    paths = [resolve_agent(token) for token in tokens]
    names = _unique_names(paths)
    players = [
        open_player(path, name, sandbox=args.sandbox, timeout=args.timeout)
        for path, name in zip(paths, names)
    ]
    try:
        played = play_game(players, seed=args.seed, max_turns=args.max_turns)
    finally:
        for player in players:
            player.close()
    if args.reveal:
        print("Hidden hands at the end (eliminated hands are empty):")
        for player in played.game.players:
            cards = ", ".join(card.value for card in player.cards) or "none"
            print(f"  {player.name}: {cards}")
        print()
    for event in played.game.history:
        print(event.message)
    print()
    for placement in played.result.placements:
        print(
            f"{placement.place}. {placement.name}  "
            f"{placement.points} pts  influence {placement.influence}  coins {placement.coins}"
        )
    faults = []
    for name, penalty in played.penalties.items():
        if penalty["illegal"] or penalty["errors"] or penalty["timeouts"]:
            faults.append(
                f"{name}: illegal {penalty['illegal']}, errors {penalty['errors']}, timeouts {penalty['timeouts']}"
            )
    if faults:
        print()
        print("Penalties:")
        for line in faults:
            print(f"  {line}")


def _unique_names(paths: list[Path]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for path in paths:
        base = agent_name_from_path(path)
        name = base
        suffix = 2
        while name in seen:
            name = f"{base}_{suffix}"
            suffix += 1
        seen.add(name)
        names.append(name)
    return names


if __name__ == "__main__":
    main()
