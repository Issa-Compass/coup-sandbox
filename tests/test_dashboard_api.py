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


@pytest.fixture()
def dashboard_with_hub(tmp_path: Path):
    uploads: list[dict] = []

    class Master(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
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
                                "sha256": "b" * 64,
                                "size_bytes": 10,
                                "uploaded_at": "2026-01-01T00:00:00+00:00",
                                "uploader": "Ada Lovelace",
                                "full_name": "Ada Lovelace",
                                "status": "approved",
                            },
                            {
                                "name": "no_owner_bot",
                                "sha256": "c" * 64,
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
                data = GOOD.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/x-python")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_error(404)

        def do_POST(self):  # noqa: N802
            if self.path != "/v1/agents":
                self.send_error(404)
                return
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            text = raw.decode("utf-8", errors="replace")

            def _form_field(field: str) -> str | None:
                marker = f'name="{field}"'
                if marker not in text:
                    return None
                after = text.split(marker, 1)[1]
                return after.split("\r\n\r\n", 1)[1].split("\r\n", 1)[0]

            name = _form_field("name") or "uploaded"
            person = _form_field("full_name") or self.headers.get("X-Uploader")
            uploads.append({"raw": raw, "uploader": person})
            body = json.dumps(
                {
                    "name": name,
                    "sha256": "a" * 64,
                    "size_bytes": 12,
                    "uploaded_at": "2026-01-01T00:00:00+00:00",
                    "uploader": person,
                    "full_name": person,
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
        yield base, uploads, master_url
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
    base, _uploads, _master_url = dashboard_with_hub
    status, body = _get(base, "/api/hub/ping")
    assert status == 200
    assert body["configured"] is True
    assert body["ok"] is True
    assert body["status"] == "ready"
    assert body["version"] == "test"


def test_agents_include_hub_submissions(dashboard_with_hub):
    base, _uploads, _master_url = dashboard_with_hub
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

    base, _uploads, _master_url = dashboard_with_hub
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
    base, uploads, _ = dashboard_with_hub
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
    base, uploads, _ = dashboard_with_hub
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
    base, uploads, master_url = dashboard_with_hub
    status, hub = _get(base, "/api/hub")
    assert status == 200
    assert hub["configured"] is True
    assert hub["master_url"] == master_url

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
        },
    )
    assert status == 201, body
    assert body["name"] == "Milo_1"
    assert body["full_name"] == "Ada Lovelace"
    assert len(uploads) == 1
    assert uploads[0]["uploader"] == "Ada Lovelace"


def test_upload_requires_full_name(dashboard_with_hub):
    base, uploads, _ = dashboard_with_hub
    status, body = _post(
        base,
        "/api/hub/upload",
        {
            "agent": "template",
            "name": "NoPerson",
            "require_ready": True,
            "games": 5,
            "sandbox_games": 1,
        },
    )
    assert status == 400
    assert "first and last name" in body["error"].lower()
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


def test_ensure_agent_reuses_hub_cache(dashboard_with_hub, tmp_path, monkeypatch):
    """Arena downloads hit the hub once; later resolves use the on-disk cache."""
    _base, _uploads, master_url = dashboard_with_hub
    import coup.runner.catalog as catalog

    submissions = tmp_path / "submissions"
    monkeypatch.setattr(catalog, "SUBMISSIONS", submissions)
    monkeypatch.setattr(dash, "SUBMISSIONS", submissions)

    calls: list[str] = []
    real_download = dash.download_agent

    def counting_download(name, dest, **kwargs):
        calls.append(name)
        return real_download(name, dest, **kwargs)

    monkeypatch.setattr(dash, "download_agent", counting_download)

    path1 = dash._ensure_agent("arena:hub_bot", hub_base=master_url)
    path2 = dash._ensure_agent("arena:hub_bot", hub_base=master_url)
    path3 = dash._ensure_agent("arena:hub_bot", hub_base=master_url, refresh=True)

    assert path1 == path2 == path3
    assert path1.is_file()
    assert calls == ["hub_bot", "hub_bot"]  # cold + refresh; middle call cached


def test_session_start_uses_cached_paths_not_redownload(dashboard_with_hub, tmp_path, monkeypatch):
    """Session start resolves agents once; the worker must not download again."""
    base, _uploads, master_url = dashboard_with_hub
    import coup.runner.catalog as catalog

    submissions = tmp_path / "submissions"
    monkeypatch.setattr(catalog, "SUBMISSIONS", submissions)
    monkeypatch.setattr(dash, "SUBMISSIONS", submissions)

    # Seed cache so start does not need the hub for hub_bot.
    cached = submissions / "hub_bot" / "agent.py"
    cached.parent.mkdir(parents=True)
    cached.write_text(GOOD, encoding="utf-8")

    calls: list[str] = []

    def counting_download(name, dest, **kwargs):
        calls.append(name)
        raise AssertionError("download_agent should not run when cache exists")

    monkeypatch.setattr(dash, "download_agent", counting_download)

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
            "run_id": "cache-session-test",
        },
    )
    assert status == 200, body
    for _ in range(100):
        _st, snap = _get(base, "/api/session")
        if snap["status"] != "running":
            break
        import time

        time.sleep(0.05)
    assert snap["status"] == "done", snap
    assert calls == []


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
