"""Mutable hidden state. Never put this object in a PlayerView."""

from __future__ import annotations

from dataclasses import dataclass, field

from coup.agent_api import Card


@dataclass
class Player:
    seat: int
    name: str
    coins: int
    cards: list[Card] = field(default_factory=list)
    revealed: list[Card] = field(default_factory=list)

    @property
    def influence(self) -> int:
        return len(self.cards)

    @property
    def alive(self) -> bool:
        return bool(self.cards)
