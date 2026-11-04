"""Anti-greedy Cap guard — small scripted exploit of never-callers.

Greedy: Tax if Duke, Steal if Cap or 2-life, else FA; Cap/Amb-blocks Steals;
never challenges; Coups at 7; Contessa-bluffs Assassinate at 1 life.

Exploit:
- Tax every turn (they never call Duke) until Coup.
- Do not Steal-spam into Cap/Amb walls — one Cap-fish after they Taxed, else Tax.
- Cap/Amb-block their Steals (they never call our block).
- Call Cap blocks after a Duke Tax; Pass Amb (often real after Duke).
- Call Contessa blocks from quiet seats (their 1-life Contessa is a bluff).
"""

from __future__ import annotations

import random

from coup.agent_api import (
    Action,
    ActionType,
    Agent,
    Block,
    Card,
    Challenge,
    Pass,
    PlayerView,
    Response,
)


class GuardBot(Agent):
    def __init__(self) -> None:
        self.rng = random.Random()

    def on_game_start(self, view: PlayerView, seed: int) -> None:
        self.rng = random.Random(seed)

    def choose_action(self, view: PlayerView) -> Action:
        legal = list(view.legal_actions)
        if not legal:
            raise RuntimeError("no legal actions")
        if all(a.type is ActionType.COUP for a in legal):
            return _best_coup(view, legal)

        me = view.players[view.you]
        coups = [a for a in legal if a.type is ActionType.COUP]
        if coups and me.coins >= 7:
            return _best_coup(view, coups)

        soft = _soft_seats(view)
        locked = _blocked_our_steal(view)

        # One Cap probe into a Duke never-caller who has not Cap-blocked yet.
        fish = [
            a
            for a in legal
            if a.type is ActionType.STEAL
            and a.target in soft
            and a.target not in locked
            and _coins(view, a.target) > 0
            and _cap_blocks(view, a.target) == 0
            and _claimed(view, a.target, Card.DUKE)
        ]
        if fish:
            return max(fish, key=lambda a: _coins(view, a.target))

        # Soft table / steallock → Tax race (Duke is free).
        if soft or locked:
            for a in legal:
                if a.type is ActionType.TAX:
                    return a

        steals = [
            a
            for a in legal
            if a.type is ActionType.STEAL
            and a.target is not None
            and _coins(view, a.target) > 0
            and a.target not in locked
        ]
        if steals and not soft:
            return max(steals, key=lambda a: _coins(view, a.target))

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
        if view.phase != "block":
            return Pass()
        # Always Cap/Amb-block Steals on us — soft thieves never call.
        if action.type is ActionType.STEAL and action.target == view.you:
            for card in (Card.CAPTAIN, Card.AMBASSADOR):
                for r in view.legal_responses:
                    if isinstance(r, Block) and r.card is card:
                        return r
        for r in view.legal_responses:
            if isinstance(r, Block) and r.card in view.your_cards:
                return r
        return Pass()

    def respond_to_block(self, view: PlayerView, block: Block) -> Response:
        if Challenge() not in view.legal_responses or block.seat is None:
            return Pass()
        if _impossible(view, block.card):
            return Challenge()
        quiet = _challenges(view, block.seat) == 0
        # Greedy Contessa-bluffs Assassinate at 1 life — always call quiet Contessa.
        if block.card is Card.CONTESSA and quiet:
            return Challenge()
        if block.card is Card.AMBASSADOR:
            return Pass()
        # Cap after Duke Tax ⇒ other card often not Cap. Call quiet Cap.
        if (
            block.card is Card.CAPTAIN
            and quiet
            and (_claimed(view, block.seat, Card.DUKE) or _cap_blocks(view, block.seat) >= 1)
        ):
            return Challenge()
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


def _best_coup(view: PlayerView, coups: list[Action]) -> Action:
    soft = _soft_seats(view)
    prefer = [a for a in coups if a.target in soft]
    pool = prefer or coups
    return max(pool, key=lambda a: (_inf(view, a.target), _coins(view, a.target)))


def _inf(view: PlayerView, seat: int | None) -> int:
    return 0 if seat is None else view.players[seat].influence


def _coins(view: PlayerView, seat: int | None) -> int:
    return 0 if seat is None else view.players[seat].coins


def _soft_seats(view: PlayerView) -> set[int]:
    """Alive never-challengers who already Taxed, Stole, or Cap/Amb-blocked."""
    me = view.you
    out: set[int] = set()
    for seat, player in enumerate(view.players):
        if seat == me or player.influence <= 0:
            continue
        if _challenges(view, seat) > 0:
            continue
        taxed = _claimed(view, seat, Card.DUKE)
        stole = any(
            e.type == "action" and e.seat == seat and e.action == ActionType.STEAL.value
            for e in view.history
        )
        blocked = _cap_blocks(view, seat) + _amb_blocks(view, seat) > 0
        if taxed or stole or blocked:
            out.add(seat)
    return out


def _blocked_our_steal(view: PlayerView) -> set[int]:
    locked: set[int] = set()
    me = view.you
    hist = view.history
    for i, ev in enumerate(hist):
        if not (
            ev.type == "action"
            and ev.seat == me
            and ev.action == ActionType.STEAL.value
            and ev.target is not None
        ):
            continue
        for j in range(i + 1, len(hist)):
            b = hist[j]
            if b.turn != ev.turn:
                break
            if not (
                b.type == "block"
                and b.action == ActionType.STEAL.value
                and b.card in (Card.CAPTAIN, Card.AMBASSADOR)
                and b.seat is not None
            ):
                continue
            beaten = any(
                ch.type == "challenge"
                and ch.turn == ev.turn
                and ch.claimer == b.seat
                and ch.success is True
                for ch in hist[j + 1 :]
            )
            if not beaten:
                locked.add(b.seat)
            break
    return locked


def _challenges(view: PlayerView, seat: int) -> int:
    return sum(1 for e in view.history if e.type == "challenge" and e.challenger == seat)


def _cap_blocks(view: PlayerView, seat: int) -> int:
    return sum(
        1
        for e in view.history
        if e.type == "block"
        and e.seat == seat
        and e.action == ActionType.STEAL.value
        and e.card is Card.CAPTAIN
    )


def _amb_blocks(view: PlayerView, seat: int) -> int:
    return sum(
        1
        for e in view.history
        if e.type == "block"
        and e.seat == seat
        and e.action == ActionType.STEAL.value
        and e.card is Card.AMBASSADOR
    )


def _claimed(view: PlayerView, seat: int, card: Card) -> bool:
    return any(e.type == "action" and e.seat == seat and e.card is card for e in view.history)


def _impossible(view: PlayerView, card: Card) -> bool:
    shown = sum(1 for p in view.players for c in p.revealed if c is card)
    mine = sum(1 for c in view.your_cards if c is card)
    return shown + mine >= view.copies_per_card
