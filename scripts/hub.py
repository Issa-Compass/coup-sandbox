"""Talk to coup-master from a local sandbox.

Put the in-person `.env` (COUP_MASTER_URL + COUP_MASTER_API_KEY) in the repo
root, or export those variables. Upload needs the API key.

  python scripts/hub.py list
  python scripts/hub.py upload milo --full-name "Ada Lovelace"
  python scripts/hub.py download other-bot

  # Organizer:
  python scripts/hub.py reject bad-bot
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coup.hub_client import (  # noqa: E402
    HubError,
    approve_agent,
    download_agent,
    download_queue_agent,
    list_queue,
    list_remote_agents,
    load_repo_dotenv,
    reject_agent,
    upload_agent,
)
from coup.runner.catalog import LOCAL, resolve_agent  # noqa: E402


def main() -> None:
    load_repo_dotenv()
    parser = argparse.ArgumentParser(description="Coup master hub client")
    parser.add_argument("--url", default=None, help="Override COUP_MASTER_URL")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List approved remote submissions")

    up = sub.add_parser("upload", help="Upload a local agent (listed immediately if safe)")
    up.add_argument("name", help="Unique submission name (A-Za-z0-9_-)")
    up.add_argument("--path", type=Path, default=None, help="Path to agent.py (default: resolve name)")
    up.add_argument(
        "--full-name",
        required=True,
        help="Your full name (at least two names; middle names OK)",
    )

    down = sub.add_parser("download", help="Download an approved remote agent into agents/local/")
    down.add_argument("name", help="Remote agent name")
    down.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="Destination file or folder (default: agents/local/<name>/agent.py)",
    )

    sub.add_parser("queue", help="Organizer: list any leftover quarantined uploads")

    pull = sub.add_parser("pull-queue", help="Organizer: download a quarantined agent")
    pull.add_argument("name")
    pull.add_argument("--dest", type=Path, default=None)

    ap = sub.add_parser("approve", help="Organizer: mark approved (legacy; uploads auto-approve)")
    ap.add_argument("name")
    ap.add_argument("--actor", default=None, help="Optional approver label")

    rj = sub.add_parser("reject", help="Organizer: delete a hub agent")
    rj.add_argument("name")
    rj.add_argument("--actor", default=None, help="Optional actor label")

    args = parser.parse_args()
    try:
        if args.cmd == "list":
            agents = list_remote_agents(base_url=args.url)
            if not agents:
                print("(no approved remote agents yet)")
                return
            for agent in agents:
                who = f"  uploader={agent.uploader}" if agent.uploader else ""
                print(f"{agent.name}\t{agent.size_bytes}B\t{agent.uploaded_at}{who}")
            return

        if args.cmd == "upload":
            path = args.path or resolve_agent(args.name)
            meta = upload_agent(
                args.name, path, base_url=args.url, full_name=args.full_name
            )
            who = f" by {meta.full_name}" if meta.full_name else ""
            print(
                f"uploaded {meta.name}{who} status={meta.status} "
                f"sha256={meta.sha256[:12]}… size={meta.size_bytes}"
            )
            return

        if args.cmd == "download":
            dest = args.dest or (LOCAL / args.name / "agent.py")
            written = download_agent(args.name, dest, base_url=args.url)
            print(f"wrote {written}")
            return

        if args.cmd == "queue":
            agents = list_queue(base_url=args.url)
            if not agents:
                print("(quarantine empty)")
                return
            for agent in agents:
                who = f"  uploader={agent.uploader}" if agent.uploader else ""
                print(f"{agent.name}\t{agent.size_bytes}B\t{agent.uploaded_at}{who}")
            return

        if args.cmd == "pull-queue":
            dest = args.dest or (Path("/tmp") / f"coup-queue-{args.name}" / "agent.py")
            written = download_queue_agent(args.name, dest, base_url=args.url)
            print(f"wrote {written}")
            return

        if args.cmd == "approve":
            meta = approve_agent(args.name, base_url=args.url, actor=args.actor)
            print(f"approved {meta.name} status={meta.status}")
            return

        if args.cmd == "reject":
            reject_agent(args.name, base_url=args.url, actor=args.actor)
            print(f"rejected/removed {args.name}")
            return
    except HubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        for issue in exc.issues:
            print(f"  - {issue}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
