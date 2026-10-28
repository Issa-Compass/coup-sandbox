"""Deck construction."""

from __future__ import annotations

from coup.agent_api import Card


def copies_per_card(player_count: int) -> int:
    """Two-player games remove one copy of each character."""

    if player_count == 2:
        return 2
    return 3


def build_deck(player_count: int) -> list[Card]:
    copies = copies_per_card(player_count)
    return [card for card in Card for _ in range(copies)]
