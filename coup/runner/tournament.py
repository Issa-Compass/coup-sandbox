"""Run a seeded round and write leaderboards."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from coup.runner.catalog import EXAMPLES, resolve_agent, submission_agents
from coup.runner.identity import invert_uids, load_or_create_uids, remap_stats, remap_winners
from coup.runner.load_agent import agent_name_from_path, unique_instance_names
from coup.runner.match import play_game
from coup.runner.players import open_player
from coup.runner.reporting import sort_rows, write_game_log, write_round_outputs, write_standings
from coup.runner.schedule import build_tables
from coup.runner.seeds import game_seed
from coup.runner.standings import build_snapshot, load_prior_rounds

ROOT = Path(__file__).resolve().parents[2]

ProgressFn = Callable[[dict[str, Any]], None]
StopFn = Callable[[], bool]


def default_agent_paths(explicit: list[str] | None, with_examples: bool) -> list[Path]:
    if explicit:
        return [resolve_agent(token) for token in explicit]
    found = submission_agents()
    if found:
        paths = list(found)
        if with_examples:
            paths.extend(
                EXAMPLES[name]
                for name in ("random", "honest", "guard", "turtle", "greedy")
            )
        return paths
    return [
        EXAMPLES[name] for name in ("random", "honest", "guard", "turtle", "greedy")
    ]


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
    on_progress: ProgressFn | None = None,
    should_stop: StopFn | None = None,
    agent_names: list[str] | None = None,
) -> Path:
    if round_number < 1:
        raise ValueError("round number must be positive")
    if len(agent_paths) < 2:
        raise ValueError("a round needs at least 2 agents")
    if agent_names is not None and len(agent_names) != len(agent_paths):
        raise ValueError("agent_names must match agent_paths length")
    raw_names = (
        list(agent_names)
        if agent_names is not None
        else [agent_name_from_path(path) for path in agent_paths]
    )
    names = unique_instance_names(raw_names)
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
    uids = load_or_create_uids(run_folder, names)
    for player in players:
        player.public_id = uids[player.name]
    public_to_real = invert_uids(uids)
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
    prior_stats, previous_winners = load_prior_rounds(run_folder, round_number)
    if on_progress:
        on_progress(
            {
                "phase": "round_start",
                "run_id": run_id,
                "round": round_number,
                "games": len(tables),
                "agents": names,
            }
        )
    try:
        for index, table in enumerate(tables, start=1):
            if should_stop and should_stop():
                raise RuntimeError("session stopped")
            seed = game_seed(secret, master_seed, index)
            seated = [by_name[name] for name in table]
            game_id = f"g{index:04d}"
            public_table = [uids[name] for name in table]
            snapshot = build_snapshot(
                run_id=run_id,
                round_number=round_number,
                game_index=index,
                game_id=game_id,
                table=public_table,
                round_stats=remap_stats(stats, uids),
                prior_stats=remap_stats(prior_stats, uids),
                previous_round_winners=remap_winners(previous_winners, uids),
            )
            played = play_game(seated, seed=seed, standings=snapshot)
            write_game_log(
                round_folder / "games" / f"{game_id}.jsonl",
                played,
                seed,
                game_id,
                public_to_real=public_to_real,
            )
            _add_game(stats, played, seated)
            winner = seated[played.result.winner].name
            print(f"game {index}/{len(tables)}: {', '.join(table)} -> {winner}")
            if on_progress:
                on_progress(
                    {
                        "phase": "game",
                        "run_id": run_id,
                        "round": round_number,
                        "index": index,
                        "total": len(tables),
                        "game_id": game_id,
                        "table": list(table),
                        "winner": winner,
                    }
                )
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
    if on_progress:
        on_progress({"phase": "round_done", "run_id": run_id, "round": round_number, "games": len(tables)})
    return round_folder


def _add_game(stats: dict[str, dict[str, Any]], played, seated) -> None:
    for placement in played.result.placements:
        real_name = seated[placement.seat].name
        row = stats[real_name]
        row["games"] += 1
        row["points"] += placement.points
        row["wins"] += int(placement.place == 1)
        penalty = played.penalties[real_name]
        row["illegal"] += penalty["illegal"]
        row["errors"] += penalty["errors"]
        row["timeouts"] += penalty["timeouts"]
        row["decisions"] += penalty["decisions"]
        row["decision_time"] += penalty["decision_time"]

