"""Leaderboards and game logs."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from coup.agent_api import Event
from coup.runner.match import PlayedGame


def write_game_log(path: Path, played: PlayedGame, seed: int, game_id: str) -> None:
    lines: list[dict[str, Any]] = [
        {
            "type": "game",
            "id": game_id,
            "seed": seed,
            "players": [player.name for player in played.game.players],
            "max_turns": played.game.max_turns,
        }
    ]
    for event in played.game.history:
        lines.append(_event_line(event))
    lines.append(
        {
            "type": "result",
            "turns": played.result.turns,
            "capped": played.result.capped,
            "winner": played.game.players[played.result.winner].name,
            "placements": [
                {
                    "place": item.place,
                    "name": item.name,
                    "points": item.points,
                    "influence": item.influence,
                    "coins": item.coins,
                }
                for item in played.result.placements
            ],
            "penalties": played.penalties,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")


def write_round_outputs(folder: Path, summary: dict[str, Any]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    rows = list(summary["agents"])
    title = f"Round {summary['round']} ({summary['run_id']})"
    (folder / "leaderboard.md").write_text(_markdown(title, rows), encoding="utf-8")
    (folder / "leaderboard.html").write_text(_html(title, rows), encoding="utf-8")


def write_standings(run_folder: Path, run_id: str) -> dict[str, Any]:
    combined: dict[str, dict[str, Any]] = {}
    rounds = sorted(path for path in run_folder.glob("round_*") if path.is_dir())
    for folder in rounds:
        summary_path = folder / "summary.json"
        if not summary_path.is_file():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        for row in summary["agents"]:
            total = combined.setdefault(
                row["name"],
                {
                    "name": row["name"],
                    "games": 0,
                    "points": 0,
                    "wins": 0,
                    "illegal": 0,
                    "errors": 0,
                    "timeouts": 0,
                    "decisions": 0,
                    "decision_time": 0.0,
                },
            )
            for key in ("games", "points", "wins", "illegal", "errors", "timeouts", "decisions"):
                total[key] += row[key]
            total["decision_time"] += row["decision_time"]
    agents = sort_rows(list(combined.values()))
    payload = {"run_id": run_id, "rounds": len(rounds), "agents": agents}
    run_folder.mkdir(parents=True, exist_ok=True)
    (run_folder / "standings.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (run_folder / "standings.md").write_text(
        _markdown(f"Standings ({run_id})", agents),
        encoding="utf-8",
    )
    (run_folder / "standings.html").write_text(
        _html(f"Standings ({run_id})", agents),
        encoding="utf-8",
    )
    return payload


def sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple:
        games = row["games"] or 1
        faults = row["illegal"] + row["errors"] + row["timeouts"]
        return (-row["points"] / games, -row["wins"] / games, faults, row["name"])

    return sorted(rows, key=key)


def _event_line(event: Event) -> dict[str, Any]:
    line: dict[str, Any] = {
        "type": "event",
        "event": event.type,
        "turn": event.turn,
        "message": event.message,
    }
    for field in ("seat", "target", "action", "challenger", "claimer", "success", "amount", "coins"):
        value = getattr(event, field)
        if value is not None:
            line[field] = value
    if event.card is not None:
        line["card"] = event.card.value
    return line


def _markdown(title: str, rows: list[dict[str, Any]]) -> str:
    ranked = sort_rows(rows)
    lines = [
        f"# {title}",
        "",
        "| Rank | Agent | Games | Points | Avg | Wins | Win% | Illegal | Errors | Timeouts | Avg ms |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rank, row in enumerate(ranked, start=1):
        lines.append(
            "| {rank} | {name} | {games} | {points} | {avg} | {wins} | {rate} | {illegal} | {errors} | {timeouts} | {ms} |".format(
                rank=rank,
                name=row["name"],
                games=row["games"],
                points=row["points"],
                avg=_avg(row["points"], row["games"]),
                wins=row["wins"],
                rate=_pct(row["wins"], row["games"]),
                illegal=row["illegal"],
                errors=row["errors"],
                timeouts=row["timeouts"],
                ms=_ms(row),
            )
        )
    lines.append("")
    return "\n".join(lines)


def _html(title: str, rows: list[dict[str, Any]]) -> str:
    ranked = sort_rows(rows)
    body = []
    for rank, row in enumerate(ranked, start=1):
        cells = [
            str(rank),
            html.escape(str(row["name"])),
            str(row["games"]),
            str(row["points"]),
            _avg(row["points"], row["games"]),
            str(row["wins"]),
            _pct(row["wins"], row["games"]),
            str(row["illegal"]),
            str(row["errors"]),
            str(row["timeouts"]),
            _ms(row),
        ]
        body.append("<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    headers = ["Rank", "Agent", "Games", "Points", "Avg", "Wins", "Win%", "Illegal", "Errors", "Timeouts", "Avg ms"]
    head = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{ font-family: Georgia, serif; margin: 2rem; color: #1a1a1a; background: #f7f4ef; }}
h1 {{ font-weight: 500; }}
table {{ border-collapse: collapse; width: 100%; background: white; }}
th, td {{ padding: 0.6rem 0.8rem; text-align: right; border-bottom: 1px solid #ddd; }}
th:nth-child(2), td:nth-child(2) {{ text-align: left; }}
th {{ background: #1f3a2e; color: white; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<table>
<thead><tr>{head}</tr></thead>
<tbody>
{''.join(body)}
</tbody>
</table>
</body>
</html>
"""


def _avg(points: int, games: int) -> str:
    if not games:
        return "0.00"
    return f"{points / games:.2f}"


def _pct(wins: int, games: int) -> str:
    if not games:
        return "0%"
    return f"{100 * wins / games:.0f}%"


def _ms(row: dict[str, Any]) -> str:
    decisions = row.get("decisions") or 0
    if not decisions:
        return "0"
    return f"{1000 * row['decision_time'] / decisions:.2f}"
