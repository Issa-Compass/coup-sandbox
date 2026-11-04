"""Income turtle: Tax if Duke, else Income; Coup when forced."""

from __future__ import annotations

import random

from coup.agent_api import (
    Action,
    ActionType,
    Agent,
    Block,
    Card,
    Pass,
    PlayerView,
    Response,
)


class TurtleBot(Agent):
    def __init__(self) -> None:
        self.rng = random.Random()

    def on_game_start(self, view: PlayerView, seed: int) -> None:
        self.rng = random.Random(seed)

    def choose_action(self, view: PlayerView) -> Action:
        legal = list(view.legal_actions)
        if not legal:
            raise RuntimeError("no legal actions")
        if all(a.type is ActionType.COUP for a in legal):
            return max(legal, key=lambda a: (_inf(view, a.target), _coins(view, a.target)))
        me = view.players[view.you]
        coups = [a for a in legal if a.type is ActionType.COUP]
        if coups and me.coins >= 7:
            return max(coups, key=lambda a: (_inf(view, a.target), _coins(view, a.target)))
        if Card.DUKE in view.your_cards:
            for a in legal:
                if a.type is ActionType.TAX:
                    return a
        for a in legal:
            if a.type is ActionType.INCOME:
                return a
        return legal[0]

    def respond_to_action(self, view: PlayerView, action: Action) -> Response:
        if view.phase == "challenge":
            return Pass()
        if view.phase == "block":
            for r in view.legal_responses:
                if isinstance(r, Block) and r.card in view.your_cards:
                    return r
            if (
                action.type is ActionType.ASSASSINATE
                and action.target == view.you
                and view.players[view.you].influence == 1
            ):
                for r in view.legal_responses:
                    if isinstance(r, Block) and r.card is Card.CONTESSA:
                        return r
        return Pass()

    def respond_to_block(self, view: PlayerView, block: Block) -> Response:
        return Pass()

    def choose_card_to_lose(self, view: PlayerView) -> Card:
        return view.your_cards[0]

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...] | list[Card]) -> list[Card]:
        return list(view.your_cards)


def _inf(view: PlayerView, seat: int | None) -> int:
    return 0 if seat is None else view.players[seat].influence


def _coins(view: PlayerView, seat: int | None) -> int:
    return 0 if seat is None else view.players[seat].coins
