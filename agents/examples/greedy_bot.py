"""FA + Steal economy: Tax if Duke, else Steal / Foreign Aid."""

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


class GreedyBot(Agent):
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
        steals = [
            a
            for a in legal
            if a.type is ActionType.STEAL and a.target is not None and _coins(view, a.target) > 0
        ]
        if steals and (Card.CAPTAIN in view.your_cards or me.influence >= 2):
            return max(steals, key=lambda a: _coins(view, a.target))
        for a in legal:
            if a.type is ActionType.FOREIGN_AID:
                return a
        if Card.ASSASSIN in view.your_cards and me.coins >= 3:
            kills = [
                a
                for a in legal
                if a.type is ActionType.ASSASSINATE and _inf(view, a.target) == 1
            ]
            if kills:
                return kills[0]
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
            if action.type is ActionType.STEAL and action.target == view.you:
                for r in view.legal_responses:
                    if isinstance(r, Block) and r.card is Card.CAPTAIN:
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
        order = [Card.CONTESSA, Card.AMBASSADOR, Card.ASSASSIN, Card.DUKE, Card.CAPTAIN]
        return min(view.your_cards, key=lambda c: order.index(c) if c in order else 9)

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...] | list[Card]) -> list[Card]:
        pool = list(view.your_cards) + list(drawn)
        need = len(view.your_cards)
        order = [Card.CAPTAIN, Card.DUKE, Card.ASSASSIN, Card.AMBASSADOR, Card.CONTESSA]
        pool.sort(key=lambda c: order.index(c) if c in order else 9)
        return pool[:need]


def _inf(view: PlayerView, seat: int | None) -> int:
    return 0 if seat is None else view.players[seat].influence


def _coins(view: PlayerView, seat: int | None) -> int:
    return 0 if seat is None else view.players[seat].coins
