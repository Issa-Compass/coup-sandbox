# Agent API

Import from `coup.agent_api` only.

```python
from coup.agent_api import (
    Action,
    ActionType,
    Agent,
    Block,
    Card,
    Challenge,
    GameResult,
    Pass,
    PlayerView,
    StandingsScope,
    default_action,
    query_previous_round_winners,
    query_standings,
)
```

Define **one** `Agent` subclass in your file. Classes you import from somewhere else do not count. The class must construct with no arguments.

## Cards and actions

`Card` is `DUKE`, `ASSASSIN`, `CAPTAIN`, `AMBASSADOR`, or `CONTESSA`.

`ActionType` is `INCOME`, `FOREIGN_AID`, `COUP`, `TAX`, `ASSASSINATE`, `STEAL`, or `EXCHANGE`.

```python
Action(ActionType.INCOME)
Action(ActionType.FOREIGN_AID)
Action(ActionType.TAX)
Action(ActionType.EXCHANGE)
Action(ActionType.COUP, target=2)
Action(ActionType.ASSASSINATE, target=2)
Action(ActionType.STEAL, target=2)
```

`target` is a seat number. Leave it empty unless the action needs a target. Copy an action out of `view.legal_actions` if you do not want to build one yourself.

Responses:

```python
Pass()
Challenge()
Block(Card.DUKE)          # you are blocking
Block(Card.DUKE, seat=1)  # the engine telling you who blocked
```

These maps are public and match the engine:

- `ACTION_CLAIM` maps Tax, Assassinate, Steal, and Exchange to the card they claim.
- `ACTION_BLOCK` maps Foreign Aid, Assassinate, and Steal to the cards that can block them.
- `ACTION_COST` is 7 for Coup and 3 for Assassinate.
- `MUST_COUP_AT` is 10.
- `ACTION_LABEL` and `card_label` are display strings.

## What the engine calls

```python
class Agent:
    def on_game_start(self, view: PlayerView, seed: int) -> None: ...
    def on_game_end(self, view: PlayerView, result: GameResult) -> None: ...
    def choose_action(self, view: PlayerView) -> Action: ...
    def respond_to_action(self, view: PlayerView, action: Action) -> Pass | Challenge | Block: ...
    def respond_to_block(self, view: PlayerView, block: Block) -> Pass | Challenge: ...
    def choose_card_to_lose(self, view: PlayerView) -> Card: ...
    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...] | list[Card]) -> list[Card]: ...
```

The base class already returns legal defaults. Override what you care about.

`seed` in `on_game_start` is a personal RNG seed. It changes every game and every seat. It does not tell you the deck order. During a tournament your object stays alive from game to game, so you may remember earlier games. `test_agent.py` also reuses your object across its check games.

`on_game_end` runs even if you were eliminated. `result.place_of(view.you)` is your place, starting at 1.

## PlayerView

| Field | Meaning |
| --- | --- |
| `you` | Your seat |
| `phase` | `action`, `challenge`, `block`, `challenge_block`, `lose`, `exchange`, or `done` |
| `turn` | Turn number, starting at 1 |
| `actor` | Seat of the player whose turn it is, once a turn has started |
| `players` | One `PublicPlayer` per seat, including you |
| `your_cards` | Your face-down cards. Nobody else's |
| `history` | Public `Event`s, oldest first |
| `legal_actions` | Actions you may return from `choose_action`. Empty at other times |
| `legal_responses` | What you may return from the respond methods. Empty at other times |
| `action` | The action currently being resolved, if any |
| `block` | The block currently being resolved, if any. `seat` is set |
| `deck_count` | Cards left in the deck |
| `drawn` | Cards you just drew. Only on your exchange decision, otherwise empty |
| `copies_per_card` | 3, or 2 in a two-player game |
| `total_cards` | 15, or 10 in a two-player game |

`PublicPlayer` has `seat`, `name`, `coins`, `influence`, and `revealed`. `influence` is how many face-down cards they have. `revealed` is the cards they have lost, in order. A player is out when `influence` is 0.

In a tournament, `name` is an opaque public UID (`u_` + hex), not the submission folder name. The same UID is reused for that agent across every game and round in the run, so you can track play style without being told who is who. A new tournament run mints new UIDs. Casual `play.py` games still use the agent name.

Always return a value that is equal to one of `legal_actions` or `legal_responses`. A `Block` during the challenge phase is illegal. A `Challenge` during the block phase is illegal. Read `view.phase`.

`respond_to_action` is used for both the challenge phase and the block phase. `respond_to_block` is only "do you challenge this block?".

## Exchange

`choose_exchange` must return the cards you **keep**.

```python
len(keep) == len(view.your_cards)
```

Every card in `keep` has to come from `view.your_cards + list(drawn)`, including duplicates. `default_exchange(view)` keeps your current cards and returns the drawn ones to the deck.

## Losing a card

Return one card from `view.your_cards`. `default_loss(view)` returns the first one.

## Events

Each `Event` has `type`, `message`, `turn`, and whichever of these apply: `seat`, `target`, `action`, `card`, `challenger`, `claimer`, `success`, `amount`, `coins`.

`success` on a challenge event is `True` when the **challenge** worked (the claim was a bluff). Hidden cards never appear in `history`. The human-readable `message` is the same text `scripts/replay.py` prints.

Useful `type` values: `start`, `action`, `challenge`, `prove`, `block`, `lose`, `eliminate`, `coins`, `steal`, `exchange`, `turn_cap`, `winner`.

## GameResult

`placements` is a tuple of `Placement` (`seat`, `name`, `place`, `points`, `influence`, `coins`), best place first. `winner` is the seat in 1st. `turns` is how many turns were played. `capped` is true when the turn limit ended the game.

## Tournament standings (optional)

During a tournament round the runner binds a public standings snapshot for the game you are in. You may read it at any decision (including `on_game_start` / `on_game_end`). Outside a tournament (`scripts/play.py`, the readiness checker) these return `None`.

```python
rows = query_standings(StandingsScope.TABLE)       # this table, current-round stats so far
rows = query_standings(StandingsScope.ROUND)       # whole round so far
rows = query_standings(StandingsScope.TOURNAMENT)  # prior rounds + this round so far
winners = query_previous_round_winners()           # top agent of each finished round
```

Each `StandingRow` has `rank`, `name`, `games`, `points`, `wins`, `avg_points`, plus fault counters (`illegal`, `errors`, `timeouts`). Rank 1 is best (same sort as the published leaderboard). The game in progress is not counted yet. In a tournament, `name` / `table` use the same public UIDs as `PublicPlayer.name` — never the real agent folder names. Organizer leaderboards still show real names.

`current_standings()` returns the raw `StandingsSnapshot` (`run_id`, `round`, `game_index`, `game_id`, `table`, …) when you need metadata. Do not read `results/` files yourself — use these helpers.

## Helpers

- `default_action(view)` returns Income, or the first legal Coup if you must Coup.
- `default_exchange(view)` and `default_loss(view)` are the safe exchange and loss.

## Checker

```powershell
python scripts/test_agent.py agents/submissions/your-name/agent.py
```

`READY` means, across the check games:

- the file imports and defines one `Agent` subclass
- the static import check is clean
- illegal moves, exceptions, and timeouts are all zero

It also prints your win rate against `random`, `honest`, `bluffer`, `challenger`, and a mix. That number does not have to be high for `READY`. It then plays a few games in a separate process, which is how the tournament runs, so an import the static check missed still fails the checker.
