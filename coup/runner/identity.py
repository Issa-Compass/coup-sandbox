"""Opaque public IDs for tournament tables.

Agents only see these IDs in ``PlayerView`` / standings. The same ID sticks for
the whole tournament run so play style can be tracked across games, but a new
run gets a fresh mapping. Organizer logs and leaderboards keep real names.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from coup.agent_api import PreviousRoundWinner

UID_PREFIX = "u_"
UID_HEX_LEN = 6
UIDS_FILE = "player_uids.json"


def new_uid(used: set[str] | None = None) -> str:
    used = used or set()
    while True:
        token = UID_PREFIX + secrets.token_hex(UID_HEX_LEN // 2)
        if token not in used:
            return token


def assign_uids(names: list[str] | tuple[str, ...]) -> dict[str, str]:
    """Fresh real-name → public-id map. IDs are not derived from the names."""

    used: set[str] = set()
    mapping: dict[str, str] = {}
    for name in names:
        if name in mapping:
            continue
        uid = new_uid(used)
        used.add(uid)
        mapping[name] = uid
    return mapping


def load_or_create_uids(run_folder: Path, names: list[str] | tuple[str, ...]) -> dict[str, str]:
    """Reuse ``player_uids.json`` for later rounds of the same run; mint any new seats."""

    path = run_folder / UIDS_FILE
    mapping: dict[str, str] = {}
    if path.is_file():
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            mapping = {str(key): str(value) for key, value in raw.items()}
    used = set(mapping.values())
    changed = False
    for name in names:
        if name in mapping:
            continue
        mapping[name] = new_uid(used)
        used.add(mapping[name])
        changed = True
    if changed or not path.is_file():
        run_folder.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {name: mapping[name] for name in names}


def invert_uids(uids: dict[str, str]) -> dict[str, str]:
    return {public: real for real, public in uids.items()}


def remap_stats(stats: dict[str, dict[str, Any]], uids: dict[str, str]) -> dict[str, dict[str, Any]]:
    remapped: dict[str, dict[str, Any]] = {}
    for real, row in stats.items():
        public = uids.get(real, real)
        copy = dict(row)
        copy["name"] = public
        remapped[public] = copy
    return remapped


def remap_winners(
    winners: tuple[PreviousRoundWinner, ...],
    uids: dict[str, str],
) -> tuple[PreviousRoundWinner, ...]:
    return tuple(
        PreviousRoundWinner(
            round=winner.round,
            name=uids.get(winner.name, winner.name),
            games=winner.games,
            points=winner.points,
            wins=winner.wins,
            avg_points=winner.avg_points,
        )
        for winner in winners
    )


def apply_name_map(text: str, public_to_real: dict[str, str]) -> str:
    """Replace public IDs with real names. Longest keys first to avoid partial swaps."""

    if not public_to_real:
        return text
    result = text
    for public in sorted(public_to_real, key=len, reverse=True):
        result = result.replace(public, public_to_real[public])
    return result
