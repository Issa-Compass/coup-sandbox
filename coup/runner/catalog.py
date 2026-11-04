"""Locate example agents, local scratch agents, and on-disk submission cache."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = {
    "template": ROOT / "agents" / "template" / "agent.py",
    "random": ROOT / "agents" / "examples" / "random_bot.py",
    "honest": ROOT / "agents" / "examples" / "honest_bot.py",
    "bluffer": ROOT / "agents" / "examples" / "bluffer_bot.py",
    "challenger": ROOT / "agents" / "examples" / "challenger_bot.py",
    "knife": ROOT / "agents" / "examples" / "knife_bot.py",
    "turtle": ROOT / "agents" / "examples" / "turtle_bot.py",
    "greedy": ROOT / "agents" / "examples" / "greedy_bot.py",
}
LOCAL = ROOT / "agents" / "local"
SUBMISSIONS = ROOT / "agents" / "submissions"

# Arena (hub) ids are namespaced so they never collide with local folder names
# or example aliases. Display name is still the bare hub name. Disk under
# agents/submissions/ is only a download/cache for running — not a catalog source.
ARENA_PREFIX = "arena:"


def arena_agent_id(name: str) -> str:
    return f"{ARENA_PREFIX}{name}"


def is_arena_id(token: str) -> bool:
    return token.startswith(ARENA_PREFIX) and len(token) > len(ARENA_PREFIX)


def arena_name(token: str) -> str | None:
    """Bare arena/hub name from ``arena:<name>``, or None if not an arena id."""

    if not is_arena_id(token):
        return None
    return token[len(ARENA_PREFIX) :]


def display_name_for_token(token: str) -> str:
    """Seat / standings label: bare name for arena ids, otherwise the token."""

    name = arena_name(token)
    return name if name is not None else token


def resolve_agent(token: str) -> Path:
    """Resolve a catalog token to an on-disk ``agent.py``.

    - ``arena:<name>`` → ``agents/submissions/<name>/`` only (never local).
    - bare token → examples, then ``agents/local/``, then ``agents/submissions/``,
      then a filesystem path.
    """

    arena = arena_name(token)
    if arena is not None:
        submission = SUBMISSIONS / arena / "agent.py"
        if submission.is_file():
            return submission
        raise FileNotFoundError(
            f"no arena agent {arena!r} under agents/submissions/ "
            "(download from the hub or pick a local agent)"
        )

    if token in EXAMPLES:
        return EXAMPLES[token]
    local = LOCAL / token / "agent.py"
    if local.is_file():
        return local
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


def _folder_agents(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("*/agent.py") if path.is_file())


def local_agents() -> list[Path]:
    return _folder_agents(LOCAL)


def submission_agents() -> list[Path]:
    return _folder_agents(SUBMISSIONS)


def _catalog_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def list_available_agents() -> list[dict[str, str]]:
    """Agents discoverable from disk: examples and local only.

    Arena / hub entries are merged by the dashboard from coup-master, not from
    ``agents/submissions/``.
    """

    agents: list[dict[str, str]] = []
    for alias, path in EXAMPLES.items():
        if alias == "template" or not path.is_file():
            continue
        agents.append(
            {
                "id": alias,
                "name": path.stem,
                "kind": "example",
                "path": _catalog_path(path),
            }
        )
    for path in local_agents():
        agents.append(
            {
                "id": path.parent.name,
                "name": path.parent.name,
                "kind": "local",
                "path": _catalog_path(path),
            }
        )
    return agents


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
