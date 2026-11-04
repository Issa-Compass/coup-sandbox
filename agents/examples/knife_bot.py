"""Assassin hunter: race to 3, knife often (honest or bluff at 2 lives)."""

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


class KnifeBot(Agent):
    def __init__(self) -> None:
        self.rng = random.Random()

    def on_game_start(self, view: PlayerView, seed: int) -> None:
        self.rng = random.Random(seed)

    def choose_action(self, view: PlayerView) -> Action:
        legal = list(view.legal_actions)
        if not legal:
            raise RuntimeError("no legal actions")
        if all(a.type is ActionType.COUP for a in legal):
            return _best_kill(view, legal)

        me = view.players[view.you]
        coups = [a for a in legal if a.type is ActionType.COUP]
        if coups and me.coins >= 7:
            return _best_kill(view, coups)

        kills = [a for a in legal if a.type is ActionType.ASSASSINATE]
        has_assassin = Card.ASSASSIN in view.your_cards
        can_bluff_knife = me.influence >= 2 and _unseen(view, Card.ASSASSIN) > 0
        if kills and me.coins >= 3 and (has_assassin or can_bluff_knife):
            one_life = [a for a in kills if _inf(view, a.target) == 1]
            pool = one_life or kills
            return _best_kill(view, pool)

        if Card.DUKE in view.your_cards:
            for a in legal:
                if a.type is ActionType.TAX:
                    return a

        # Race coins for the next knife — Income over FA (FA invites Duke blocks).
        for a in legal:
            if a.type is ActionType.INCOME:
                return a
        return legal[0]

    def respond_to_action(self, view: PlayerView, action: Action) -> Response:
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
        # Keep Assassin; Contessa only matters on last life.
        order = [Card.AMBASSADOR, Card.CAPTAIN, Card.DUKE, Card.CONTESSA, Card.ASSASSIN]
        if view.players[view.you].influence == 1:
            order = [Card.AMBASSADOR, Card.CAPTAIN, Card.DUKE, Card.ASSASSIN, Card.CONTESSA]
        return min(view.your_cards, key=lambda c: order.index(c) if c in order else 9)

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...] | list[Card]) -> list[Card]:
        pool = list(view.your_cards) + list(drawn)
        need = len(view.your_cards)
        order = [Card.ASSASSIN, Card.DUKE, Card.CONTESSA, Card.CAPTAIN, Card.AMBASSADOR]
        if view.players[view.you].influence == 1:
            order = [Card.CONTESSA, Card.ASSASSIN, Card.DUKE, Card.CAPTAIN, Card.AMBASSADOR]
        pool.sort(key=lambda c: order.index(c) if c in order else 9)
        return pool[:need]


def _inf(view: PlayerView, seat: int | None) -> int:
    return 0 if seat is None else view.players[seat].influence


def _coins(view: PlayerView, seat: int | None) -> int:
    return 0 if seat is None else view.players[seat].coins


def _unseen(view: PlayerView, card: Card) -> int:
    in_hand = sum(held is card for held in view.your_cards)
    revealed = sum(shown is card for player in view.players for shown in player.revealed)
    return view.copies_per_card - in_hand - revealed


def _best_kill(view: PlayerView, actions: list[Action]) -> Action:
    return max(
        actions,
        key=lambda a: (1 if _inf(view, a.target) == 1 else 0, _coins(view, a.target), _inf(view, a.target)),
    )
