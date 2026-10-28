"""Play one game by asking the seated players for each decision."""

from __future__ import annotations

from dataclasses import dataclass

from coup.agent_api import TURN_CAP, GameResult, default_action, default_exchange, default_loss
from coup.agent_api import Pass
from coup.engine.game import Game
from coup.runner.players import Player
from coup.runner.seeds import personal_seed


@dataclass
class PlayedGame:
    game: Game
    result: GameResult
    penalties: dict[str, dict[str, int | float]]


def play_game(players: list[Player], seed: int, max_turns: int = TURN_CAP) -> PlayedGame:
    if len({player.name for player in players}) != len(players):
        raise ValueError("player names at a table must be unique")
    before = [player.snapshot() for player in players]
    game = Game([player.name for player in players], seed=seed, max_turns=max_turns)
    for seat, player in enumerate(players):
        player.on_game_start(game.view_for(seat), personal_seed(seed, seat, player.name))
    while not game.finished:
        prompt = game.prompt()
        if prompt is None:
            break
        player = players[prompt.seat]
        view = game.view_for(prompt.seat)
        if prompt.kind == "choose_action":
            action = player.choose_action(view)
            try:
                game.submit_action(action)
            except ValueError:
                player.illegals += 1
                game.submit_action(default_action(view))
        elif prompt.kind == "respond_to_action":
            if game.pending_action is None:
                raise RuntimeError("missing action")
            response = player.respond_to_action(view, game.pending_action)
            try:
                game.submit_reaction(response)
            except ValueError:
                player.illegals += 1
                game.submit_reaction(Pass())
        elif prompt.kind == "respond_to_block":
            if game.pending_block is None:
                raise RuntimeError("missing block")
            response = player.respond_to_block(view, game.pending_block)
            try:
                game.submit_reaction(response)
            except ValueError:
                player.illegals += 1
                game.submit_reaction(Pass())
        elif prompt.kind == "choose_card_to_lose":
            card = player.choose_card_to_lose(view)
            try:
                game.submit_loss(card)
            except ValueError:
                player.illegals += 1
                game.submit_loss(default_loss(view))
        elif prompt.kind == "choose_exchange":
            keep = player.choose_exchange(view, view.drawn)
            try:
                game.submit_exchange(keep)
            except ValueError:
                player.illegals += 1
                game.submit_exchange(default_exchange(view))
        else:
            raise RuntimeError(f"unknown prompt {prompt.kind}")
    result = game.result()
    for seat, player in enumerate(players):
        player.on_game_end(game.view_for(seat), result)
    penalties = {}
    for player, start in zip(players, before):
        illegal, errors, timeouts, decisions, spent = player.snapshot()
        penalties[player.name] = {
            "illegal": illegal - start[0],
            "errors": errors - start[1],
            "timeouts": timeouts - start[2],
            "decisions": decisions - start[3],
            "decision_time": round(spent - start[4], 6),
        }
    return PlayedGame(game=game, result=result, penalties=penalties)
