"""Dashboard HTTP API: agent validate + hub submit."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import serve_dashboard as dash  # noqa: E402

GOOD = (ROOT / "agents" / "template" / "agent.py").read_text(encoding="utf-8")
UNSAFE = "import socket\n" + GOOD


@pytest.fixture()
def dashboard(tmp_path: Path):
    results = tmp_path / "results"
    server = dash.make_server(results=results, hub_base="", quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base = f"http://{host}:{port}"
    try:
        yield base, results
    finally:
        server.shutdown()
        server.server_close()


HUB_AGENTS = {"hub_bot", "slow_bot"}


def _fake_decision(agent: str, request: dict) -> dict:
    """What the hub returns for one act: a decision, never the agent file."""

    from coup.agent_api import Pass, default_action, default_exchange, default_loss
    from coup.serialize import from_data, to_data

    if agent == "slow_bot" and request["method"] not in ("on_game_start", "on_game_end"):
        return {"ok": False, "status": "timeout", "error": "timeout"}
    method = request["method"]
    if method in ("on_game_start", "on_game_end"):
        return {"ok": True, "result": None}
    view = from_data(request["view"])
    if method == "choose_action":
        result = default_action(view)
    elif method in ("respond_to_action", "respond_to_block"):
        result = Pass()
    elif method == "choose_card_to_lose":
        result = default_loss(view)
    elif method == "choose_exchange":
        result = default_exchange(view)
    else:
        return {"ok": False, "status": "error", "error": "unknown method"}
    return {"ok": True, "result": to_data(result)}


@pytest.fixture()
def dashboard_with_hub(tmp_path: Path):
    uploads: list[dict] = []
    requests: list[str] = []
    sessions: dict[str, list[str]] = {}

    class Master(BaseHTTPRequestHandler):
        def _send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_DELETE(self):  # noqa: N802
            requests.append(f"DELETE {self.path}")
            sessions.pop(self.path.rsplit("/", 1)[-1], None)
            self.send_response(204)
            self.end_headers()

        def do_GET(self):  # noqa: N802
            requests.append(f"GET {self.path}")
            if self.path == "/health":
                body = json.dumps({"status": "ok", "version": "test"}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/v1/agents":
                body = json.dumps(
                    {
                        "agents": [
                            {
                                "name": "hub_bot",
                                "size_bytes": 10,
                                "uploaded_at": "2026-01-01T00:00:00+00:00",
                                "uploader": "Ada Lovelace",
                                "full_name": "Ada Lovelace",
                                "status": "approved",
                            },
                            {
                                "name": "no_owner_bot",
                                "size_bytes": 10,
                                "uploaded_at": "2026-01-01T00:00:00+00:00",
                                "uploader": None,
                                "full_name": None,
                                "status": "approved",
                            },
                        ]
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/v1/agents/hub_bot":
                self._send_json(
                    200,
                    {
                        "name": "hub_bot",
                        "size_bytes": 10,
                        "uploaded_at": "2026-01-01T00:00:00+00:00",
                        "full_name": "Ada Lovelace",
                        "status": "approved",
                    },
                )
                return
            self.send_error(404)

        def do_POST(self):  # noqa: N802
            requests.append(f"POST {self.path}")
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            if self.path == "/v1/sessions":
                names = json.loads(raw)["agents"]
                if any(name not in HUB_AGENTS for name in names):
                    self._send_json(404, {"detail": {"error": "agent not found"}})
                    return
                session_id = f"s{len(sessions) + 1}"
                sessions[session_id] = names
                self._send_json(201, {"session_id": session_id, "agents": names})
                return
            if self.path.startswith("/v1/sessions/") and self.path.endswith("/act"):
                session_id = self.path.split("/")[3]
                if session_id not in sessions:
                    self._send_json(404, {"detail": {"error": "play session not found"}})
                    return
                request = json.loads(raw)
                agent = sessions[session_id][request.get("seat", 0)]
                self._send_json(200, _fake_decision(agent, request))
                return
            if self.path != "/v1/agents":
                self.send_error(404)
                return
            text = raw.decode("utf-8", errors="replace")

            def _form_field(field: str) -> str | None:
                marker = f'name="{field}"'
                if marker not in text:
                    return None
                after = text.split(marker, 1)[1]
                return after.split("\r\n\r\n", 1)[1].split("\r\n", 1)[0]

            name = _form_field("name") or "uploaded"
            person = _form_field("full_name") or self.headers.get("X-Uploader")
            player_uid = _form_field("player_uid")
            uploads.append({"raw": raw, "uploader": person, "player_uid": player_uid})
            body = json.dumps(
                {
                    "name": name,
                    "sha256": "a" * 64,
                    "size_bytes": 12,
                    "uploaded_at": "2026-01-01T00:00:00+00:00",
                    "uploader": person,
                    "full_name": person,
                    "player_uid": player_uid,
                }
            ).encode()
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # noqa: A003
            return

    master = ThreadingHTTPServer(("127.0.0.1", 0), Master)
    master_thread = threading.Thread(target=master.serve_forever, daemon=True)
    master_thread.start()
    master_url = f"http://127.0.0.1:{master.server_address[1]}"

    results = tmp_path / "results"
    server = dash.make_server(results=results, hub_base=master_url, quiet=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, uploads, master_url, requests
    finally:
        server.shutdown()
        server.server_close()
        master.shutdown()
        master.server_close()


def _post(base: str, path: str, payload: dict) -> tuple[int, dict]:
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        return exc.code, json.loads(body) if body else {"error": str(exc)}


def _get(base: str, path: str) -> tuple[int, dict]:
    import urllib.request

    with urllib.request.urlopen(f"{base}{path}", timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode())


def test_player_uid_endpoint(dashboard, tmp_path, monkeypatch):
    player_file = tmp_path / ".coup-player.json"
    monkeypatch.setattr("coup.hub_client.PLAYER_FILE", player_file)
    base, _ = dashboard
    assert not player_file.is_file()
    status, body = _get(base, "/api/player")
    assert status == 200
    uid = body["player_uid"]
    assert uid.startswith("p_")
    assert player_file.is_file()
    status2, body2 = _get(base, "/api/player")
    assert status2 == 200
    assert body2["player_uid"] == uid


def test_hub_status_unconfigured(dashboard):
    base, _ = dashboard
    status, body = _get(base, "/api/hub")
    assert status == 200
    assert body["configured"] is False


def test_hub_ping_unconfigured(dashboard):
    base, _ = dashboard
    status, body = _get(base, "/api/hub/ping")
    assert status == 200
    assert body["configured"] is False
    assert body["ok"] is False
    assert body["status"] == "offline"


def test_hub_ping_ready(dashboard_with_hub):
    base, _uploads, _master_url, _requests = dashboard_with_hub
    status, body = _get(base, "/api/hub/ping")
    assert status == 200
    assert body["configured"] is True
    assert body["ok"] is True
    assert body["status"] == "ready"
    assert body["version"] == "test"


def test_agents_include_hub_submissions(dashboard_with_hub):
    base, _uploads, _master_url, _requests = dashboard_with_hub
    status, body = _get(base, "/api/agents")
    assert status == 200
    by_id = {row["id"]: row for row in body["agents"]}
    assert by_id["arena:hub_bot"]["kind"] == "submission"
    assert by_id["arena:hub_bot"]["name"] == "hub_bot"
    assert by_id["arena:hub_bot"]["source"] == "hub"
    assert by_id["arena:hub_bot"]["full_name"] == "Ada Lovelace"
    assert "hub_bot" not in by_id
    assert "arena:no_owner_bot" not in by_id
    assert "no_owner_bot" not in by_id
    assert by_id["random"]["kind"] == "example"


def test_hub_and_local_same_name_coexist(dashboard_with_hub, tmp_path, monkeypatch):
    """Local folder hub_bot must stay selectable when hub also has hub_bot."""
    import coup.runner.catalog as catalog

    local_root = tmp_path / "local"
    bot = local_root / "hub_bot" / "agent.py"
    bot.parent.mkdir(parents=True)
    bot.write_text(GOOD, encoding="utf-8")
    # Keep catalog.ROOT as the real repo so example paths still relativize.
    monkeypatch.setattr(catalog, "LOCAL", local_root)
    monkeypatch.setattr(catalog, "SUBMISSIONS", tmp_path / "submissions")

    base, _uploads, _master_url, _requests = dashboard_with_hub
    status, body = _get(base, "/api/agents")
    assert status == 200
    by_id = {row["id"]: row for row in body["agents"]}
    assert by_id["hub_bot"]["kind"] == "local"
    assert by_id["hub_bot"]["name"] == "hub_bot"
    assert by_id["arena:hub_bot"]["kind"] == "submission"
    assert by_id["arena:hub_bot"]["source"] == "hub"
    assert by_id["arena:hub_bot"]["name"] == "hub_bot"


def test_base_and_local_same_name_coexist(dashboard, tmp_path, monkeypatch):
    """Local folder reusing a base alias stays selectable as local:<name>."""
    import coup.runner.catalog as catalog

    local_root = tmp_path / "local"
    bot = local_root / "guard" / "agent.py"
    bot.parent.mkdir(parents=True)
    bot.write_text(GOOD, encoding="utf-8")
    monkeypatch.setattr(catalog, "LOCAL", local_root)
    monkeypatch.setattr(catalog, "SUBMISSIONS", tmp_path / "submissions")

    base, _ = dashboard
    status, body = _get(base, "/api/agents")
    assert status == 200
    by_id = {row["id"]: row for row in body["agents"]}
    assert by_id["guard"]["kind"] == "example"
    assert by_id["local:guard"]["kind"] == "local"
    assert by_id["local:guard"]["name"] == "guard"


def test_validate_template_ready(dashboard):
    base, _ = dashboard
    status, body = _post(
        base,
        "/api/agents/validate",
        {"agent": "template", "name": "Milo_1", "games": 5, "sandbox_games": 1},
    )
    assert status == 200
    assert body["ready"] is True
    assert body["safe"] is True
    assert body["name_ok"] is True
    assert body["illegal"] == 0
    assert "READY" in body["text"]


def test_validate_rejects_bad_name(dashboard):
    base, _ = dashboard
    status, body = _post(
        base,
        "/api/agents/validate",
        {"agent": "template", "name": "bad name", "games": 5, "sandbox_games": 0},
    )
    assert status == 200
    assert body["ready"] is False
    assert body["name_ok"] is False
    assert body["safe"] is False
    assert any("A–Z" in issue or "name" in issue.lower() for issue in body["issues"])


def test_validate_rejects_unsafe_source(dashboard, tmp_path: Path):
    base, _ = dashboard
    path = ROOT / "tests" / "_unsafe_validate_agent.py"
    path.write_text(UNSAFE, encoding="utf-8")
    try:
        status, body = _post(
            base,
            "/api/agents/validate",
            {"path": str(path.relative_to(ROOT)), "games": 1, "sandbox_games": 0},
        )
        assert status == 200
        assert body["ready"] is False
        assert any("socket" in issue for issue in body["issues"])
    finally:
        path.unlink(missing_ok=True)


def test_upload_requires_hub(dashboard):
    base, _ = dashboard
    status, body = _post(
        base,
        "/api/hub/upload",
        {
            "agent": "template",
            "name": "Milo_1",
            "games": 5,
            "sandbox_games": 0,
        },
    )
    assert status == 400
    assert "coup-master" in body["error"]


def test_upload_rejects_not_ready(dashboard_with_hub, tmp_path: Path):
    base, uploads, _, _requests = dashboard_with_hub
    path = ROOT / "tests" / "_unsafe_upload_agent.py"
    path.write_text(UNSAFE, encoding="utf-8")
    try:
        status, body = _post(
            base,
            "/api/hub/upload",
            {
                "path": str(path.relative_to(ROOT)),
                "name": "HackerBot",
                "require_ready": True,
                "games": 1,
                "sandbox_games": 0,
            },
        )
        assert status == 400
        assert "not ready" in body["error"]
        assert uploads == []
    finally:
        path.unlink(missing_ok=True)


def test_upload_cannot_skip_ready_check(dashboard_with_hub, tmp_path: Path):
    """require_ready=false must not bypass safety + readiness."""
    base, uploads, _, _requests = dashboard_with_hub
    path = ROOT / "tests" / "_unsafe_skip_ready_agent.py"
    path.write_text(UNSAFE, encoding="utf-8")
    try:
        status, body = _post(
            base,
            "/api/hub/upload",
            {
                "path": str(path.relative_to(ROOT)),
                "name": "SkipBot",
                "require_ready": False,
                "games": 1,
                "sandbox_games": 0,
            },
        )
        assert status == 400
        assert "not ready" in body["error"]
        assert uploads == []
    finally:
        path.unlink(missing_ok=True)


def test_upload_after_ready(dashboard_with_hub):
    base, uploads, master_url, _requests = dashboard_with_hub
    status, hub = _get(base, "/api/hub")
    assert status == 200
    assert hub["configured"] is True
    assert hub["master_url"] == master_url

    uid = "p_" + ("a" * 24)
    status, body = _post(
        base,
        "/api/hub/upload",
        {
            "agent": "template",
            "name": "Milo_1",
            "require_ready": True,
            "games": 5,
            "sandbox_games": 1,
            "full_name": "Ada Lovelace",
            "player_uid": uid,
        },
    )
    assert status == 201, body
    assert body["name"] == "Milo_1"
    assert body["full_name"] == "Ada Lovelace"
    assert body["player_uid"] == uid
    assert len(uploads) == 1
    assert uploads[0]["uploader"] == "Ada Lovelace"
    assert uploads[0]["player_uid"] == uid


def test_upload_requires_full_name(dashboard_with_hub):
    base, uploads, _, _requests = dashboard_with_hub
    status, body = _post(
        base,
        "/api/hub/upload",
        {
            "agent": "template",
            "name": "NoPerson",
            "require_ready": True,
            "games": 5,
            "sandbox_games": 1,
            "player_uid": "p_" + ("b" * 24),
        },
    )
    assert status == 400
    assert "first and last name" in body["error"].lower()
    assert uploads == []


def test_upload_requires_player_uid(dashboard_with_hub):
    base, uploads, _, _requests = dashboard_with_hub
    status, body = _post(
        base,
        "/api/hub/upload",
        {
            "agent": "template",
            "name": "NoUid",
            "require_ready": True,
            "games": 5,
            "sandbox_games": 1,
            "full_name": "Ada Lovelace",
        },
    )
    assert status == 400
    assert "player_uid" in body["error"].lower()
    assert uploads == []


def test_session_start_and_reject_concurrent(dashboard):
    base, results = dashboard
    status, body = _post(
        base,
        "/api/session/start",
        {
            "agents": ["random", "honest"],
            "rounds": [{"number": 1, "games_per_agent": 40}],
            "seed": 7,
            "timeout": 1,
            "table_size": 2,
            "sandbox": False,
            "force": True,
            "run_id": "api-session-test",
        },
    )
    assert status == 200, body
    assert body["status"] == "running"
    assert body["run_id"] == "api-session-test"

    status2, body2 = _post(
        base,
        "/api/session/start",
        {
            "agents": ["random", "bluffer"],
            "rounds": [{"number": 1, "games_per_agent": 1}],
            "seed": 1,
            "force": True,
            "run_id": "api-session-test-2",
        },
    )
    assert status2 == 400
    assert "already running" in body2["error"]

    # Wait for the long-ish round to finish (or stop it).
    _post(base, "/api/session/stop", {})
    for _ in range(100):
        status, snap = _get(base, "/api/session")
        assert status == 200
        if snap["status"] != "running":
            break
        import time

        time.sleep(0.05)
    assert snap["status"] in ("stopped", "done", "error"), snap
    assert (results / "api-session-test").is_dir() or snap["status"] == "stopped"


def test_session_start_writes_roster_and_run_api_returns_it(dashboard):
    """Another round needs durable catalog tokens — not standings seat names."""
    base, results = dashboard
    agents = ["random", "honest", "guard"]
    status, body = _post(
        base,
        "/api/session/start",
        {
            "agents": agents,
            "rounds": [{"number": 1, "games_per_agent": 1}],
            "seed": 11,
            "timeout": 1,
            "table_size": 3,
            "sandbox": False,
            "force": True,
            "run_id": "roster-persist-test",
        },
    )
    assert status == 200, body

    roster_path = results / "roster-persist-test" / "roster.json"
    assert roster_path.is_file()
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    assert roster["agents"] == agents

    for _ in range(100):
        _st, snap = _get(base, "/api/session")
        if snap["status"] != "running":
            break
        import time

        time.sleep(0.05)
    assert snap["status"] == "done", snap

    status, meta = _get(base, "/api/runs/roster-persist-test")
    assert status == 200, meta
    assert meta["run_id"] == "roster-persist-test"
    assert meta["agents"] == agents
    assert 1 in meta["rounds"]

    status, listing = _get(base, "/api/runs")
    assert status == 200
    row = next(run for run in listing["runs"] if run["id"] == "roster-persist-test")
    assert row["agents"] == agents

    # Second round reuses the same roster tokens (simulates Another round after restart).
    status, body2 = _post(
        base,
        "/api/session/start",
        {
            "agents": meta["agents"],
            "rounds": [{"number": 2, "games_per_agent": 1}],
            "seed": 12,
            "timeout": 1,
            "table_size": 3,
            "sandbox": False,
            "force": True,
            "run_id": "roster-persist-test",
        },
    )
    assert status == 200, body2
    for _ in range(100):
        _st, snap2 = _get(base, "/api/session")
        if snap2["status"] != "running":
            break
        import time

        time.sleep(0.05)
    assert snap2["status"] == "done", snap2
    assert json.loads(roster_path.read_text(encoding="utf-8"))["agents"] == agents
    status, meta2 = _get(base, "/api/runs/roster-persist-test")
    assert status == 200
    assert meta2["agents"] == agents
    assert meta2["rounds"] == [1, 2]


def test_read_roster_empty_without_file(tmp_path: Path):
    assert dash._read_roster(tmp_path / "missing-run") == []
    empty = tmp_path / "empty-run"
    empty.mkdir()
    assert dash._read_roster(empty) == []


def _no_agent_files(root: Path) -> list[Path]:
    return sorted(root.rglob("agent.py")) if root.exists() else []


def _assert_no_source_fetch(requests: list[str]) -> None:
    for line in requests:
        assert not line.startswith("GET /v1/agents/"), line
        assert "/v1/admin/" not in line, line


def test_ensure_agent_plays_arena_remotely(dashboard_with_hub, tmp_path, monkeypatch):
    """Arena tokens become a hub seat; nothing is downloaded or cached."""
    _base, _uploads, master_url, requests = dashboard_with_hub
    import coup.runner.catalog as catalog
    from coup.runner.players import RemoteAgentRef

    monkeypatch.setattr(catalog, "LOCAL", tmp_path / "local")
    monkeypatch.setattr(catalog, "SUBMISSIONS", tmp_path / "submissions")

    ref = dash._ensure_agent("arena:hub_bot", hub_base=master_url)
    assert ref == RemoteAgentRef(name="hub_bot", hub_base=master_url)
    assert _no_agent_files(tmp_path) == []
    assert requests == []


def test_session_with_arena_agent_writes_no_file(dashboard_with_hub, tmp_path, monkeypatch):
    base, _uploads, _master_url, requests = dashboard_with_hub
    import coup.runner.catalog as catalog

    monkeypatch.setattr(catalog, "LOCAL", tmp_path / "local")
    monkeypatch.setattr(catalog, "SUBMISSIONS", tmp_path / "submissions")

    status, body = _post(
        base,
        "/api/session/start",
        {
            "agents": ["arena:hub_bot", "random"],
            "rounds": [{"number": 1, "games_per_agent": 1}],
            "seed": 3,
            "timeout": 1,
            "table_size": 2,
            "sandbox": False,
            "force": True,
            "run_id": "remote-session-test",
        },
    )
    assert status == 200, body
    for _ in range(200):
        _st, snap = _get(base, "/api/session")
        if snap["status"] != "running":
            break
        import time

        time.sleep(0.05)
    assert snap["status"] == "done", snap
    assert _no_agent_files(tmp_path / "local") == []
    assert _no_agent_files(tmp_path / "submissions") == []
    assert "POST /v1/sessions" in requests
    assert any(line.endswith("/act") for line in requests)
    assert any(line.startswith("DELETE /v1/sessions/") for line in requests)
    _assert_no_source_fetch(requests)

    summary = json.loads(
        (tmp_path / "results" / "remote-session-test" / "round_1" / "summary.json").read_text()
    )
    hub_row = next(row for row in summary["agents"] if row["name"] == "hub_bot")
    assert hub_row["errors"] == 0
    assert hub_row["timeouts"] == 0
    assert hub_row["decisions"] > 0


def test_remote_player_counts_hub_timeouts(dashboard_with_hub):
    _base, _uploads, master_url, requests = dashboard_with_hub
    from coup.runner.match import play_game
    from coup.runner.players import RemoteAgentRef, open_player

    remote = open_player(
        RemoteAgentRef(name="slow_bot", hub_base=master_url), "slow_bot", sandbox=False, timeout=1.0
    )
    local = open_player(ROOT / "agents" / "examples" / "random_bot.py", "random", False, 1.0)
    try:
        played = play_game([remote, local], seed=4)
    finally:
        remote.close()
        local.close()
    assert played.result.winner in (0, 1)
    assert played.penalties["slow_bot"]["timeouts"] > 0
    assert played.penalties["slow_bot"]["errors"] == 0
    _assert_no_source_fetch(requests)


def test_remote_player_unknown_agent_falls_back(dashboard_with_hub):
    _base, _uploads, master_url, _requests = dashboard_with_hub
    from coup.runner.match import play_game
    from coup.runner.players import RemoteAgentRef, open_player

    remote = open_player(
        RemoteAgentRef(name="missing_bot", hub_base=master_url), "missing_bot", False, 1.0
    )
    local = open_player(ROOT / "agents" / "examples" / "random_bot.py", "random", False, 1.0)
    try:
        played = play_game([remote, local], seed=5)
    finally:
        local.close()
    assert played.penalties["missing_bot"]["errors"] > 0
    assert "not found" in (remote.load_error or "")


def test_hub_download_routes_removed(dashboard_with_hub):
    base, _uploads, _master_url, requests = dashboard_with_hub
    import urllib.error
    import urllib.request

    with pytest.raises(urllib.error.HTTPError) as got:
        urllib.request.urlopen(f"{base}/api/hub/agents/hub_bot", timeout=10)
    assert got.value.code == 404
    status, _body = _post(base, "/api/hub/download", {"name": "hub_bot"})
    assert status == 404
    _assert_no_source_fetch(requests)


def test_game_route_never_serves_hands(dashboard):
    base, results = dashboard
    games = results / "hands-run" / "round_1" / "games"
    games.mkdir(parents=True)
    header = {"type": "game", "id": "g0001", "seed": 1, "players": ["a", "b"], "max_turns": 200}
    event = {
        "type": "event",
        "message": "start",
        "turn": 0,
        "state": {"players": [{"name": "a", "coins": 2, "influence": 2, "revealed": [], "hand": ["duke", "captain"]}]},
    }
    # An older log that still stores hands inline, plus the organizer sibling.
    for name in ("g0001.jsonl", "g0001.hands.jsonl"):
        (games / name).write_text(
            json.dumps(header) + "\n" + json.dumps(event) + "\n", encoding="utf-8"
        )

    status, listing = _get(base, "/api/runs/hands-run/rounds/1/games")
    assert status == 200
    assert [game["id"] for game in listing["games"]] == ["g0001"]

    status, body = _get(base, "/api/runs/hands-run/rounds/1/games/g0001")
    assert status == 200
    for line in body["lines"]:
        for player in (line.get("state") or {}).get("players", []):
            assert "hand" not in player
    assert "duke" not in json.dumps(body)


def test_manual_play_human_vs_agents(dashboard):
    base, _ = dashboard
    status, idle = _get(base, "/api/manual")
    assert status == 200
    assert idle["status"] == "idle"

    status, snap = _post(
        base,
        "/api/manual/start",
        {"agents": ["random", "honest"], "seed": 1, "timeout": 1},
    )
    assert status == 200, snap
    assert snap["status"] == "waiting"
    assert snap["human_name"] == "You"
    assert snap["prompt"]["kind"] == "choose_action"
    assert snap["view"]["your_cards"]

    # Always Pass / Income-prefer; step agents one decision at a time (paced UI path).
    for _ in range(200):
        if snap["status"] == "finished":
            break
        if snap["status"] == "thinking":
            status, snap = _post(base, "/api/manual/step", {})
            assert status == 200, snap
            continue
        assert snap["status"] == "waiting", snap
        kind = snap["prompt"]["kind"]
        if kind == "choose_action":
            acts = snap["view"]["legal_actions"]
            pick = next((a for a in acts if a["type"] == "income"), acts[0])
            status, snap = _post(base, "/api/manual/move", pick)
        elif kind in ("respond_to_action", "respond_to_block"):
            status, snap = _post(base, "/api/manual/move", {"type": "pass"})
        elif kind == "choose_card_to_lose":
            status, snap = _post(base, "/api/manual/move", {"card": snap["view"]["your_cards"][0]})
        elif kind == "choose_exchange":
            need = len(snap["view"]["your_cards"])
            pool = snap["view"]["your_cards"] + snap["view"]["drawn"]
            status, snap = _post(base, "/api/manual/move", {"keep": pool[:need]})
        else:
            raise AssertionError(kind)
        assert status == 200, snap

    assert snap["status"] == "finished", snap
    assert snap["result"]["winner_name"]
    status, stopped = _post(base, "/api/manual/stop", {})
    assert status == 200
    assert stopped["status"] == "idle"
