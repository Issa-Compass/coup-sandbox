"""Copy agents/submissions from origin branches named agent/<name>.

Each candidate works on branch agent/<name> and adds
agents/submissions/<name>/agent.py. This checks those files out into the
current worktree so a round can see every submission at once.

  python scripts/collect_submissions.py
  python scripts/collect_submissions.py --remote upstream
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coup.runner.catalog import safe_branch_name  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect agent/* branches into agents/submissions.")
    parser.add_argument("--remote", default="origin")
    args = parser.parse_args()
    subprocess.check_call(["git", "fetch", args.remote], cwd=ROOT)
    listing = subprocess.check_output(["git", "branch", "-r"], cwd=ROOT, text=True)
    collected = 0
    for line in listing.splitlines():
        ref = line.strip().lstrip("* ").split()[0]
        if not ref.startswith(f"{args.remote}/"):
            continue
        name = safe_branch_name(ref)
        if name is None:
            continue
        branch = ref
        files = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", branch, "agents/submissions"],
            cwd=ROOT,
            text=True,
        )
        paths = [item.strip() for item in files.splitlines() if item.strip()]
        if not paths:
            print(f"skip {branch}: no agents/submissions files")
            continue
        subprocess.check_call(["git", "checkout", branch, "--", *paths], cwd=ROOT)
        print(f"collected {name} ({len(paths)} files)")
        collected += 1
    if collected == 0:
        print("No agent/<name> branches found.")
        sys.exit(1)
    print(f"Collected {collected} branches. Review git status, then run scripts/tournament.py.")


if __name__ == "__main__":
    main()
