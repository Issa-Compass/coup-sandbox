"""Plays like HonestBot, but challenges claims that are unlikely to be true."""

import math

from coup.agent_api import ACTION_CLAIM, Action, Agent, Block, Card, Challenge, Pass, PlayerView, Response

from agents.examples.honest_bot import HonestBot, _impossible


class ChallengerBot(HonestBot):
    """One Agent subclass. HonestBot is the parent, not a second entry point."""

    def respond_to_action(self, view: PlayerView, action: Action) -> Response:
        if view.phase == "challenge":
            claim = ACTION_CLAIM.get(action.type)
            if claim is not None and view.actor is not None and _unlikely(view, view.actor, claim):
                return Challenge()
            return Pass()
        return super().respond_to_action(view, action)

    def respond_to_block(self, view: PlayerView, block: Block) -> Response:
        if block.seat is None:
            return Pass()
        if _unlikely(view, block.seat, block.card):
            return Challenge()
        return Pass()


def _unlikely(view: PlayerView, claimer: int, card: Card) -> bool:
    if _impossible(view, card):
        return True
    copies = _copies_unseen(view, card)
    unseen = _unseen_total(view)
    hand = view.players[claimer].influence
    if hand <= 0 or copies <= 0 or hand > unseen:
        return True
    if copies >= unseen:
        return False
    other = unseen - copies
    if other < hand:
        return False
    probability = 1.0 - math.comb(other, hand) / math.comb(unseen, hand)
    return probability < 0.5


def _copies_unseen(view: PlayerView, card: Card) -> int:
    in_hand = sum(held is card for held in view.your_cards)
    revealed = sum(shown is card for player in view.players for shown in player.revealed)
    return view.copies_per_card - in_hand - revealed


def _unseen_total(view: PlayerView) -> int:
    revealed = sum(len(player.revealed) for player in view.players)
    return view.total_cards - len(view.your_cards) - revealed
