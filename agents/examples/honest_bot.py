"""Never claims a character it does not hold. Challenges only impossible claims."""

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
    default_action,
)


class HonestBot(Agent):
    def choose_action(self, view: PlayerView) -> Action:
        legal = list(view.legal_actions)
        if legal and all(action.type is ActionType.COUP for action in legal):
            return _best_coup(view, legal)
        if _holds(view, Card.ASSASSIN):
            kills = [
                action
                for action in legal
                if action.type is ActionType.ASSASSINATE and _influence(view, action.target) == 1
            ]
            if kills:
                return kills[0]
        if _holds(view, Card.DUKE):
            for action in legal:
                if action.type is ActionType.TAX:
                    return action
        if _holds(view, Card.CAPTAIN):
            steals = [
                action
                for action in legal
                if action.type is ActionType.STEAL and _coins(view, action.target) > 0
            ]
            if steals:
                return max(steals, key=lambda action: _coins(view, action.target))
        if _holds(view, Card.AMBASSADOR) and not _holds(view, Card.DUKE):
            for action in legal:
                if action.type is ActionType.EXCHANGE:
                    return action
        if _coins(view, view.you) >= 7:
            weak = [
                action
                for action in legal
                if action.type is ActionType.COUP and _influence(view, action.target) == 1
            ]
            if weak:
                return weak[0]
        return default_action(view)

    def respond_to_action(self, view: PlayerView, action: Action) -> Response:
        if view.phase == "challenge":
            claim = ACTION_CLAIM.get(action.type)
            if claim is not None and view.actor is not None and _impossible(view, claim):
                return Challenge()
            return Pass()
        if view.phase == "block":
            for response in view.legal_responses:
                if isinstance(response, Block) and response.card in view.your_cards:
                    return response
        return Pass()

    def respond_to_block(self, view: PlayerView, block: Block) -> Response:
        if _impossible(view, block.card):
            return Challenge()
        return Pass()

    def choose_card_to_lose(self, view: PlayerView) -> Card:
        # Give up the card we have the most duplicates of, Duke last.
        rank = {
            Card.AMBASSADOR: 0,
            Card.CONTESSA: 1,
            Card.CAPTAIN: 2,
            Card.ASSASSIN: 3,
            Card.DUKE: 4,
        }
        return min(view.your_cards, key=lambda card: (-view.your_cards.count(card), rank[card]))

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...] | list[Card]) -> list[Card]:
        pool = list(view.your_cards) + list(drawn)
        rank = {
            Card.DUKE: 0,
            Card.ASSASSIN: 1,
            Card.CAPTAIN: 2,
            Card.CONTESSA: 3,
            Card.AMBASSADOR: 4,
        }
        pool.sort(key=lambda card: rank[card])
        return pool[: len(view.your_cards)]


def _holds(view: PlayerView, card: Card) -> bool:
    return card in view.your_cards


def _player(view: PlayerView, seat: int | None):
    if seat is None:
        raise RuntimeError("missing seat")
    return view.players[seat]


def _influence(view: PlayerView, seat: int | None) -> int:
    return _player(view, seat).influence


def _coins(view: PlayerView, seat: int | None) -> int:
    return _player(view, seat).coins


def _best_coup(view: PlayerView, legal: list[Action]) -> Action:
    return max(legal, key=lambda action: (_influence(view, action.target), _coins(view, action.target)))


def _impossible(view: PlayerView, card: Card) -> bool:
    in_hand = sum(held is card for held in view.your_cards)
    revealed = sum(shown is card for player in view.players for shown in player.revealed)
    return view.copies_per_card - in_hand - revealed <= 0
