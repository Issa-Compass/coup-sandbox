"""Serve the scoreboard and game playback dashboard.

  python scripts/serve_dashboard.py --results results --port 8765

Also starts multi-round tournament sessions from the UI (agent pick + watch live).
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
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


from coup.hub_client import (  # noqa: E402
    HubError,
    download_agent,
    list_remote_agents,
    load_repo_dotenv,
    master_url,
    ping_hub,
    upload_agent,
    validate_full_name,
    validate_player_uid,
    validate_local_name,
)
from coup.runner.catalog import (  # noqa: E402
    LOCAL,
    SUBMISSIONS,
    arena_agent_id,
    arena_name,
    display_name_for_token,
    list_available_agents,
    resolve_agent,
)
from coup.runner.load_agent import unique_instance_names  # noqa: E402
from coup.runner.manual import ManualGame, snapshot_dict  # noqa: E402
from coup.runner.players import open_player  # noqa: E402
from coup.runner.testing import evaluate  # noqa: E402
from coup.runner.tournament import run_round  # noqa: E402

DASHBOARD = ROOT / "dashboard"

SAFE_RUN = re.compile(r"^[A-Za-z0-9._-]+$")
SAFE_GAME = re.compile(r"^g\d{4}$")
# Bare local/example ids, or namespaced local:<name> / arena:<hub_name>.
SAFE_AGENT = re.compile(r"^(?:(?:arena|local):[A-Za-z0-9_-]+|[A-Za-z0-9._-]+)$")
SAFE_HUB_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
DEFAULT_VALIDATE_GAMES = 40
DEFAULT_VALIDATE_SANDBOX_GAMES = 2


class SessionController:
    """One background multi-round tournament at a time."""

    def __init__(self, results: Path, hub_base: str = "") -> None:
        self.results = results
        self.hub_base = (hub_base or "").rstrip("/")
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
        # Reject early without holding the lock across hub downloads.
        with self.lock:
            if self.state["status"] == "running":
                raise ValueError("a session is already running")
        # Resolve / download agents outside the lock so /api/session stays responsive.
        config = _parse_session_config(payload, hub_base=self.hub_base)
        with self.lock:
            if self.state["status"] == "running":
                raise ValueError("a session is already running")
            _write_roster(self.results / config["run_id"], config["agents"])
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
            aliases = list(config["agents"])
            paths = list(config["paths"])
            seat_names = [display_name_for_token(alias) for alias in aliases]
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
                    agent_names=seat_names,
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


class ManualController:
    """One interactive human-vs-agents game at a time."""

    def __init__(self, hub_base: str = "") -> None:
        self.hub_base = (hub_base or "").rstrip("/")
        self.lock = threading.Lock()
        self._game: ManualGame | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return self._snapshot_unlocked()

    def stop(self) -> dict[str, Any]:
        with self.lock:
            if self._game is not None:
                self._game.close()
                self._game = None
            return self._snapshot_unlocked()

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            busy = (
                self._game is not None
                and self._game.snapshot().status in ("waiting", "thinking")
            )
            if busy:
                raise ValueError("a manual game is already in progress — stop it first")
        # Resolve / download opponents outside the lock (hub I/O).
        config = _parse_manual_config(payload, hub_base=self.hub_base)
        with self.lock:
            if self._game is not None:
                status = self._game.snapshot().status
                if status in ("waiting", "thinking"):
                    raise ValueError("a manual game is already in progress — stop it first")
                self._game.close()
                self._game = None
            players = [
                open_player(path, name, sandbox=False, timeout=config["timeout"])
                for path, name in zip(config["paths"], config["seat_names"])
            ]
            game = ManualGame(players, seed=config["seed"])
            try:
                snap = game.start()
            except Exception:
                game.close()
                raise
            self._game = game
            return snapshot_dict(snap)

    def move(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if self._game is None:
                raise ValueError("no manual game in progress")
            if not isinstance(payload, dict):
                raise ValueError("decision must be an object")
            snap = self._game.submit(payload)
            return snapshot_dict(snap)

    def step(self) -> dict[str, Any]:
        with self.lock:
            if self._game is None:
                raise ValueError("no manual game in progress")
            snap = self._game.step_agent()
            return snapshot_dict(snap)

    def _snapshot_unlocked(self) -> dict[str, Any]:
        if self._game is None:
            return {
                "status": "idle",
                "human_seat": 0,
                "human_name": "You",
                "agents": [],
                "seed": None,
                "board": None,
                "prompt": None,
                "view": None,
                "history": [],
                "result": None,
                "error": None,
                "message": "Pick opponents, then Play.",
            }
        return snapshot_dict(self._game.snapshot())


def make_handler(
    *,
    results: Path,
    hub_base: str = "",
    session: SessionController | None = None,
    manual: ManualController | None = None,
    quiet: bool = False,
) -> type[BaseHTTPRequestHandler]:
    """Build the dashboard request handler (also used by tests)."""

    results = results.resolve()
    results.mkdir(parents=True, exist_ok=True)
    hub = (hub_base or "").rstrip("/")
    controller = session or SessionController(results, hub_base=hub)
    manual_controller = manual or ManualController(hub_base=hub)

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
            if quiet:
                return
            print(f"{self.address_string()} {format % args}")

        def _api_get(self, path: str) -> None:
            parts = [part for part in path.split("/") if part]
            try:
                if parts == ["api", "agents"]:
                    self._json(200, {"agents": _agents_with_hub(hub)})
                    return
                if parts == ["api", "hub"]:
                    self._json(
                        200,
                        {
                            "configured": bool(hub),
                            "master_url": hub or None,
                        },
                    )
                    return
                if parts == ["api", "hub", "ping"]:
                    self._hub_ping()
                    return
                if parts == ["api", "hub", "agents"]:
                    self._hub_list()
                    return
                if (
                    len(parts) == 4
                    and parts[0] == "api"
                    and parts[1] == "hub"
                    and parts[2] == "agents"
                ):
                    self._hub_download(parts[3])
                    return
                if parts == ["api", "rules"]:
                    rules_path = ROOT / "RULES.md"
                    if not rules_path.is_file():
                        self._json(404, {"error": "rules not found"})
                        return
                    self._json(200, {"text": rules_path.read_text(encoding="utf-8")})
                    return
                if parts == ["api", "session"]:
                    self._json(200, controller.snapshot())
                    return
                if parts == ["api", "manual"]:
                    self._json(200, manual_controller.snapshot())
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
                    self._json(
                        200,
                        {
                            "run_id": run_id,
                            "rounds": rounds,
                            "agents": _read_roster(run_folder),
                        },
                    )
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
                    self._json(200, controller.start(body))
                    return
                if parts == ["api", "session", "stop"]:
                    self._json(200, controller.stop())
                    return
                if parts == ["api", "manual", "start"]:
                    self._json(200, manual_controller.start(body))
                    return
                if parts == ["api", "manual", "move"]:
                    self._json(200, manual_controller.move(body))
                    return
                if parts == ["api", "manual", "step"]:
                    self._json(200, manual_controller.step())
                    return
                if parts == ["api", "manual", "stop"]:
                    self._json(200, manual_controller.stop())
                    return
                if parts == ["api", "agents", "validate"]:
                    self._validate_agent(body)
                    return
                if parts == ["api", "hub", "upload"]:
                    self._hub_upload(body)
                    return
                if parts == ["api", "hub", "download"]:
                    self._hub_download_body(body)
                    return
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except json.JSONDecodeError:
                self._json(400, {"error": "invalid json"})
                return
            self._json(404, {"error": "not found"})

        def _require_hub(self) -> str:
            if not hub:
                raise ValueError("coup-master not configured (set COUP_MASTER_URL or --master-url)")
            return hub

        def _hub_ping(self) -> None:
            if not hub:
                self._json(
                    200,
                    {
                        "configured": False,
                        "ok": False,
                        "status": "offline",
                        "error": "coup-master not configured",
                    },
                )
                return
            try:
                result = ping_hub(hub, timeout=5.0)
            except HubError as exc:
                self._json(
                    200,
                    {
                        "configured": True,
                        "ok": False,
                        "status": "offline",
                        "error": str(exc),
                        "version": None,
                    },
                )
                return
            self._json(
                200,
                {
                    "configured": True,
                    "ok": True,
                    "status": "ready",
                    "version": result.get("version"),
                    "error": None,
                },
            )

        def _hub_list(self) -> None:
            try:
                base = self._require_hub()
                agents = list_remote_agents(base_url=base)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except HubError as exc:
                self._json(exc.status or 502, {"error": str(exc), "issues": exc.issues})
                return
            self._json(
                200,
                {
                    "agents": [
                        {
                            "name": a.name,
                            "sha256": a.sha256,
                            "size_bytes": a.size_bytes,
                            "uploaded_at": a.uploaded_at,
                            "uploader": a.uploader,
                            "full_name": a.full_name,
                        }
                        for a in agents
                    ]
                },
            )

        def _hub_download(self, name: str) -> None:
            if not SAFE_HUB_NAME.fullmatch(name):
                self._json(400, {"error": "invalid agent name"})
                return
            try:
                base = self._require_hub()
                dest = LOCAL / name / "agent.py"
                written = download_agent(name, dest, base_url=base)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except HubError as exc:
                self._json(exc.status or 502, {"error": str(exc), "issues": exc.issues})
                return
            self._json(200, {"name": name, "path": str(written.relative_to(ROOT))})

        def _hub_download_body(self, body: dict[str, Any]) -> None:
            name = body.get("name")
            if not isinstance(name, str) or not SAFE_HUB_NAME.fullmatch(name):
                raise ValueError("name must match [A-Za-z0-9_-]+")
            self._hub_download(name)

        def _validate_agent(self, body: dict[str, Any]) -> None:
            path = _resolve_agent_path(body)
            name = body.get("name")
            name_issues: list[str] = []
            if name is not None:
                if not isinstance(name, str):
                    raise ValueError("name must be a string")
                try:
                    validate_local_name(name)
                except HubError as exc:
                    name_issues.append(str(exc))
            games = int(body.get("games", DEFAULT_VALIDATE_GAMES))
            sandbox_games = int(body.get("sandbox_games", DEFAULT_VALIDATE_SANDBOX_GAMES))
            timeout = float(body.get("timeout", 1.0))
            if games < 1:
                raise ValueError("games must be >= 1")
            if sandbox_games < 0:
                raise ValueError("sandbox_games must be >= 0")
            if timeout <= 0:
                raise ValueError("timeout must be positive")
            report = evaluate(path, games=games, timeout=timeout, sandbox_games=sandbox_games)
            payload = report.as_dict()
            payload["agent"] = body.get("agent")
            payload["name"] = name
            payload["name_ok"] = not name_issues
            payload["name_issues"] = name_issues
            payload["safe"] = report.ready and not name_issues
            if name_issues:
                payload["ready"] = False
                payload["issues"] = [*name_issues, *payload["issues"]]
                payload["text"] = report.text() + "\n" + "\n".join(f"  - {item}" for item in name_issues)
            self._json(200, payload)

        def _hub_upload(self, body: dict[str, Any]) -> None:
            name = body.get("name")
            if not isinstance(name, str) or not SAFE_HUB_NAME.fullmatch(name):
                raise ValueError("name must match [A-Za-z0-9_-]+")
            try:
                validate_local_name(name)
            except HubError as exc:
                raise ValueError(str(exc)) from exc
            path = _resolve_agent_path(body, fallback_name=name)
            # Always re-run local safety + readiness (static allowlist, valid Agent,
            # legal play) before upload — clients cannot skip with require_ready=false.
            games = int(body.get("games", DEFAULT_VALIDATE_GAMES))
            sandbox_games = int(body.get("sandbox_games", DEFAULT_VALIDATE_SANDBOX_GAMES))
            timeout = float(body.get("timeout", 1.0))
            report = evaluate(path, games=games, timeout=timeout, sandbox_games=sandbox_games)
            if not report.ready:
                self._json(
                    400,
                    {
                        "error": "agent is not ready to submit",
                        "issues": report.issues
                        or [
                            f"illegal={report.illegal}",
                            f"errors={report.errors}",
                            f"timeouts={report.timeouts}",
                        ],
                        "report": report.as_dict(),
                    },
                )
                return
            base = self._require_hub()
            full_name = body.get("full_name", body.get("uploader"))
            if full_name is not None and not isinstance(full_name, str):
                raise ValueError("full_name must be a string")
            player_uid = body.get("player_uid")
            if player_uid is not None and not isinstance(player_uid, str):
                raise ValueError("player_uid must be a string")
            try:
                validate_full_name(full_name)
                validate_player_uid(player_uid)
            except HubError as exc:
                raise ValueError(str(exc)) from exc
            try:
                meta = upload_agent(
                    name,
                    path,
                    base_url=base,
                    full_name=full_name,
                    player_uid=player_uid,
                )
            except HubError as exc:
                self._json(exc.status or 502, {"error": str(exc), "issues": exc.issues})
                return
            self._json(
                201,
                {
                    "name": meta.name,
                    "sha256": meta.sha256,
                    "size_bytes": meta.size_bytes,
                    "uploaded_at": meta.uploaded_at,
                    "uploader": meta.uploader,
                    "full_name": meta.full_name,
                    "player_uid": meta.player_uid,
                },
            )

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

    return Handler


def make_server(
    *,
    host: str = "127.0.0.1",
    port: int = 0,
    results: Path,
    hub_base: str = "",
    session: SessionController | None = None,
    manual: ManualController | None = None,
    quiet: bool = False,
) -> ThreadingHTTPServer:
    handler = make_handler(
        results=results, hub_base=hub_base, session=session, manual=manual, quiet=quiet
    )
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    load_repo_dotenv()
    parser = argparse.ArgumentParser(description="Serve the Coup dashboard.")
    parser.add_argument("--results", type=Path, default=ROOT / "results")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--master-url",
        default=None,
        help="coup-master base URL (else COUP_MASTER_URL). Enables /api/hub/*.",
    )
    args = parser.parse_args()
    results = args.results.resolve()
    results.mkdir(parents=True, exist_ok=True)
    hub_base = (args.master_url or master_url() or "").rstrip("/")
    server = make_server(host=args.host, port=args.port, results=results, hub_base=hub_base)
    hub_note = hub_base or "(unset — /api/hub disabled)"
    print(f"dashboard http://{args.host}:{args.port}  results={results}  master={hub_note}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


def _resolve_agent_path(body: dict[str, Any], *, fallback_name: str | None = None) -> Path:
    """Resolve an upload/validate body to an on-disk agent.py under the repo."""

    agent = body.get("agent")
    path_raw = body.get("path")
    if agent is not None:
        if not isinstance(agent, str) or not SAFE_AGENT.fullmatch(agent):
            raise ValueError(f"invalid agent id: {agent!r}")
        try:
            path = resolve_agent(agent)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        return path
    if path_raw is not None:
        if not isinstance(path_raw, str):
            raise ValueError("path must be a string")
        path = Path(path_raw)
        if not path.is_file():
            path = ROOT / path_raw
        if not path.is_file():
            raise ValueError(f"file not found: {path_raw}")
        resolved = path.resolve()
        if not str(resolved).startswith(str(ROOT.resolve())):
            raise ValueError("path must be inside the coup-sandbox repo")
        return resolved
    if fallback_name:
        try:
            return resolve_agent(fallback_name)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
    raise ValueError("provide agent id or path")


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


def _agents_with_hub(hub_base: str) -> list[dict[str, str]]:
    """Examples + local + arena from coup-master only (not agents/submissions/).

    Namespaces are independent: local ``milo``, base ``guard``, and hub ``milo``
    can share a display name. Colliding local vs base uses ``local:<name>``;
    arena always uses ``arena:<name>``. Disk under ``agents/submissions/`` is a
    run-time cache after download — it does not populate The Arena catalog.
    """

    agents = list_available_agents()
    by_id = {row["id"]: dict(row) for row in agents}
    if hub_base:
        try:
            remote = list_remote_agents(base_url=hub_base, timeout=8.0)
        except HubError:
            remote = []
        for row in remote:
            name = row.name
            if not SAFE_HUB_NAME.fullmatch(name):
                continue
            owner = (row.full_name or row.uploader or "").strip()
            if not owner:
                # Hide hub agents that were uploaded without a person name.
                continue
            aid = arena_agent_id(name)
            by_id[aid] = {
                "id": aid,
                "name": name,
                "kind": "submission",
                "path": f"hub:{name}",
                "source": "hub",
                "full_name": owner,
            }
    # Preserve example order, then local, then arena (hub only).
    examples = [by_id[row["id"]] for row in agents if row["kind"] == "example" and row["id"] in by_id]
    locals_ = sorted(
        (row for row in by_id.values() if row.get("kind") == "local"),
        key=lambda row: row["name"],
    )
    submitted = sorted(
        (
            row
            for row in by_id.values()
            if row.get("kind") == "submission"
            and row.get("source") == "hub"
            and (row.get("full_name") or "").strip()
        ),
        key=lambda row: row["name"],
    )
    return [*examples, *locals_, *submitted]


def _ensure_agent(token: str, *, hub_base: str = "", refresh: bool = False) -> Path:
    """Resolve a catalog token to a file; download hub arena agents into submissions.

    Cached ``agents/submissions/<name>/agent.py`` is reused unless ``refresh`` is set,
    so starting a tournament does not re-hit the hub on every Run.
    """

    hub_name = arena_name(token)
    if hub_name is not None:
        if not SAFE_HUB_NAME.fullmatch(hub_name):
            raise FileNotFoundError(f"no agent {token!r}")
        dest = SUBMISSIONS / hub_name / "agent.py"
        if hub_base:
            if not refresh and dest.is_file() and dest.stat().st_size > 0:
                return dest
            try:
                return download_agent(hub_name, dest, base_url=hub_base)
            except HubError as exc:
                # Stale cache is better than failing mid-start when the hub blips.
                if dest.is_file() and dest.stat().st_size > 0:
                    return dest
                raise FileNotFoundError(f"no arena agent {hub_name!r} on hub: {exc}") from exc
        return resolve_agent(token)

    # Bare ids are local / examples / path only — never silently bind a hub name.
    return resolve_agent(token)


def _parse_manual_config(payload: dict[str, Any], *, hub_base: str = "") -> dict[str, Any]:
    agents = payload.get("agents")
    if not isinstance(agents, list) or not agents:
        raise ValueError("pick at least 1 agent opponent")
    if len(agents) > 5:
        raise ValueError("at most 5 agent opponents")
    cleaned: list[str] = []
    paths: list[Path] = []
    for item in agents:
        if not isinstance(item, str) or not SAFE_AGENT.fullmatch(item):
            raise ValueError(f"invalid agent id: {item!r}")
        if item in cleaned:
            raise ValueError(f"duplicate agent {item!r}")
        try:
            path = _ensure_agent(item, hub_base=hub_base)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        cleaned.append(item)
        paths.append(path)
    seat_names = unique_instance_names([display_name_for_token(item) for item in cleaned])
    if "You" in seat_names or "You" in cleaned:
        raise ValueError("agent id You is reserved for the human player")
    seed_raw = payload.get("seed", None)
    if seed_raw is None or seed_raw == "":
        seed = random.randrange(1, 2**31)
    else:
        seed = int(seed_raw)
    timeout = float(payload.get("timeout", 1.0))
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    return {
        "agents": cleaned,
        "paths": paths,
        "seat_names": seat_names,
        "seed": seed,
        "timeout": timeout,
    }


def _parse_session_config(payload: dict[str, Any], *, hub_base: str = "") -> dict[str, Any]:
    agents = payload.get("agents")
    if not isinstance(agents, list) or len(agents) < 2:
        raise ValueError("select at least 2 agents")
    cleaned_agents: list[str] = []
    paths: list[Path] = []
    for item in agents:
        if not isinstance(item, str) or not SAFE_AGENT.fullmatch(item):
            raise ValueError(f"invalid agent id: {item!r}")
        try:
            path = _ensure_agent(item, hub_base=hub_base)
        except FileNotFoundError as exc:
            raise ValueError(str(exc)) from exc
        cleaned_agents.append(item)
        paths.append(path)

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
        "paths": paths,
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


def _write_roster(run_folder: Path, agents: list[str]) -> None:
    """Persist catalog agent tokens so Another round can rebuild the field after restart."""

    run_folder.mkdir(parents=True, exist_ok=True)
    payload = {"agents": list(agents)}
    (run_folder / "roster.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )


def _read_roster(run_folder: Path) -> list[str]:
    raw = _read_json(run_folder / "roster.json")
    if not isinstance(raw, dict):
        return []
    agents = raw.get("agents")
    if not isinstance(agents, list):
        return []
    return [item for item in agents if isinstance(item, str) and item]


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
                "agents": _read_roster(folder),
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
