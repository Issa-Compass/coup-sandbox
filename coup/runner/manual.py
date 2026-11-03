"""Step-through game where one seat is a human and the rest are agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from coup.agent_api import (
    ACTION_BLOCK,
    TURN_CAP,
    Action,
    ActionType,
    Block,
    Card,
    Challenge,
    Pass,
    Response,
    card_label,
    default_action,
    default_exchange,
    default_loss,
)
from coup.engine.game import Game
from coup.engine.rules import claim_of
from coup.runner.players import Player
from coup.runner.seeds import personal_seed
from coup.serialize import to_data


HUMAN_NAME = "You"


@dataclass
class ManualSnapshot:
    status: str  # idle | waiting | thinking | finished | error
    human_seat: int
    agents: list[str]
    seed: int
    board: dict[str, Any] | None
    prompt: dict[str, Any] | None
    view: dict[str, Any] | None
    history: list[dict[str, Any]]
    result: dict[str, Any] | None
    error: str | None
    message: str


class ManualGame:
    """One interactive Coup table: human at seat 0, agents after."""

    def __init__(
        self,
        agent_players: list[Player],
        *,
        seed: int,
        max_turns: int = TURN_CAP,
    ) -> None:
        if not agent_players:
            raise ValueError("pick at least 1 agent opponent")
        if len(agent_players) > 5:
            raise ValueError("at most 5 agent opponents (6 seats total)")
        names = [HUMAN_NAME, *[player.public_id for player in agent_players]]
        if len(set(names)) != len(names):
            raise ValueError("player names at a table must be unique")
        self.human_seat = 0
        self.agents = [player.name for player in agent_players]
        self.seed = seed
        self._agent_players = agent_players
        # Seat 0 is human; seats 1..n are agents (index = seat - 1).
        self._players: list[Player | None] = [None, *agent_players]
        self.game = Game(names, seed=seed, max_turns=max_turns)
        self.error: str | None = None
        self._started = False
        self._ended = False

    def start(self) -> ManualSnapshot:
        for seat, player in enumerate(self._players):
            if player is None:
                continue
            player.on_game_start(
                self.game.view_for(seat),
                personal_seed(self.seed, seat, player.name),
            )
        self._started = True
        # Do not auto-play agents here — the client steps them with a delay.
        return self.snapshot()

    def close(self) -> None:
        for player in self._agent_players:
            player.close()

    def submit(self, decision: dict[str, Any]) -> ManualSnapshot:
        if not self._started:
            raise ValueError("game has not started")
        if self.game.finished:
            raise ValueError("game is already finished")
        prompt = self.game.prompt()
        if prompt is None or prompt.seat != self.human_seat:
            raise ValueError("not waiting for your move")
        kind = prompt.kind
        view = self.game.view_for(self.human_seat)
        try:
            if kind == "choose_action":
                action = _parse_action(decision, view.legal_actions)
                self.game.submit_action(action)
            elif kind in ("respond_to_action", "respond_to_block"):
                response = _parse_response(decision, view.legal_responses)
                self.game.submit_reaction(response)
            elif kind == "choose_card_to_lose":
                card = _parse_card(decision.get("card"))
                if card not in view.your_cards:
                    raise ValueError(f"cannot reveal {card}")
                self.game.submit_loss(card)
            elif kind == "choose_exchange":
                keep = [_parse_card(item) for item in decision.get("keep") or []]
                self.game.submit_exchange(keep)
            else:
                raise ValueError(f"unknown prompt {kind}")
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            raise ValueError(str(exc)) from exc
        return self.snapshot()

    def step_agent(self) -> ManualSnapshot:
        """Resolve exactly one agent decision. Used for paced playback in the UI."""

        if not self._started:
            raise ValueError("game has not started")
        if self.game.finished:
            return self.snapshot()
        prompt = self.game.prompt()
        if prompt is None:
            return self.snapshot()
        if prompt.seat == self.human_seat:
            return self.snapshot()
        self._resolve_one_agent(prompt.seat, prompt.kind)
        return self.snapshot()

    def snapshot(self) -> ManualSnapshot:
        if not self._started:
            return ManualSnapshot(
                status="idle",
                human_seat=self.human_seat,
                agents=list(self.agents),
                seed=self.seed,
                board=None,
                prompt=None,
                view=None,
                history=[],
                result=None,
                error=self.error,
                message="Not started",
            )
        board = self._public_board()
        history = [
            {
                "event": event.type,
                "message": event.message,
                "turn": event.turn,
                "seat": event.seat,
                "target": event.target,
                "action": event.action,
                "card": event.card.value if event.card is not None else None,
                "challenger": event.challenger,
                "claimer": event.claimer,
                "success": event.success,
            }
            for event in self.game.history
        ]
        if self.game.finished:
            result = self.game.result()
            if not self._ended:
                self._ended = True
                for seat, player in enumerate(self._players):
                    if player is None:
                        continue
                    player.on_game_end(self.game.view_for(seat), result)
            winner_name = self.game.players[result.winner].name
            return ManualSnapshot(
                status="finished",
                human_seat=self.human_seat,
                agents=list(self.agents),
                seed=self.seed,
                board=board,
                prompt=None,
                view=_view_payload(self.game.view_for(self.human_seat)),
                history=history,
                result={
                    "winner": result.winner,
                    "winner_name": winner_name,
                    "turns": result.turns,
                    "capped": result.capped,
                    "placements": [
                        {
                            "seat": row.seat,
                            "name": row.name,
                            "place": row.place,
                            "points": row.points,
                            "influence": row.influence,
                            "coins": row.coins,
                        }
                        for row in result.placements
                    ],
                },
                error=self.error,
                message=f"Winner: {winner_name}",
            )
        prompt = self.game.prompt()
        human_view = _view_payload(self.game.view_for(self.human_seat))
        if prompt is None:
            return ManualSnapshot(
                status="waiting",
                human_seat=self.human_seat,
                agents=list(self.agents),
                seed=self.seed,
                board=board,
                prompt=None,
                view=human_view,
                history=history,
                result=None,
                error=self.error,
                message="Waiting…",
            )
        if prompt.seat == self.human_seat:
            phase = self.game.phase
            return ManualSnapshot(
                status="waiting",
                human_seat=self.human_seat,
                agents=list(self.agents),
                seed=self.seed,
                board=board,
                prompt={"kind": prompt.kind, "seat": prompt.seat, "phase": phase},
                view=human_view,
                history=history,
                result=None,
                error=self.error,
                message=_prompt_message(prompt.kind, phase=phase, action=self.game.pending_action),
            )
        actor_name = self.game.players[prompt.seat].name
        return ManualSnapshot(
            status="thinking",
            human_seat=self.human_seat,
            agents=list(self.agents),
            seed=self.seed,
            board=board,
            prompt={
                "kind": prompt.kind,
                "seat": prompt.seat,
                "name": actor_name,
            },
            view=human_view,
            history=history,
            result=None,
            error=self.error,
            message=f"{actor_name} is deciding…",
        )

    def _resolve_one_agent(self, seat: int, kind: str) -> None:
        player = self._players[seat]
        if player is None:
            raise RuntimeError(f"missing agent at seat {seat}")
        view = self.game.view_for(seat)
        if kind == "choose_action":
            action = player.choose_action(view)
            try:
                self.game.submit_action(action)
            except ValueError:
                player.illegals += 1
                self.game.submit_action(default_action(view))
        elif kind == "respond_to_action":
            if self.game.pending_action is None:
                raise RuntimeError("missing action")
            response = player.respond_to_action(view, self.game.pending_action)
            try:
                self.game.submit_reaction(response)
            except ValueError:
                player.illegals += 1
                self.game.submit_reaction(Pass())
        elif kind == "respond_to_block":
            if self.game.pending_block is None:
                raise RuntimeError("missing block")
            response = player.respond_to_block(view, self.game.pending_block)
            try:
                self.game.submit_reaction(response)
            except ValueError:
                player.illegals += 1
                self.game.submit_reaction(Pass())
        elif kind == "choose_card_to_lose":
            card = player.choose_card_to_lose(view)
            try:
                self.game.submit_loss(card)
            except ValueError:
                player.illegals += 1
                self.game.submit_loss(default_loss(view))
        elif kind == "choose_exchange":
            keep = player.choose_exchange(view, view.drawn)
            try:
                self.game.submit_exchange(keep)
            except ValueError:
                player.illegals += 1
                self.game.submit_exchange(default_exchange(view))
        else:
            raise RuntimeError(f"unknown prompt {kind}")

    def _public_board(self) -> dict[str, Any]:
        raw = self.game.board_snapshot()
        players = []
        for row in raw["players"]:
            seat = row["seat"]
            hand = row["hand"] if seat == self.human_seat else []
            players.append({**row, "hand": hand})
        return {**raw, "players": players}


def snapshot_dict(snap: ManualSnapshot) -> dict[str, Any]:
    return {
        "status": snap.status,
        "human_seat": snap.human_seat,
        "human_name": HUMAN_NAME,
        "agents": snap.agents,
        "seed": snap.seed,
        "board": snap.board,
        "prompt": snap.prompt,
        "view": snap.view,
        "history": snap.history,
        "result": snap.result,
        "error": snap.error,
        "message": snap.message,
    }


def _view_payload(view: Any) -> dict[str, Any]:
    data = to_data(view)
    # Flatten enums/dataclasses into UI-friendly shapes.
    return {
        "you": view.you,
        "phase": view.phase,
        "turn": view.turn,
        "actor": view.actor,
        "your_cards": [card.value for card in view.your_cards],
        "drawn": [card.value for card in view.drawn],
        "legal_actions": [
            {"type": action.type.value, "target": action.target} for action in view.legal_actions
        ],
        "legal_responses": [_response_payload(item) for item in view.legal_responses],
        "action": (
            {"type": view.action.type.value, "target": view.action.target}
            if view.action is not None
            else None
        ),
        "block": (
            {"card": view.block.card.value, "seat": view.block.seat}
            if view.block is not None
            else None
        ),
        "deck_count": view.deck_count,
        "_raw": data,
    }


def _response_payload(response: Response) -> dict[str, Any]:
    if isinstance(response, Pass):
        return {"type": "pass"}
    if isinstance(response, Challenge):
        return {"type": "challenge"}
    if isinstance(response, Block):
        return {"type": "block", "card": response.card.value}
    raise TypeError(f"unknown response {type(response)!r}")


def _parse_action(decision: dict[str, Any], legal: tuple[Action, ...]) -> Action:
    raw_type = decision.get("type")
    if not isinstance(raw_type, str):
        raise ValueError("action type required")
    try:
        action_type = ActionType(raw_type)
    except ValueError as exc:
        raise ValueError(f"unknown action {raw_type!r}") from exc
    target = decision.get("target")
    if target is not None:
        target = int(target)
    action = Action(action_type, target)
    if action not in legal:
        raise ValueError(f"illegal action {action}")
    return action


def _parse_response(decision: dict[str, Any], legal: tuple[Response, ...]) -> Response:
    raw_type = decision.get("type")
    if raw_type == "pass":
        response: Response = Pass()
    elif raw_type == "challenge":
        response = Challenge()
    elif raw_type == "block":
        response = Block(_parse_card(decision.get("card")))
    else:
        raise ValueError("response type must be pass, challenge, or block")
    if response not in legal:
        raise ValueError(f"illegal response {response}")
    return response


def _parse_card(value: Any) -> Card:
    if not isinstance(value, str):
        raise ValueError("card required")
    try:
        return Card(value)
    except ValueError as exc:
        raise ValueError(f"unknown card {value!r}") from exc


def _prompt_message(kind: str, phase: str | None = None, action: Action | None = None) -> str:
    if kind == "respond_to_action":
        if phase == "challenge":
            claimed = claim_of(action) if action is not None else None
            if claimed is not None:
                return f"Challenge the {card_label(claimed)} claim, or pass"
            return "Challenge the claim, or pass"
        if phase == "block":
            blockers = ACTION_BLOCK.get(action.type, ()) if action is not None else ()
            if blockers:
                names = " / ".join(card_label(card) for card in blockers)
                return f"Block with {names}, or pass"
            return "Block the action, or pass"
        return "Respond to the action"
    if kind == "respond_to_block":
        return "Challenge the block, or pass"
    return {
        "choose_action": "Your turn — choose an action",
        "choose_card_to_lose": "Choose a card to lose",
        "choose_exchange": "Choose which cards to keep",
    }.get(kind, "Your move")
