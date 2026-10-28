"""Picks uniformly from the legal moves. The easiest baseline to beat."""

import random

from coup.agent_api import Action, Agent, Block, Card, PlayerView, Response


class RandomBot(Agent):
    def __init__(self) -> None:
        self.rng = random.Random()

    def on_game_start(self, view: PlayerView, seed: int) -> None:
        self.rng = random.Random(seed)

    def choose_action(self, view: PlayerView) -> Action:
        return self.rng.choice(list(view.legal_actions))

    def respond_to_action(self, view: PlayerView, action: Action) -> Response:
        return self.rng.choice(list(view.legal_responses))

    def respond_to_block(self, view: PlayerView, block: Block) -> Response:
        return self.rng.choice(list(view.legal_responses))

    def choose_card_to_lose(self, view: PlayerView) -> Card:
        return self.rng.choice(list(view.your_cards))

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...] | list[Card]) -> list[Card]:
        pool = list(view.your_cards) + list(drawn)
        self.rng.shuffle(pool)
        return pool[: len(view.your_cards)]
