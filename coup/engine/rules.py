"""Legality helpers. The game object is the authority; these are pure checks."""

from __future__ import annotations

from collections import Counter

from coup.agent_api import (
    ACTION_BLOCK,
    ACTION_CLAIM,
    ACTION_COST,
    MUST_COUP_AT,
    STARTING_COINS,
    TWO_PLAYER_STARTING_COINS,
    Action,
    ActionType,
    Block,
    Card,
    Challenge,
    Pass,
    Response,
)


def placement_points(place: int, player_count: int) -> int:
    """1st gets ``n``. Later place ``p`` gets ``max(n - p - 1, 0)``.

    A 6-player table is 6, 3, 2, 1, 0, 0. Smaller tables use the same formula.
    """

    if place == 1:
        return player_count
    return max(player_count - place - 1, 0)


def starting_coins(player_count: int) -> int:
    if player_count == 2:
        return TWO_PLAYER_STARTING_COINS
    return STARTING_COINS


def legal_actions(coins: int, opponents: list[int]) -> list[Action]:
    """``opponents`` are the other living seats, in the order a Coup should offer them."""

    if not opponents:
        return []
    if coins >= MUST_COUP_AT:
        return [Action(ActionType.COUP, target) for target in opponents]
    actions = [
        Action(ActionType.INCOME),
        Action(ActionType.FOREIGN_AID),
        Action(ActionType.TAX),
    ]
    if coins >= ACTION_COST[ActionType.COUP]:
        actions.extend(Action(ActionType.COUP, target) for target in opponents)
    if coins >= ACTION_COST[ActionType.ASSASSINATE]:
        actions.extend(Action(ActionType.ASSASSINATE, target) for target in opponents)
    actions.extend(Action(ActionType.STEAL, target) for target in opponents)
    actions.append(Action(ActionType.EXCHANGE))
    return actions


def legal_block_cards(action: Action) -> tuple[Card, ...]:
    return ACTION_BLOCK.get(action.type, ())


def claim_of(action: Action) -> Card | None:
    return ACTION_CLAIM.get(action.type)


def response_is_legal(response: Response, legal: tuple[Response, ...]) -> bool:
    if isinstance(response, Pass):
        return any(isinstance(item, Pass) for item in legal)
    if isinstance(response, Challenge):
        return any(isinstance(item, Challenge) for item in legal)
    if isinstance(response, Block):
        return any(isinstance(item, Block) and item.card is response.card for item in legal)
    return False


def exchange_keep_is_legal(keep: list[Card], pool: list[Card], need: int) -> bool:
    if len(keep) != need:
        return False
    pool_counts = Counter(pool)
    keep_counts = Counter(keep)
    return all(count <= pool_counts[card] for card, count in keep_counts.items())


def cards_returned(pool: list[Card], keep: list[Card]) -> list[Card]:
    counts = Counter(pool)
    counts.subtract(Counter(keep))
    returned: list[Card] = []
    for card, count in counts.items():
        if count < 0:
            raise ValueError("keep is not a subset of the pool")
        returned.extend([card] * count)
    return returned
