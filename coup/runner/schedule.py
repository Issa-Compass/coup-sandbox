"""Seat every agent the same number of times, at tables of 2 to 6."""

from __future__ import annotations

import random


def choose_sizes(player_count: int, prefer: int = 5) -> list[int]:
    """Split ``player_count`` into table sizes.

    A field of 6 or fewer sits at one table. Larger fields prefer sizes 4, 5,
    and 6, and only use 3 or 2 when the count cannot be split otherwise
    (7 players is a table of 4 and a table of 3).
    """

    if player_count < 2:
        raise ValueError("need at least 2 players")
    if not 2 <= prefer <= 6:
        raise ValueError("table size must be between 2 and 6")
    if player_count <= 6:
        return [player_count]
    for allowed in ({4, 5, 6}, {3, 4, 5, 6}, {2, 3, 4, 5, 6}):
        found = _best_split(player_count, allowed, prefer)
        if found is not None:
            return found
    raise RuntimeError(f"cannot seat {player_count} players")


def build_tables(
    names: list[str],
    games_per_agent: int,
    seed: int,
    prefer: int = 5,
) -> list[list[str]]:
    """Each wave seats every agent once. Seat order inside a table is shuffled."""

    if len(names) < 2:
        raise ValueError("need at least 2 agents")
    if len(set(names)) != len(names):
        raise ValueError("agent names must be unique")
    if games_per_agent < 1:
        raise ValueError("games_per_agent must be positive")
    rng = random.Random(seed)
    tables: list[list[str]] = []
    for _ in range(games_per_agent):
        order = list(names)
        rng.shuffle(order)
        index = 0
        for size in choose_sizes(len(order), prefer):
            group = order[index : index + size]
            index += size
            rng.shuffle(group)
            tables.append(group)
    return tables


def _best_split(player_count: int, allowed: set[int], prefer: int) -> list[int] | None:
    best_at: dict[int, list[int]] = {0: []}
    for total in range(player_count):
        sizes = best_at.get(total)
        if sizes is None:
            continue
        for part in sorted(allowed):
            nxt = total + part
            if nxt > player_count:
                continue
            candidate = sizes + [part]
            old = best_at.get(nxt)
            if old is None or _cost(candidate, prefer) < _cost(old, prefer):
                best_at[nxt] = candidate
    return best_at.get(player_count)


def _cost(sizes: list[int], prefer: int) -> tuple[int, int, int]:
    return (
        sum(abs(size - prefer) for size in sizes),
        -sum(size == prefer for size in sizes),
        len(sizes),
    )
