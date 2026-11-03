"""Seat every agent the same number of times, at tables of 2 to 6.

When the field is larger than one table, each wave rebalances so agents
share tables as evenly as a poker tournament would — not pure shuffle luck.
"""

from __future__ import annotations

import random
from collections import Counter
from itertools import combinations


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
    """Each wave seats every agent once with balanced opponents.

    Pair meetings (sharing a table) are kept as even as possible across the
    round. Seat order inside each table is still shuffled.
    """

    if len(names) < 2:
        raise ValueError("need at least 2 agents")
    if len(set(names)) != len(names):
        raise ValueError("agent names must be unique")
    if games_per_agent < 1:
        raise ValueError("games_per_agent must be positive")

    rng = random.Random(seed)
    sizes = choose_sizes(len(names), prefer)
    pair_counts: Counter[tuple[str, str]] = Counter()
    tables: list[list[str]] = []

    for _ in range(games_per_agent):
        wave = _balanced_wave(names, sizes, pair_counts, rng)
        for group in wave:
            for left, right in combinations(group, 2):
                pair_counts[_pair_key(left, right)] += 1
            seats = list(group)
            rng.shuffle(seats)
            tables.append(seats)
    return tables


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def _balanced_wave(
    names: list[str],
    sizes: list[int],
    pair_counts: Counter[tuple[str, str]],
    rng: random.Random,
) -> list[list[str]]:
    """Try several seatings; keep the one that adds the least repeat meetings."""

    if len(sizes) == 1:
        order = list(names)
        rng.shuffle(order)
        return [order]

    attempts = max(24, min(120, len(names) * 8))
    best: list[list[str]] | None = None
    best_score: tuple[int, int, int] | None = None
    for _ in range(attempts):
        candidate = _greedy_seat(names, sizes, pair_counts, rng)
        score = _wave_score(candidate, pair_counts)
        if best_score is None or score < best_score:
            best = candidate
            best_score = score
    assert best is not None
    return best


def _greedy_seat(
    names: list[str],
    sizes: list[int],
    pair_counts: Counter[tuple[str, str]],
    rng: random.Random,
) -> list[list[str]]:
    order = list(names)
    rng.shuffle(order)
    tables: list[list[str]] = [[] for _ in sizes]
    for agent in order:
        choices: list[tuple[tuple[int, int, int], int]] = []
        for index, size in enumerate(sizes):
            if len(tables[index]) >= size:
                continue
            cost = sum(pair_counts[_pair_key(agent, other)] for other in tables[index])
            # Prefer empty-ish tables on ties so late agents are not forced into one pile.
            remaining = size - len(tables[index])
            choices.append(((cost, -remaining, rng.random()), index))
        choices.sort(key=lambda item: item[0])
        tables[choices[0][1]].append(agent)
    return tables


def _wave_score(
    tables: list[list[str]],
    pair_counts: Counter[tuple[str, str]],
) -> tuple[int, int, int]:
    """Lower is better: total prior meetings added, then max, then spread."""

    added = 0
    projected_max = 0
    projected_min = None
    touched: list[int] = []
    for group in tables:
        for left, right in combinations(group, 2):
            prior = pair_counts[_pair_key(left, right)]
            nxt = prior + 1
            added += prior
            touched.append(nxt)
            if nxt > projected_max:
                projected_max = nxt
            if projected_min is None or nxt < projected_min:
                projected_min = nxt
    spread = projected_max - (projected_min or 0)
    return (added, projected_max, spread)


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
