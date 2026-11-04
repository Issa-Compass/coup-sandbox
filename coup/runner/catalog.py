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
    "guard": ROOT / "agents" / "examples" / "guard_bot.py",
    "turtle": ROOT / "agents" / "examples" / "turtle_bot.py",
    "greedy": ROOT / "agents" / "examples" / "greedy_bot.py",
}
LOCAL = ROOT / "agents" / "local"
SUBMISSIONS = ROOT / "agents" / "submissions"

# Namespaced catalog ids so local / base / arena never share an id when the
# folder or hub name matches. Display name is still the bare name. Disk under
# agents/submissions/ is only a download/cache for running — not a catalog source.
ARENA_PREFIX = "arena:"
LOCAL_PREFIX = "local:"


def arena_agent_id(name: str) -> str:
    return f"{ARENA_PREFIX}{name}"


def local_agent_id(name: str) -> str:
    return f"{LOCAL_PREFIX}{name}"


def is_arena_id(token: str) -> bool:
    return token.startswith(ARENA_PREFIX) and len(token) > len(ARENA_PREFIX)


def is_local_id(token: str) -> bool:
    return token.startswith(LOCAL_PREFIX) and len(token) > len(LOCAL_PREFIX)


def arena_name(token: str) -> str | None:
    """Bare arena/hub name from ``arena:<name>``, or None if not an arena id."""

    if not is_arena_id(token):
        return None
    return token[len(ARENA_PREFIX) :]


def local_name(token: str) -> str | None:
    """Bare local folder name from ``local:<name>``, or None if not a local id."""

    if not is_local_id(token):
        return None
    return token[len(LOCAL_PREFIX) :]


def catalog_local_id(folder_name: str) -> str:
    """Catalog id for a local folder: ``local:<name>`` when it reuses a base alias."""

    if folder_name in EXAMPLES:
        return local_agent_id(folder_name)
    return folder_name


def display_name_for_token(token: str) -> str:
    """Seat / standings label: bare name for local:/arena: ids, otherwise the token."""

    for extract in (arena_name, local_name):
        name = extract(token)
        if name is not None:
            return name
    return token


def resolve_agent(token: str) -> Path:
    """Resolve a catalog token to an on-disk ``agent.py``.

    - ``arena:<name>`` → ``agents/submissions/<name>/`` only (never local).
    - ``local:<name>`` → ``agents/local/<name>/`` only (never example / submissions).
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

    local_token = local_name(token)
    if local_token is not None:
        local = LOCAL / local_token / "agent.py"
        if local.is_file():
            return local
        raise FileNotFoundError(
            f"no local agent {local_token!r} under agents/local/ "
            "(create agents/local/<name>/agent.py)"
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

    A local folder that reuses a base-set / example alias stays in the catalog
    as ``local:<name>`` so both bots are selectable (unique ids, same display
    name). Arena / hub entries are merged by the dashboard from coup-master,
    not from ``agents/submissions/``.
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
        name = path.parent.name
        agents.append(
            {
                "id": catalog_local_id(name),
                "name": name,
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
