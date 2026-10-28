"""Run test_agent.py on submission folders that changed in this push or PR.

Used by GitHub Actions. Locally:

  python scripts/ci_submissions.py
  python scripts/ci_submissions.py agents/submissions/ada/agent.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def submission_dirs(paths: list[str]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for raw in paths:
        path = Path(raw.replace("\\", "/"))
        parts = path.parts
        if len(parts) < 3 or parts[0] != "agents" or parts[1] != "submissions":
            continue
        folder = ROOT / "agents" / "submissions" / parts[2]
        agent = folder / "agent.py"
        if agent.is_file() and folder not in seen:
            seen.add(folder)
            found.append(agent)
    return found


def changed_paths() -> list[str]:
    base = os.environ.get("GITHUB_BASE_REF", "").strip()
    if base:
        subprocess.check_call(["git", "fetch", "origin", base], cwd=ROOT)
        diff = subprocess.check_output(
            ["git", "diff", "--name-only", f"origin/{base}...HEAD"],
            cwd=ROOT,
            text=True,
        )
        return diff.splitlines()
    try:
        diff = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD~1", "HEAD"],
            cwd=ROOT,
            text=True,
        )
    except subprocess.CalledProcessError:
        return []
    return diff.splitlines()


def main() -> None:
    if len(sys.argv) > 1:
        agents = [Path(arg) for arg in sys.argv[1:]]
    else:
        agents = submission_dirs(changed_paths())
    if not agents:
        print("No changed submissions. Skipping agent checks.")
        return
    failed = False
    for agent in agents:
        print(f"== {agent}")
        result = subprocess.run([sys.executable, str(ROOT / "scripts" / "test_agent.py"), str(agent)], cwd=ROOT)
        if result.returncode != 0:
            failed = True
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
