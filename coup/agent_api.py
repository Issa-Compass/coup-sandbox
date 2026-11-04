"""Public contract for Coup agents.

Agents may import from this module and nothing else under ``coup``.
The engine calls the methods on ``Agent``. Return the types documented here.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass
from enum import Enum
from typing import Union


class Card(str, Enum):
    DUKE = "duke"
    ASSASSIN = "assassin"
    CAPTAIN = "captain"
    AMBASSADOR = "ambassador"
    CONTESSA = "contessa"


class ActionType(str, Enum):
    INCOME = "income"
    FOREIGN_AID = "foreign_aid"
    COUP = "coup"
    TAX = "tax"
    ASSASSINATE = "assassinate"
    STEAL = "steal"
    EXCHANGE = "exchange"


# A character claim implied by an action. Income, Foreign Aid, and Coup
# claim nothing, so they cannot be challenged.
ACTION_CLAIM: dict[ActionType, Card] = {
    ActionType.TAX: Card.DUKE,
    ActionType.ASSASSINATE: Card.ASSASSIN,
    ActionType.STEAL: Card.CAPTAIN,
    ActionType.EXCHANGE: Card.AMBASSADOR,
}

# Cards that can block an action. Empty means the action cannot be blocked.
ACTION_BLOCK: dict[ActionType, tuple[Card, ...]] = {
    ActionType.FOREIGN_AID: (Card.DUKE,),
    ActionType.ASSASSINATE: (Card.CONTESSA,),
    ActionType.STEAL: (Card.CAPTAIN, Card.AMBASSADOR),
}

# Coins paid when the action is declared. Assassinate and Coup are not refunded.
ACTION_COST: dict[ActionType, int] = {
    ActionType.COUP: 7,
    ActionType.ASSASSINATE: 3,
}

ACTION_LABEL: dict[ActionType, str] = {
    ActionType.INCOME: "Income",
    ActionType.FOREIGN_AID: "Foreign Aid",
    ActionType.COUP: "Coup",
    ActionType.TAX: "Tax",
    ActionType.ASSASSINATE: "Assassinate",
    ActionType.STEAL: "Steal",
    ActionType.EXCHANGE: "Exchange",
}

MUST_COUP_AT = 10
STARTING_COINS = 2
TWO_PLAYER_STARTING_COINS = 1
STEAL_AMOUNT = 2
TURN_CAP = 200


def card_label(card: Card) -> str:
    return card.value.capitalize()


@dataclass(frozen=True)
class Action:
    """A turn action. ``target`` is a seat index, required for Coup, Assassinate, and Steal."""

    type: ActionType
    target: int | None = None


@dataclass(frozen=True)
class Pass:
    """Allow the action or block to stand."""


@dataclass(frozen=True)
class Challenge:
    """Claim the current character claim is a bluff."""


@dataclass(frozen=True)
class Block:
    """Block the current action by claiming ``card``.

    ``seat`` is filled in by the engine when it tells you who blocked.
    When you return a block, set ``card`` only.
    """

    card: Card
    seat: int | None = None


Response = Union[Pass, Challenge, Block]


@dataclass(frozen=True)
class PublicPlayer:
    """One seat as seen by agents.

    ``name`` is the public table id. In a tournament it is an opaque UID that
    stays fixed for the run (so you can track a seat across games) but is not
    the submission folder name. Casual ``play.py`` games use the agent name.
    """

    seat: int
    name: str
    coins: int
    influence: int
    revealed: tuple[Card, ...]


@dataclass(frozen=True)
class Event:
    """One public game event. Hidden cards are never included."""

    type: str
    message: str
    turn: int
    seat: int | None = None
    target: int | None = None
    action: str | None = None
    card: Card | None = None
    challenger: int | None = None
    claimer: int | None = None
    success: bool | None = None
    amount: int | None = None
    coins: int | None = None


@dataclass(frozen=True)
class PlayerView:
    """Everything one player is allowed to see.

    ``your_cards`` are your face-down cards only. Other players' face-down
    cards are not in this object. ``influence`` is how many face-down cards
    they have left. ``revealed`` is the cards they have lost.
    """

    you: int
    phase: str
    turn: int
    actor: int | None
    players: tuple[PublicPlayer, ...]
    your_cards: tuple[Card, ...]
    history: tuple[Event, ...]
    legal_actions: tuple[Action, ...]
    legal_responses: tuple[Response, ...]
    action: Action | None
    block: Block | None
    deck_count: int
    drawn: tuple[Card, ...]
    copies_per_card: int
    total_cards: int


@dataclass(frozen=True)
class Placement:
    seat: int
    name: str
    place: int
    points: int
    influence: int
    coins: int


@dataclass(frozen=True)
class GameResult:
    placements: tuple[Placement, ...]
    turns: int
    capped: bool
    winner: int

    def place_of(self, seat: int) -> int:
        for placement in self.placements:
            if placement.seat == seat:
                return placement.place
        raise KeyError(seat)


class StandingsScope(str, Enum):
    """Scopes for ``query_standings``.

    - ``TABLE``: agents seated at this game, ranked by current-round stats so far
    - ``ROUND``: every agent in the current round, stats from finished games only
    - ``TOURNAMENT``: cumulative across finished prior rounds plus this round so far
    """

    TABLE = "table"
    ROUND = "round"
    TOURNAMENT = "tournament"


@dataclass(frozen=True)
class StandingRow:
    """One agent on a leaderboard snapshot. Rank 1 is best.

    ``name`` is the same public UID used in ``PublicPlayer.name`` for this run.
    """

    rank: int
    name: str
    games: int
    points: int
    wins: int
    avg_points: float
    illegal: int = 0
    errors: int = 0
    timeouts: int = 0


@dataclass(frozen=True)
class PreviousRoundWinner:
    """Top agent of a finished round in this tournament run (same sort as the leaderboard).

    ``name`` is that run's public UID, not the submission folder name.
    """

    round: int
    name: str
    games: int
    points: int
    wins: int
    avg_points: float


@dataclass(frozen=True)
class StandingsSnapshot:
    """Tournament context bound for one game. Prefer ``query_standings`` over reading this.

    ``table`` and every ``name`` field use this run's public UIDs.
    """

    run_id: str
    round: int
    game_index: int
    game_id: str
    table: tuple[str, ...]
    round_rows: tuple[StandingRow, ...]
    tournament_rows: tuple[StandingRow, ...]
    previous_round_winners: tuple[PreviousRoundWinner, ...]


_STANDINGS: contextvars.ContextVar[StandingsSnapshot | None] = contextvars.ContextVar(
    "coup_standings",
    default=None,
)


def bind_standings(snapshot: StandingsSnapshot | None) -> contextvars.Token:
    """Runner/worker only. Agents should call ``query_standings``, not this."""

    return _STANDINGS.set(snapshot)


def reset_standings(token: contextvars.Token) -> None:
    """Runner/worker only. Pair with ``bind_standings``."""

    _STANDINGS.reset(token)


def current_standings() -> StandingsSnapshot | None:
    """Raw snapshot for this game, or ``None`` outside a tournament round."""

    return _STANDINGS.get()


def query_standings(scope: StandingsScope | str = StandingsScope.ROUND) -> tuple[StandingRow, ...] | None:
    """Optional leaderboard read. Returns ``None`` when not in a tournament round.

    Finished games only — the game you are playing is not included yet.
    """

    snapshot = _STANDINGS.get()
    if snapshot is None:
        return None
    if isinstance(scope, str):
        scope = StandingsScope(scope)
    if scope is StandingsScope.ROUND:
        return snapshot.round_rows
    if scope is StandingsScope.TOURNAMENT:
        return snapshot.tournament_rows
    if scope is StandingsScope.TABLE:
        seated = set(snapshot.table)
        filtered = [row for row in snapshot.round_rows if row.name in seated]
        return tuple(
            StandingRow(
                rank=index,
                name=row.name,
                games=row.games,
                points=row.points,
                wins=row.wins,
                avg_points=row.avg_points,
                illegal=row.illegal,
                errors=row.errors,
                timeouts=row.timeouts,
            )
            for index, row in enumerate(filtered, start=1)
        )
    raise ValueError(f"unknown standings scope: {scope!r}")


def query_previous_round_winners() -> tuple[PreviousRoundWinner, ...] | None:
    """Winners of finished rounds in this run, oldest first. ``None`` outside a tournament."""

    snapshot = _STANDINGS.get()
    if snapshot is None:
        return None
    return snapshot.previous_round_winners


def default_action(view: PlayerView) -> Action:
    """Income when it is legal, otherwise the first legal action (a Coup if you must Coup)."""

    for action in view.legal_actions:
        if action.type is ActionType.INCOME:
            return action
    if not view.legal_actions:
        raise RuntimeError("no legal actions")
    return view.legal_actions[0]


def default_loss(view: PlayerView) -> Card:
    if not view.your_cards:
        raise RuntimeError("no card to lose")
    return view.your_cards[0]


def default_exchange(view: PlayerView) -> list[Card]:
    """Keep the cards you already had and return whatever you drew."""

    return list(view.your_cards)


class Agent:
    """Subclass this. Define exactly one subclass in your agent file.

    The engine calls one method at a time and waits for the return value.
    Do not print. Do not read files, the network, or ``coup.engine``.
    """

    def on_game_start(self, view: PlayerView, seed: int) -> None:
        """Called once before the first turn. ``seed`` is only for your RNG."""

    def on_game_end(self, view: PlayerView, result: GameResult) -> None:
        """Called once after the game, including if you were eliminated."""

    def choose_action(self, view: PlayerView) -> Action:
        """Pick a turn action. It must be one of ``view.legal_actions``."""

        return default_action(view)

    def respond_to_action(self, view: PlayerView, action: Action) -> Response:
        """Challenge phase or block phase. Return one of ``view.legal_responses``.

        ``view.phase`` is ``"challenge"`` or ``"block"``. A block returned
        during the challenge phase is illegal. A challenge returned during
        the block phase is illegal.
        """

        return Pass()

    def respond_to_block(self, view: PlayerView, block: Block) -> Response:
        """Someone blocked. Return Pass or Challenge."""

        return Pass()

    def choose_card_to_lose(self, view: PlayerView) -> Card:
        """Reveal one of ``view.your_cards``. It leaves the game face up."""

        return default_loss(view)

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...] | list[Card]) -> list[Card]:
        """Return the cards you KEEP. The length must equal ``len(view.your_cards)``.

        The pool is ``view.your_cards + drawn``. Everything you do not keep
        goes back into the deck. Do not return the discards.
        """

        return default_exchange(view)
