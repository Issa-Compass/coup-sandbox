"""Serve the organizer scoreboard and game playback dashboard.

  python scripts/serve_dashboard.py --results results --port 8765

Also starts multi-round tournament sessions from the UI (agent pick + watch live).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import random
import re
import sys
import threading
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from coup.runner.catalog import list_available_agents, resolve_agent  # noqa: E402
from coup.runner.tournament import run_round  # noqa: E402

DASHBOARD = ROOT / "dashboard"

SAFE_RUN = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_GAME = re.compile(r"^g\d{4}$")
SAFE_AGENT = re.compile(r"^[A-Za-z0-9._-]+$")


class SessionController:
    """One background multi-round tournament at a time."""

    def __init__(self, results: Path) -> None:
        self.results = results
        self.lock = threading.Lock()
        self._cancel = False
        self._thread: threading.Thread | None = None
        self.state: dict[str, Any] = _idle_session()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return dict(self.state)

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if self.state["status"] != "running":
                return dict(self.state)
            self._cancel = True
            self.state["message"] = "Stopping after the current game…"
            return dict(self.state)

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self.state["status"] == "running":
                raise ValueError("a session is already running")
            config = _parse_session_config(payload)
            self._cancel = False
            self.state = {
                "status": "running",
                "run_id": config["run_id"],
                "agents": list(config["agents"]),
                "rounds": list(config["rounds"]),
                "round_index": 0,
                "rounds_total": len(config["rounds"]),
                "current_round": config["rounds"][0]["number"],
                "current_game": 0,
                "games_in_round": 0,
                "last_game_id": None,
                "message": "Starting…",
                "error": None,
                "started_at": _now(),
                "finished_at": None,
                "sandbox": config["sandbox"],
                "seed": config["seed"],
            }
            self._thread = threading.Thread(
                target=self._run,
                args=(config,),
                name="coup-session",
                daemon=True,
            )
            self._thread.start()
            return dict(self.state)

    def _run(self, config: dict[str, Any]) -> None:
        try:
            paths = [resolve_agent(alias) for alias in config["agents"]]
            for index, round_cfg in enumerate(config["rounds"]):
                if self._should_stop():
                    raise RuntimeError("session stopped")
                with self.lock:
                    self.state["round_index"] = index
                    self.state["current_round"] = round_cfg["number"]
                    self.state["current_game"] = 0
                    self.state["games_in_round"] = 0
                    self.state["message"] = f"Round {round_cfg['number']} starting…"
                run_round(
                    paths,
                    games_per_agent=round_cfg["games_per_agent"],
                    master_seed=config["seed"] + index,
                    round_number=round_cfg["number"],
                    run_id=config["run_id"],
                    timeout=config["timeout"],
                    sandbox=config["sandbox"],
                    table_size=config["table_size"],
                    results_root=self.results,
                    force=config["force"],
                    on_progress=self._on_progress,
                    should_stop=self._should_stop,
                )
            with self.lock:
                self.state["status"] = "done"
                self.state["message"] = "All rounds finished"
                self.state["finished_at"] = _now()
        except Exception as exc:  # noqa: BLE001 — surface any runner failure to the UI
            with self.lock:
                stopped = isinstance(exc, RuntimeError) and str(exc) == "session stopped"
                self.state["status"] = "stopped" if stopped else "error"
                self.state["error"] = None if stopped else str(exc)
                self.state["message"] = "Stopped" if stopped else f"Failed: {exc}"
                self.state["finished_at"] = _now()
            if self.state["status"] == "error":
                traceback.print_exc()

    def _should_stop(self) -> bool:
        return self._cancel

    def _on_progress(self, event: dict[str, Any]) -> None:
        with self.lock:
            phase = event.get("phase")
            if phase == "round_start":
                self.state["current_round"] = event["round"]
                self.state["games_in_round"] = event["games"]
                self.state["current_game"] = 0
                self.state["message"] = f"Round {event['round']}: {event['games']} games"
            elif phase == "game":
                self.state["current_round"] = event["round"]
                self.state["current_game"] = event["index"]
                self.state["games_in_round"] = event["total"]
                self.state["last_game_id"] = event["game_id"]
                self.state["message"] = (
                    f"Round {event['round']} · game {event['index']}/{event['total']} "
                    f"({event['game_id']}) → {event['winner']}"
                )
            elif phase == "round_done":
                self.state["message"] = f"Round {event['round']} complete"


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Coup organizer dashboard.")
    parser.add_argument("--results", type=Path, default=ROOT / "results")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    results = args.results.resolve()
    results.mkdir(parents=True, exist_ok=True)
    session = SessionController(results)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path.startswith("/api/"):
                self._api_get(path)
                return
            self._static(path)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = unquote(parsed.path)
            if path.startswith("/api/"):
                self._api_post(path)
                return
            self.send_error(404)

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            print(f"{self.address_string()} {format % args}")

        def _api_get(self, path: str) -> None:
            parts = [part for part in path.split("/") if part]
            try:
                if parts == ["api", "agents"]:
                    self._json(200, {"agents": list_available_agents()})
                    return
                if parts == ["api", "rules"]:
                    rules_path = ROOT / "RULES.md"
                    if not rules_path.is_file():
                        self._json(404, {"error": "rules not found"})
                        return
                    self._json(200, {"text": rules_path.read_text(encoding="utf-8")})
                    return
                if parts == ["api", "session"]:
                    self._json(200, session.snapshot())
                    return
                if parts == ["api", "runs"]:
                    self._json(200, {"runs": _list_runs(results)})
                    return
                if len(parts) == 4 and parts[0] == "api" and parts[1] == "runs" and parts[3] == "standings":
                    run_id = _safe_run(parts[2])
                    payload = _read_json(results / run_id / "standings.json")
                    if payload is None:
                        self._json(404, {"error": "standings not found"})
                        return
                    self._json(200, payload)
                    return
                if (
                    len(parts) == 5
                    and parts[0] == "api"
                    and parts[1] == "runs"
                    and parts[3] == "rounds"
                ):
                    run_id = _safe_run(parts[2])
                    round_number = _safe_round(parts[4])
                    payload = _read_json(results / run_id / f"round_{round_number}" / "summary.json")
                    if payload is None:
                        self._json(404, {"error": "round not found"})
                        return
                    self._json(200, payload)
                    return
                if (
                    len(parts) == 6
                    and parts[0] == "api"
                    and parts[1] == "runs"
                    and parts[3] == "rounds"
                    and parts[5] == "games"
                ):
                    run_id = _safe_run(parts[2])
                    round_number = _safe_round(parts[4])
                    self._json(200, {"games": _list_games(results / run_id / f"round_{round_number}" / "games")})
                    return
                if (
                    len(parts) == 7
                    and parts[0] == "api"
                    and parts[1] == "runs"
                    and parts[3] == "rounds"
                    and parts[5] == "games"
                ):
                    run_id = _safe_run(parts[2])
                    round_number = _safe_round(parts[4])
                    game_id = _safe_game(parts[6])
                    path_log = results / run_id / f"round_{round_number}" / "games" / f"{game_id}.jsonl"
                    if not path_log.is_file():
                        self._json(404, {"error": "game not found"})
                        return
                    self._json(200, {"lines": _read_jsonl(path_log)})
                    return
                if len(parts) == 3 and parts[0] == "api" and parts[1] == "runs":
                    run_id = _safe_run(parts[2])
                    run_folder = results / run_id
                    if not run_folder.is_dir():
                        self._json(404, {"error": "run not found"})
                        return
                    rounds = sorted(
                        int(path.name.split("_", 1)[1])
                        for path in run_folder.glob("round_*")
                        if path.is_dir() and path.name.split("_", 1)[1].isdigit()
                    )
                    self._json(200, {"run_id": run_id, "rounds": rounds})
                    return
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(404, {"error": "not found"})

        def _api_post(self, path: str) -> None:
            parts = [part for part in path.split("/") if part]
            try:
                body = self._read_body()
                if parts == ["api", "session", "start"]:
                    self._json(200, session.start(body))
                    return
                if parts == ["api", "session", "stop"]:
                    self._json(200, session.stop())
                    return
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return
            self._json(404, {"error": "not found"})

        def _read_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            if not raw.strip():
                return {}
            data = json.loads(raw.decode("utf-8"))
            if not isinstance(data, dict):
                raise ValueError("body must be a json object")
            return data

        def _static(self, path: str) -> None:
            if path in ("", "/"):
                path = "/index.html"
            relative = path.lstrip("/")
            target = (DASHBOARD / relative).resolve()
            if not str(target).startswith(str(DASHBOARD.resolve())) or not target.is_file():
                self.send_error(404)
                return
            data = target.read_bytes()
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, payload: object) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"dashboard http://{args.host}:{args.port}  results={results}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


def _idle_session() -> dict[str, Any]:
    return {
        "status": "idle",
        "run_id": None,
        "agents": [],
        "rounds": [],
        "round_index": 0,
        "rounds_total": 0,
        "current_round": None,
        "current_game": 0,
        "games_in_round": 0,
        "last_game_id": None,
        "message": None,
        "error": None,
        "started_at": None,
        "finished_at": None,
        "sandbox": None,
        "seed": None,
    }


def _parse_session_config(payload: dict[str, Any]) -> dict[str, Any]:
    agents = payload.get("agents")
    if not isinstance(agents, list) or len(agents) < 2:
        raise ValueError("select at least 2 agents")
    cleaned_agents: list[str] = []
    for item in agents:
        if not isinstance(item, str) or not SAFE_AGENT.match(item):
            raise ValueError(f"invalid agent id: {item!r}")
        try:
            resolve_agent(item)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        cleaned_agents.append(item)

    rounds_raw = payload.get("rounds")
    if not isinstance(rounds_raw, list) or not rounds_raw:
        raise ValueError("add at least one round")
    rounds: list[dict[str, int]] = []
    seen: set[int] = set()
    for item in rounds_raw:
        if not isinstance(item, dict):
            raise ValueError("each round must be an object")
        number = int(item.get("number", 0))
        games = int(item.get("games_per_agent", 0))
        if number < 1:
            raise ValueError("round number must be >= 1")
        if games < 1:
            raise ValueError("games_per_agent must be >= 1")
        if number in seen:
            raise ValueError(f"duplicate round number {number}")
        seen.add(number)
        rounds.append({"number": number, "games_per_agent": games})
    rounds.sort(key=lambda row: row["number"])

    run_id = payload.get("run_id") or datetime.now().strftime("%Y%m%d-%H%M%S")
    if not isinstance(run_id, str) or not SAFE_RUN.match(run_id):
        raise ValueError("invalid run id")

    seed_raw = payload.get("seed", None)
    if seed_raw is None or seed_raw == "":
        seed = random.randrange(1, 2**31)
    else:
        seed = int(seed_raw)
    timeout = float(payload.get("timeout", 1.0))
    table_size = int(payload.get("table_size", 5))
    sandbox = bool(payload.get("sandbox", False))
    force = bool(payload.get("force", False))
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if not 2 <= table_size <= 6:
        raise ValueError("table_size must be 2–6")

    return {
        "agents": cleaned_agents,
        "rounds": rounds,
        "run_id": run_id,
        "seed": seed,
        "timeout": timeout,
        "table_size": table_size,
        "sandbox": sandbox,
        "force": force,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_run(value: str) -> str:
    if not SAFE_RUN.match(value):
        raise ValueError("invalid run id")
    return value


def _safe_round(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise ValueError("invalid round")
    return int(value)


def _safe_game(value: str) -> str:
    if not SAFE_GAME.match(value):
        raise ValueError("invalid game id")
    return value


def _list_runs(results: Path) -> list[dict]:
    runs = []
    for folder in sorted(results.iterdir(), key=lambda path: path.name, reverse=True):
        if not folder.is_dir():
            continue
        if not SAFE_RUN.match(folder.name):
            continue
        rounds = sorted(
            int(path.name.split("_", 1)[1])
            for path in folder.glob("round_*")
            if path.is_dir() and path.name.split("_", 1)[1].isdigit()
        )
        runs.append(
            {
                "id": folder.name,
                "rounds": rounds,
                "has_standings": (folder / "standings.json").is_file(),
            }
        )
    return runs


def _list_games(games_folder: Path) -> list[dict]:
    if not games_folder.is_dir():
        return []
    games = []
    for path in sorted(games_folder.glob("g*.jsonl")):
        try:
            rows = _read_jsonl(path)
        except json.JSONDecodeError:
            # Mid-write or truncated file — skip until the next refresh.
            continue
        header = next((row for row in rows if row.get("type") == "game"), None)
        result = next((row for row in rows if row.get("type") == "result"), None)
        if header is None:
            continue
        games.append(
            {
                "id": header.get("id", path.stem),
                "seed": header.get("seed"),
                "players": header.get("players", []),
                "winner": None if result is None else result.get("winner"),
                "turns": None if result is None else result.get("turns"),
                "capped": None if result is None else result.get("capped"),
            }
        )
    return games


def _read_json(path: Path) -> object | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    main()
