"""Claims Duke and Assassin often, including when it does not hold them."""

import random

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


class BlufferBot(Agent):
    def __init__(self) -> None:
        self.rng = random.Random()

    def on_game_start(self, view: PlayerView, seed: int) -> None:
        self.rng = random.Random(seed)

    def choose_action(self, view: PlayerView) -> Action:
        legal = list(view.legal_actions)
        coups = [action for action in legal if action.type is ActionType.COUP]
        if coups and all(action.type is ActionType.COUP for action in legal):
            return self.rng.choice(coups)
        roll = self.rng.random()
        assassinations = [action for action in legal if action.type is ActionType.ASSASSINATE]
        if assassinations and roll < 0.45:
            return self.rng.choice(assassinations)
        if roll < 0.75:
            for action in legal:
                if action.type is ActionType.TAX:
                    return action
        noisy = [
            action
            for action in legal
            if action.type
            in (ActionType.INCOME, ActionType.FOREIGN_AID, ActionType.STEAL, ActionType.EXCHANGE, ActionType.TAX)
        ]
        return self.rng.choice(noisy or legal)

    def respond_to_action(self, view: PlayerView, action: Action) -> Response:
        if view.phase == "challenge":
            claim = ACTION_CLAIM.get(action.type)
            if claim is not None and _unseen(view, claim) <= 0:
                return Challenge()
            if self.rng.random() < 0.1:
                return Challenge()
            return Pass()
        blocks = [response for response in view.legal_responses if isinstance(response, Block)]
        if blocks and self.rng.random() < 0.6:
            return self.rng.choice(blocks)
        return Pass()

    def respond_to_block(self, view: PlayerView, block: Block) -> Response:
        if _unseen(view, block.card) <= 0 or self.rng.random() < 0.15:
            return Challenge()
        return Pass()

    def choose_card_to_lose(self, view: PlayerView) -> Card:
        return self.rng.choice(list(view.your_cards))

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...] | list[Card]) -> list[Card]:
        pool = list(view.your_cards) + list(drawn)
        self.rng.shuffle(pool)
        return pool[: len(view.your_cards)]


def _unseen(view: PlayerView, card: Card) -> int:
    in_hand = sum(held is card for held in view.your_cards)
    revealed = sum(shown is card for player in view.players for shown in player.revealed)
    return view.copies_per_card - in_hand - revealed
