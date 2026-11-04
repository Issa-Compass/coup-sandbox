"""Download approved hub agents into agents/submissions/ for a tournament round.

Requires a coup-master `.env` (COUP_MASTER_URL). API key is not required to list
or download approved agents.

  python scripts/collect_submissions.py
  python scripts/collect_submissions.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coup.hub_client import HubError, download_agent, list_remote_agents, load_repo_dotenv  # noqa: E402
from coup.runner.catalog import SUBMISSIONS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pull coup-master agents into agents/submissions/ (gitignored)."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing agents/submissions/<name>/agent.py files.",
    )
    parser.add_argument("--url", default=None, help="Override COUP_MASTER_URL")
    args = parser.parse_args()
    load_repo_dotenv()
    try:
        agents = list_remote_agents(base_url=args.url)
    except HubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    if not agents:
        print("No approved hub agents to collect.")
        sys.exit(1)
    SUBMISSIONS.mkdir(parents=True, exist_ok=True)
    collected = 0
    skipped = 0
    for agent in agents:
        dest = SUBMISSIONS / agent.name / "agent.py"
        if dest.is_file() and not args.force:
            print(f"skip {agent.name}: already present (pass --force to overwrite)")
            skipped += 1
            continue
        try:
            written = download_agent(agent.name, dest, base_url=args.url)
        except HubError as exc:
            print(f"error: {agent.name}: {exc}", file=sys.stderr)
            sys.exit(1)
        who = f" ({agent.full_name or agent.uploader})" if (agent.full_name or agent.uploader) else ""
        print(f"collected {agent.name}{who} -> {written}")
        collected += 1
    print(f"Collected {collected} agent(s), skipped {skipped}.")
    if collected == 0 and skipped == 0:
        sys.exit(1)
    print("Review agents/submissions/, then run: python scripts/tournament.py --round 1 --submissions")


if __name__ == "__main__":
    main()
