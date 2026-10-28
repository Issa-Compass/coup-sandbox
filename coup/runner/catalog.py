"""Locate example agents and candidate submissions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = {
    "template": ROOT / "agents" / "template" / "agent.py",
    "random": ROOT / "agents" / "examples" / "random_bot.py",
    "honest": ROOT / "agents" / "examples" / "honest_bot.py",
    "bluffer": ROOT / "agents" / "examples" / "bluffer_bot.py",
    "challenger": ROOT / "agents" / "examples" / "challenger_bot.py",
}
SUBMISSIONS = ROOT / "agents" / "submissions"


def resolve_agent(token: str) -> Path:
    if token in EXAMPLES:
        return EXAMPLES[token]
    submission = SUBMISSIONS / token / "agent.py"
    if submission.is_file():
        return submission
    path = Path(token)
    if not path.is_file():
        path = ROOT / token
    if not path.is_file():
        known = ", ".join(sorted(EXAMPLES))
        raise FileNotFoundError(f"no agent {token!r}. Use a path or one of: {known}")
    return path


def submission_agents() -> list[Path]:
    if not SUBMISSIONS.is_dir():
        return []
    return sorted(path for path in SUBMISSIONS.glob("*/agent.py") if path.is_file())


def safe_branch_name(branch: str) -> str | None:
    """Return the agent name from ``origin/agent/<name>``, or None."""

    text = branch.strip()
    marker = "/agent/"
    if marker not in text:
        if text.startswith("agent/"):
            name = text.split("/", 1)[1]
        else:
            return None
    else:
        name = text.split(marker, 1)[1]
    name = name.strip().strip("/")
    if not name or "/" in name or name in {".", ".."}:
        return None
    return name
