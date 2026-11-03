"""Build standings snapshots agents may query during a tournament game."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from coup.agent_api import PreviousRoundWinner, StandingRow, StandingsSnapshot
from coup.runner.reporting import sort_rows


def empty_stat(name: str) -> dict[str, Any]:
    return {
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


def rows_from_stats(stats: dict[str, dict[str, Any]]) -> tuple[StandingRow, ...]:
    ranked = sort_rows(list(stats.values()))
    return tuple(_row(index, item) for index, item in enumerate(ranked, start=1))


def merge_stats(
    base: dict[str, dict[str, Any]],
    extra: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {name: dict(row) for name, row in base.items()}
    for name, row in extra.items():
        total = merged.setdefault(name, empty_stat(name))
        for key in ("games", "points", "wins", "illegal", "errors", "timeouts", "decisions"):
            total[key] += row[key]
        total["decision_time"] += row.get("decision_time", 0.0)
    return merged


def load_prior_rounds(
    run_folder: Path,
    current_round: int,
) -> tuple[dict[str, dict[str, Any]], tuple[PreviousRoundWinner, ...]]:
    """Stats and winners from ``round_1`` .. ``round_{current_round-1}`` under ``run_folder``."""

    combined: dict[str, dict[str, Any]] = {}
    winners: list[PreviousRoundWinner] = []
    for number in range(1, current_round):
        summary_path = run_folder / f"round_{number}" / "summary.json"
        if not summary_path.is_file():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        agents = summary.get("agents") or []
        if not agents:
            continue
        round_stats = {row["name"]: _coerce_stat(row) for row in agents}
        combined = merge_stats(combined, round_stats)
        top = sort_rows(list(round_stats.values()))[0]
        winners.append(
            PreviousRoundWinner(
                round=int(summary.get("round", number)),
                name=top["name"],
                games=top["games"],
                points=top["points"],
                wins=top["wins"],
                avg_points=_avg(top["points"], top["games"]),
            )
        )
    return combined, tuple(winners)


def build_snapshot(
    *,
    run_id: str,
    round_number: int,
    game_index: int,
    game_id: str,
    table: list[str] | tuple[str, ...],
    round_stats: dict[str, dict[str, Any]],
    prior_stats: dict[str, dict[str, Any]],
    previous_round_winners: tuple[PreviousRoundWinner, ...],
) -> StandingsSnapshot:
    round_rows = rows_from_stats(round_stats)
    tournament_stats = merge_stats(prior_stats, round_stats)
    # Agents only in the current round still appear on the tournament board.
    for name in round_stats:
        tournament_stats.setdefault(name, empty_stat(name))
    return StandingsSnapshot(
        run_id=run_id,
        round=round_number,
        game_index=game_index,
        game_id=game_id,
        table=tuple(table),
        round_rows=round_rows,
        tournament_rows=rows_from_stats(tournament_stats),
        previous_round_winners=previous_round_winners,
    )


def _row(rank: int, item: dict[str, Any]) -> StandingRow:
    return StandingRow(
        rank=rank,
        name=item["name"],
        games=item["games"],
        points=item["points"],
        wins=item["wins"],
        avg_points=_avg(item["points"], item["games"]),
        illegal=item.get("illegal", 0),
        errors=item.get("errors", 0),
        timeouts=item.get("timeouts", 0),
    )


def _coerce_stat(row: dict[str, Any]) -> dict[str, Any]:
    base = empty_stat(row["name"])
    for key in base:
        if key in row:
            base[key] = row[key]
    return base


def _avg(points: int, games: int) -> float:
    if games <= 0:
        return 0.0
    return points / games
