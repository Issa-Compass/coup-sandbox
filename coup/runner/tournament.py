"""Run a seeded round and write leaderboards."""

from __future__ import annotations

import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from coup.runner.catalog import EXAMPLES, resolve_agent, submission_agents
from coup.runner.load_agent import agent_name_from_path
from coup.runner.match import play_game
from coup.runner.players import open_player
from coup.runner.reporting import sort_rows, write_game_log, write_round_outputs, write_standings
from coup.runner.schedule import build_tables
from coup.runner.seeds import game_seed

ROOT = Path(__file__).resolve().parents[2]


def default_agent_paths(explicit: list[str] | None, with_examples: bool) -> list[Path]:
    if explicit:
        return [resolve_agent(token) for token in explicit]
    found = submission_agents()
    if found:
        paths = list(found)
        if with_examples:
            paths.extend(EXAMPLES[name] for name in ("random", "honest", "bluffer", "challenger"))
        return paths
    return [EXAMPLES[name] for name in ("random", "honest", "bluffer", "challenger")]


def run_round(
    agent_paths: list[Path],
    *,
    games_per_agent: int,
    master_seed: int,
    round_number: int,
    run_id: str | None,
    timeout: float,
    sandbox: bool,
    table_size: int,
    results_root: Path | None = None,
    force: bool = False,
) -> Path:
    if round_number < 1:
        raise ValueError("round number must be positive")
    if len(agent_paths) < 2:
        raise ValueError("a round needs at least 2 agents")
    names = [agent_name_from_path(path) for path in agent_paths]
    if len(set(names)) != len(names):
        raise ValueError(f"agent names must be unique, got {names}")
    run_id = run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    root = results_root or (ROOT / "results")
    run_folder = root / run_id
    round_folder = run_folder / f"round_{round_number}"
    if round_folder.exists() and not force:
        raise FileExistsError(f"{round_folder} already exists. Pass --force to replace it.")
    if force and round_folder.exists():
        for child in sorted(round_folder.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
    players = [
        open_player(path, name, sandbox=sandbox, timeout=timeout)
        for path, name in zip(agent_paths, names)
    ]
    by_name = {player.name: player for player in players}
    tables = build_tables(names, games_per_agent, master_seed, prefer=table_size)
    secret = secrets.token_bytes(32)
    stats = {
        name: {
            "name": name,
            "games": 0,
            "points": 0,
            "wins": 0,
            "illegal": 0,
            "errors": 0,
            "timeouts": 0,
            "decisions": 0,
            "decision_time": 0.0,
        }
        for name in names
    }
    try:
        for index, table in enumerate(tables, start=1):
            seed = game_seed(secret, master_seed, index)
            seated = [by_name[name] for name in table]
            played = play_game(seated, seed=seed)
            game_id = f"g{index:04d}"
            write_game_log(round_folder / "games" / f"{game_id}.jsonl", played, seed, game_id)
            _add_game(stats, played)
            print(f"game {index}/{len(tables)}: {', '.join(table)} -> {played.game.players[played.result.winner].name}")
    finally:
        for player in players:
            player.close()
    summary = {
        "run_id": run_id,
        "round": round_number,
        "master_seed": master_seed,
        "games_per_agent": games_per_agent,
        "sandbox": sandbox,
        "timeout": timeout,
        "table_size": table_size,
        "games": len(tables),
        "agents": sort_rows(list(stats.values())),
    }
    write_round_outputs(round_folder, summary)
    write_standings(run_folder, run_id)
    print(f"leaderboard: {round_folder / 'leaderboard.md'}")
    return round_folder


def _add_game(stats: dict[str, dict[str, Any]], played) -> None:
    for placement in played.result.placements:
        row = stats[placement.name]
        row["games"] += 1
        row["points"] += placement.points
        row["wins"] += int(placement.place == 1)
        penalty = played.penalties[placement.name]
        row["illegal"] += penalty["illegal"]
        row["errors"] += penalty["errors"]
        row["timeouts"] += penalty["timeouts"]
        row["decisions"] += penalty["decisions"]
        row["decision_time"] += penalty["decision_time"]

