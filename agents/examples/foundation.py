"""Shared Coup policy for the example ladder bots.

Hard floors every personality inherits (so they stop free-dying):
- card-count: challenge only when the claim is impossible, or soft enough
- last-life Contessa vs Assassinate (bluff if Contessa is still possible)
- truthful blocks when holding the card
- Coup at 10; prefer Coup at 7+ into 1-influence / coin threats
- sane lose / exchange ranks

`Tendencies` knobs keep the ladder distinct without reintroducing suicide.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from coup.agent_api import (
    ACTION_CLAIM,
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

_LOSE_RANK = {
    Card.AMBASSADOR: 0,
    Card.CONTESSA: 1,
    Card.CAPTAIN: 2,
    Card.ASSASSIN: 3,
    Card.DUKE: 4,
}

_EXCHANGE_RANK = {
    Card.DUKE: 0,
    Card.ASSASSIN: 1,
    Card.CAPTAIN: 2,
    Card.CONTESSA: 3,
    Card.AMBASSADOR: 4,
}


@dataclass(frozen=True)
class Tendencies:
    """Personality overlay on the shared floors."""

    # Challenge: impossible claims always. Speculative if P(true) < challenge_p_max.
    challenge_only_impossible: bool = False
    challenge_p_max: float = 0.18
    # Extra random challenge chance after floors (bluffer / noisy random).
    challenge_noise: float = 0.0
    # Speculative challenges need 2 influence unless the claim is high-stakes.
    spare_life_for_speculate: bool = True

    # Action bluffs (0–1). Honest keeps these low; bluffer pushes them up.
    bluff_tax: float = 0.0
    bluff_assassinate: float = 0.0
    bluff_steal: float = 0.0
    bluff_exchange: float = 0.0

    # Last-life Contessa vs Assassinate (survival). Honest and the ladder keep this on.
    survival_contessa_bluff: bool = True
    # Block bluffs beyond last-life Contessa floor.
    bluff_block_contessa_at_two: float = 0.0
    bluff_block_steal: float = 0.0
    bluff_block_duke_fa: float = 0.0

    # After policy picks a preferred action, sometimes pick uniform legal instead.
    action_noise: float = 0.0
    # Among responses, sometimes ignore policy and pick uniform legal (after floors).
    response_noise: float = 0.0

    # Coup earlier when someone is racing coins.
    coup_lead_coins: int = 6


class FoundationBot(Agent):
    """Base policy. Subclasses set ``TENDENCIES`` only."""

    TENDENCIES: Tendencies = Tendencies()

    def __init__(self) -> None:
        self.rng = random.Random()
        self.t = self.TENDENCIES

    def on_game_start(self, view: PlayerView, seed: int) -> None:
        self.rng = random.Random(seed)
        self.t = self.TENDENCIES

    def choose_action(self, view: PlayerView) -> Action:
        legal = list(view.legal_actions)
        if not legal:
            raise RuntimeError("no legal actions")

        if self.t.action_noise > 0 and self.rng.random() < self.t.action_noise:
            return self.rng.choice(legal)

        if all(action.type is ActionType.COUP for action in legal):
            return _best_target(view, legal)

        me = view.players[view.you]
        living = [p for p in view.players if p.influence > 0 and p.seat != view.you]
        coups = [a for a in legal if a.type is ActionType.COUP]

        if coups and me.coins >= 7:
            one_life = [a for a in coups if _influence(view, a.target) == 1]
            if one_life:
                return _best_target(view, one_life)
            leader = max((p.coins for p in living), default=0)
            if me.coins >= 8 or leader >= self.t.coup_lead_coins or len(living) <= 2:
                return _best_target(view, coups)

        if _holds(view, Card.ASSASSIN):
            kills = [
                a
                for a in legal
                if a.type is ActionType.ASSASSINATE and _influence(view, a.target) == 1
            ]
            kills = [a for a in kills if not _contessa_proven(view, a.target)]
            if kills:
                return _best_target(view, kills)

        if _holds(view, Card.DUKE):
            for a in legal:
                if a.type is ActionType.TAX:
                    return a

        if _holds(view, Card.CAPTAIN):
            steals = [
                a
                for a in legal
                if a.type is ActionType.STEAL and _coins(view, a.target) > 0
            ]
            if steals:
                return max(steals, key=lambda a: _coins(view, a.target))

        if _holds(view, Card.AMBASSADOR) and _want_exchange(view):
            for a in legal:
                if a.type is ActionType.EXCHANGE:
                    return a

        # Selective bluffs (personality).
        if (
            not _holds(view, Card.DUKE)
            and _unseen(view, Card.DUKE) > 0
            and me.coins < 7
            and self._roll(self.t.bluff_tax)
            and (me.influence >= 2 or len(living) <= 2)
        ):
            for a in legal:
                if a.type is ActionType.TAX:
                    return a

        if (
            not _holds(view, Card.ASSASSIN)
            and _unseen(view, Card.ASSASSIN) > 0
            and me.coins >= 3
            and me.influence >= 2
            and self._roll(self.t.bluff_assassinate)
        ):
            kills = [
                a
                for a in legal
                if a.type is ActionType.ASSASSINATE
                and _influence(view, a.target) == 1
                and _unseen(view, Card.CONTESSA) <= 1
            ]
            if kills:
                return _best_target(view, kills)

        if (
            not _holds(view, Card.CAPTAIN)
            and _unseen(view, Card.CAPTAIN) > 0
            and self._roll(self.t.bluff_steal)
        ):
            steals = [
                a
                for a in legal
                if a.type is ActionType.STEAL and _coins(view, a.target) > 0
            ]
            if steals and me.influence >= 2:
                return max(steals, key=lambda a: _coins(view, a.target))

        if (
            not _holds(view, Card.AMBASSADOR)
            and _unseen(view, Card.AMBASSADOR) > 0
            and self._roll(self.t.bluff_exchange)
            and me.influence >= 2
        ):
            for a in legal:
                if a.type is ActionType.EXCHANGE:
                    return a

        if coups and me.coins >= 7:
            return _best_target(view, coups)

        for a in legal:
            if a.type is ActionType.FOREIGN_AID and _unseen(view, Card.DUKE) <= 1:
                return a
        for a in legal:
            if a.type is ActionType.FOREIGN_AID:
                return a
        for a in legal:
            if a.type is ActionType.INCOME:
                return a
        return legal[0]

    def respond_to_action(self, view: PlayerView, action: Action) -> Response:
        if view.phase == "challenge":
            return self._challenge_action(view, action)
        if view.phase == "block":
            return self._choose_block(view, action)
        return Pass()

    def respond_to_block(self, view: PlayerView, block: Block) -> Response:
        if Challenge() not in view.legal_responses or block.seat is None:
            return Pass()
        if _impossible(view, block.card):
            return Challenge()
        if self.t.challenge_only_impossible:
            return Pass()

        me = view.players[view.you]
        p_true = _claim_probability(view, block.seat, block.card)
        acting = view.actor == view.you
        high_stakes = acting and view.action is not None and view.action.type in (
            ActionType.ASSASSINATE,
            ActionType.STEAL,
        )

        if self._should_speculate(me.influence, p_true, high_stakes):
            return Challenge()
        if self.t.challenge_noise > 0 and self.rng.random() < self.t.challenge_noise:
            if me.influence >= 2 or high_stakes:
                return Challenge()
        return Pass()

    def choose_card_to_lose(self, view: PlayerView) -> Card:
        if not view.your_cards:
            raise RuntimeError("no card to lose")
        rank = dict(_LOSE_RANK)
        if _unseen(view, Card.ASSASSIN) > 0:
            rank[Card.CONTESSA] = 5
        return min(
            view.your_cards,
            key=lambda card: (-view.your_cards.count(card), rank[card]),
        )

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...] | list[Card]) -> list[Card]:
        pool = list(view.your_cards) + list(drawn)
        need = len(view.your_cards)
        rank = dict(_EXCHANGE_RANK)
        if view.players[view.you].influence == 1:
            rank[Card.CONTESSA] = 0
            rank[Card.DUKE] = 1
        pool.sort(key=lambda card: rank[card])
        return pool[:need]

    def _challenge_action(self, view: PlayerView, action: Action) -> Response:
        claim = ACTION_CLAIM.get(action.type)
        if claim is None or view.actor is None or Challenge() not in view.legal_responses:
            return Pass()
        if _impossible(view, claim):
            return Challenge()
        if self.t.challenge_only_impossible:
            return Pass()

        me = view.players[view.you]
        p_true = _claim_probability(view, view.actor, claim)
        high_stakes = (
            action.type is ActionType.ASSASSINATE and action.target == view.you
        ) or _coins(view, view.actor) >= self.t.coup_lead_coins

        # Prefer Contessa path over speculative Assassin challenges on us.
        if action.type is ActionType.ASSASSINATE and action.target == view.you:
            can_contessa = Card.CONTESSA in view.your_cards or _unseen(view, Card.CONTESSA) > 0
            if can_contessa and p_true >= 0.22:
                return Pass()

        if self._should_speculate(me.influence, p_true, high_stakes):
            return Challenge()
        if self.t.challenge_noise > 0 and self.rng.random() < self.t.challenge_noise:
            if me.influence >= 2 or high_stakes:
                return Challenge()
        return Pass()

    def _choose_block(self, view: PlayerView, action: Action) -> Response:
        blocks = [r for r in view.legal_responses if isinstance(r, Block)]
        if not blocks:
            return Pass()

        if self.t.response_noise > 0 and self.rng.random() < self.t.response_noise:
            # Survival floor still applies before noise.
            survival = self._survival_contessa(view, action, blocks)
            if survival is not None:
                return survival
            return self.rng.choice(list(view.legal_responses))

        for block in blocks:
            if block.card in view.your_cards:
                return block

        survival = self._survival_contessa(view, action, blocks)
        if survival is not None:
            return survival

        me = view.players[view.you]

        if action.type is ActionType.ASSASSINATE and action.target == view.you:
            contessa = [b for b in blocks if b.card is Card.CONTESSA]
            if (
                contessa
                and not _impossible(view, Card.CONTESSA)
                and self._roll(self.t.bluff_block_contessa_at_two)
                and me.influence >= 2
            ):
                return contessa[0]

        if action.type is ActionType.STEAL and action.target == view.you and me.coins > 0:
            steal_blocks = [b for b in blocks if b.card in (Card.CAPTAIN, Card.AMBASSADOR)]
            if steal_blocks and not _impossible(view, steal_blocks[0].card) and self._roll(
                self.t.bluff_block_steal
            ):
                steal_blocks.sort(key=lambda b: 0 if b.card is Card.CAPTAIN else 1)
                if me.influence >= 2 or me.coins >= 4:
                    return steal_blocks[0]

        if action.type is ActionType.FOREIGN_AID:
            duke = [b for b in blocks if b.card is Card.DUKE]
            if (
                duke
                and not _impossible(view, Card.DUKE)
                and self._roll(self.t.bluff_block_duke_fa)
                and view.actor is not None
                and _coins(view, view.actor) >= 5
                and me.influence >= 2
            ):
                return duke[0]

        return Pass()

    def _survival_contessa(
        self, view: PlayerView, action: Action, blocks: list[Block]
    ) -> Response | None:
        if action.type is not ActionType.ASSASSINATE or action.target != view.you:
            return None
        if not self.t.survival_contessa_bluff:
            return None
        if view.players[view.you].influence != 1:
            return None
        contessa = [b for b in blocks if b.card is Card.CONTESSA]
        if contessa and not _impossible(view, Card.CONTESSA):
            return contessa[0]
        return None

    def _should_speculate(self, influence: int, p_true: float, high_stakes: bool) -> bool:
        if p_true >= self.t.challenge_p_max:
            # High-stakes: slightly looser bar (still well below coin-flip).
            if high_stakes and p_true < min(0.35, self.t.challenge_p_max + 0.12):
                return influence >= 2 or high_stakes
            return False
        if self.t.spare_life_for_speculate and influence < 2 and not high_stakes:
            return False
        return True

    def _roll(self, rate: float) -> bool:
        if rate <= 0:
            return False
        if rate >= 1:
            return True
        return self.rng.random() < rate


def _holds(view: PlayerView, card: Card) -> bool:
    return card in view.your_cards


def _influence(view: PlayerView, seat: int | None) -> int:
    if seat is None:
        return 0
    return view.players[seat].influence


def _coins(view: PlayerView, seat: int | None) -> int:
    if seat is None:
        return 0
    return view.players[seat].coins


def _unseen(view: PlayerView, card: Card) -> int:
    in_hand = sum(held is card for held in view.your_cards)
    revealed = sum(shown is card for player in view.players for shown in player.revealed)
    return view.copies_per_card - in_hand - revealed


def _unseen_total(view: PlayerView) -> int:
    revealed = sum(len(player.revealed) for player in view.players)
    return view.total_cards - len(view.your_cards) - revealed


def _impossible(view: PlayerView, card: Card) -> bool:
    return _unseen(view, card) <= 0


def _claim_probability(view: PlayerView, claimer: int, card: Card) -> float:
    copies = _unseen(view, card)
    unseen = _unseen_total(view)
    hand = view.players[claimer].influence
    if hand <= 0 or copies <= 0 or hand > unseen:
        return 0.0
    if copies >= unseen:
        return 1.0
    other = unseen - copies
    if other < hand:
        return 1.0
    return 1.0 - math.comb(other, hand) / math.comb(unseen, hand)


def _best_target(view: PlayerView, actions: list[Action]) -> Action:
    def key(action: Action) -> tuple:
        inf = _influence(view, action.target)
        coins = _coins(view, action.target)
        return (1 if inf == 1 else 0, coins, inf)

    return max(actions, key=key)


def _want_exchange(view: PlayerView) -> bool:
    cards = view.your_cards
    if Card.DUKE in cards:
        return False
    useful = {Card.DUKE, Card.CAPTAIN, Card.ASSASSIN, Card.CONTESSA}
    return not any(c in useful for c in cards)


def _contessa_proven(view: PlayerView, seat: int | None) -> bool:
    if seat is None:
        return False
    for event in view.history:
        if event.type == "prove" and event.seat == seat and event.card is Card.CONTESSA:
            return True
        if event.type == "block" and event.seat == seat and event.card is Card.CONTESSA:
            return True
    return False
