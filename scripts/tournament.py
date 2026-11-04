"""Play a round and write results/<run-id>/round_N/.

With no agents and no submissions, the four example bots play each other.

  python scripts/tournament.py --round 1 --games-per-agent 6 --no-sandbox
  python scripts/tournament.py --round 1 --submissions
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coup.runner.catalog import EXAMPLES, submission_agents  # noqa: E402
from coup.runner.tournament import default_agent_paths, run_round  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a Coup round.")
    parser.add_argument("--agents", nargs="*", default=None, help="Aliases or file paths.")
    parser.add_argument("--submissions", action="store_true", help="Use agents/submissions/*/agent.py.")
    parser.add_argument("--with-examples", action="store_true", help="Add the example bots to submissions.")
    parser.add_argument("--games-per-agent", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1, help="Master seed for seating. Deck seeds stay secret.")
    parser.add_argument("--round", type=int, required=True, dest="round_number")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--table-size", type=int, default=5)
    parser.add_argument("--sandbox", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.agents:
        paths = default_agent_paths(args.agents, with_examples=False)
    elif args.submissions:
        paths = submission_agents()
        if args.with_examples:
            paths = list(paths) + [
                EXAMPLES[name] for name in ("random", "honest", "knife", "turtle", "greedy")
            ]
        if len(paths) < 2:
            print("Need at least 2 agents. Add submissions or pass --with-examples.")
            sys.exit(1)
    else:
        paths = default_agent_paths(None, with_examples=False)
    try:
        run_round(
            paths,
            games_per_agent=args.games_per_agent,
            master_seed=args.seed,
            round_number=args.round_number,
            run_id=args.run_id,
            timeout=args.timeout,
            sandbox=args.sandbox,
            table_size=args.table_size,
            force=args.force,
        )
    except (ValueError, FileExistsError, FileNotFoundError) as exc:
        print(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
