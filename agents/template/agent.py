"""Starting point. Copy this folder to agents/submissions/<your-name>/ and edit it.

The methods below already play legal moves, so `test_agent.py` is green before
you change anything. Replace the bodies with your own policy. Return only
values from `view.legal_actions` or `view.legal_responses`.
"""

from coup.agent_api import (
    Action,
    Agent,
    Block,
    Card,
    GameResult,
    PlayerView,
    Response,
    default_action,
    default_exchange,
    default_loss,
    Pass,
)


class TemplateAgent(Agent):
    def on_game_start(self, view: PlayerView, seed: int) -> None:
        # `seed` is a personal RNG seed. It is not the deck seed.
        # Store anything you want to remember. The tournament process stays
        # up across games unless you crash or time out.
        self.seed = seed

    def on_game_end(self, view: PlayerView, result: GameResult) -> None:
        # `result.place_of(view.you)` is 1 when you won.
        return None

    def choose_action(self, view: PlayerView) -> Action:
        # Your turn. Income is legal unless you have 10+ coins, in which case
        # every legal action is a Coup and this helper plays the first one.
        return default_action(view)

    def respond_to_action(self, view: PlayerView, action: Action) -> Response:
        # phase "challenge": someone claimed a character. Pass or Challenge.
        # phase "block": you may block. Pass, or Block(card) from legal_responses.
        # A Challenge during the block phase is illegal, and the other way around.
        return Pass()

    def respond_to_block(self, view: PlayerView, block: Block) -> Response:
        # `block.card` is the character they claimed. `block.seat` is who.
        return Pass()

    def choose_card_to_lose(self, view: PlayerView) -> Card:
        # Reveal one of your own cards. It stays face up for the rest of the game.
        return default_loss(view)

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...] | list[Card]) -> list[Card]:
        # Return the cards you KEEP, not the ones you put back.
        # len(keep) must equal len(view.your_cards). The pool is your cards plus `drawn`.
        return default_exchange(view)
