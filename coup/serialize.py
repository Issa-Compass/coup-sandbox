"""JSON conversion for the agent sandbox protocol. Not part of the agent API."""

from __future__ import annotations

from typing import Any

from coup.agent_api import (
    Action,
    ActionType,
    Block,
    Card,
    Challenge,
    Event,
    GameResult,
    Pass,
    Placement,
    PlayerView,
    PreviousRoundWinner,
    PublicPlayer,
    StandingRow,
    StandingsScope,
    StandingsSnapshot,
)

ENUMS = {"Card": Card, "ActionType": ActionType, "StandingsScope": StandingsScope}
DATACLASSES = {
    "Action": Action,
    "Block": Block,
    "Pass": Pass,
    "Challenge": Challenge,
    "Event": Event,
    "PublicPlayer": PublicPlayer,
    "PlayerView": PlayerView,
    "Placement": Placement,
    "GameResult": GameResult,
    "StandingRow": StandingRow,
    "PreviousRoundWinner": PreviousRoundWinner,
    "StandingsSnapshot": StandingsSnapshot,
}
TUPLE_FIELDS = {
    "revealed",
    "players",
    "your_cards",
    "history",
    "legal_actions",
    "legal_responses",
    "drawn",
    "placements",
    "table",
    "round_rows",
    "tournament_rows",
    "previous_round_winners",
}


def to_data(obj: Any) -> Any:
    if hasattr(obj, "value") and obj.__class__.__name__ in ENUMS:
        return {"_enum": obj.__class__.__name__, "value": obj.value}
    type_name = obj.__class__.__name__
    if type_name in DATACLASSES:
        payload: dict[str, Any] = {"_type": type_name}
        for key, value in vars(obj).items():
            payload[key] = to_data(value)
        return payload
    if isinstance(obj, tuple | list):
        return [to_data(item) for item in obj]
    if isinstance(obj, str | int | float | bool) or obj is None:
        return obj
    raise TypeError(f"cannot serialize {type(obj)!r}")


def from_data(data: Any) -> Any:
    if isinstance(data, list):
        return [from_data(item) for item in data]
    if not isinstance(data, dict):
        return data
    if "_enum" in data:
        enum = ENUMS.get(data["_enum"])
        if enum is None:
            raise ValueError(f"unknown enum {data['_enum']}")
        return enum(data["value"])
    if "_type" not in data:
        return {key: from_data(value) for key, value in data.items()}
    cls = DATACLASSES.get(data["_type"])
    if cls is None:
        raise ValueError(f"unknown type {data['_type']}")
    kwargs = {}
    for key, value in data.items():
        if key == "_type":
            continue
        loaded = from_data(value)
        if key in TUPLE_FIELDS:
            loaded = tuple(loaded)
        kwargs[key] = loaded
    return cls(**kwargs)
