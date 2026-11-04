"""HTTP client for the shared Coup master submission hub."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
NAME_MIN = 1
NAME_MAX = 64
FULL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z'-]*(?: [A-Za-z][A-Za-z'-]*)+$")
FULL_NAME_MIN = 3
FULL_NAME_MAX = 128
RESERVED_NAMES = {
    "template",
    "random",
    "honest",
    "bluffer",
    "challenger",
    "guard",
    "turtle",
    "greedy",
    "master",
    "sandbox",
    "admin",
    "api",
    "health",
}
DEFAULT_TIMEOUT = 30.0
REPO_ROOT = Path(__file__).resolve().parents[1]


def load_repo_dotenv(path: Path | None = None) -> None:
    """Load KEY=VALUE from the repo `.env` without overriding existing env vars."""

    env_path = Path(path) if path is not None else REPO_ROOT / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ[key] = value


@dataclass(frozen=True)
class HubAgent:
    name: str
    sha256: str
    size_bytes: int
    uploaded_at: str
    uploader: str | None = None
    full_name: str | None = None
    status: str = "approved"
    approved_at: str | None = None


class HubError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, issues: list[str] | None = None):
        super().__init__(message)
        self.status = status
        self.issues = issues or []


def master_url() -> str:
    return os.environ.get("COUP_MASTER_URL", "").strip().rstrip("/")


def require_master_url() -> str:
    url = master_url()
    if not url:
        raise HubError("set COUP_MASTER_URL to the coup-master base URL")
    return url


def _api_key(api_key: str | None = None) -> str:
    key = api_key if api_key is not None else os.environ.get("COUP_MASTER_API_KEY", "").strip()
    if not key:
        raise HubError("set COUP_MASTER_API_KEY for this hub command")
    return key


def validate_local_name(name: str) -> None:
    """Raise HubError when the Coup AI name would be rejected by coup-master."""

    if not name:
        raise HubError("pick a name for your Coup AI")
    if len(name) < NAME_MIN or len(name) > NAME_MAX:
        raise HubError(f"Coup AI name must be {NAME_MIN}–{NAME_MAX} characters")
    if not NAME_RE.fullmatch(name):
        raise HubError("Coup AI name: letters, numbers, underscore, and hyphen only — no spaces")
    if name.lower() in RESERVED_NAMES:
        raise HubError(f"Coup AI name {name!r} is reserved — pick another")
    if name.startswith("-") or name.endswith("-") or name.startswith("_") or name.endswith("_"):
        raise HubError("Coup AI name must not start or end with _ or -")


def validate_full_name(value: str | None) -> None:
    """Raise HubError when the person's full name would be rejected by coup-master."""

    if value is None or not str(value).strip():
        raise HubError("enter your first and last name (e.g. Ada Lovelace)")
    text = " ".join(str(value).strip().split())
    if len(text) < FULL_NAME_MIN or len(text) > FULL_NAME_MAX:
        raise HubError(f"use {FULL_NAME_MIN}–{FULL_NAME_MAX} characters for your full name")
    parts = text.split(" ")
    if len(parts) < 2:
        # One token: underscore/digits → charset tip; plain "Ada" → ask for last name.
        if not re.fullmatch(r"[A-Za-z][A-Za-z'-]*", parts[0]):
            raise HubError("full name: letters, spaces, apostrophes, and hyphens only")
        raise HubError("add your last name too (e.g. Ada Lovelace)")
    if not FULL_NAME_RE.fullmatch(text):
        raise HubError("full name: letters, spaces, apostrophes, and hyphens only")


def _parse_agent(row: dict[str, Any]) -> HubAgent:
    person = row.get("full_name") or row.get("uploader")
    person_s = str(person) if person else None
    return HubAgent(
        name=str(row["name"]),
        sha256=str(row["sha256"]),
        size_bytes=int(row["size_bytes"]),
        uploaded_at=str(row["uploaded_at"]),
        uploader=person_s,
        full_name=person_s,
        status=str(row.get("status") or "approved"),
        approved_at=str(row["approved_at"]) if row.get("approved_at") else None,
    )


def ping_hub(base_url: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
    """GET ``/health`` on coup-master. Raises HubError when unreachable or not ok."""

    base = (base_url or require_master_url()).rstrip("/")
    payload = _request_json("GET", f"{base}/health", timeout=timeout)
    status = str(payload.get("status", "")).strip().lower()
    if status not in {"ok", "healthy", "ready"}:
        raise HubError(f"hub health not ok: {payload.get('status')!r}")
    return {
        "ok": True,
        "status": "ready",
        "version": payload.get("version"),
    }


def list_remote_agents(base_url: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> list[HubAgent]:
    base = (base_url or require_master_url()).rstrip("/")
    payload = _request_json("GET", f"{base}/v1/agents", timeout=timeout)
    agents = payload.get("agents")
    if not isinstance(agents, list):
        raise HubError("master returned unexpected list payload")
    out: list[HubAgent] = []
    for row in agents:
        if not isinstance(row, dict):
            continue
        out.append(_parse_agent(row))
    return out


def list_queue(
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[HubAgent]:
    base = (base_url or require_master_url()).rstrip("/")
    headers = {"X-API-Key": _api_key(api_key)}
    payload = _request_json("GET", f"{base}/v1/admin/queue", headers=headers, timeout=timeout)
    agents = payload.get("agents")
    if not isinstance(agents, list):
        raise HubError("master returned unexpected queue payload")
    return [_parse_agent(row) for row in agents if isinstance(row, dict)]


def download_agent(
    name: str,
    dest: Path,
    *,
    base_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    validate_local_name(name)
    base = (base_url or require_master_url()).rstrip("/")
    data = _request_bytes("GET", f"{base}/v1/agents/{urllib.parse.quote(name)}", timeout=timeout)
    return _write_agent(dest, data)


def download_queue_agent(
    name: str,
    dest: Path,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Path:
    """Organizer download of quarantined (or any) agent via admin API."""

    validate_local_name(name)
    base = (base_url or require_master_url()).rstrip("/")
    headers = {"X-API-Key": _api_key(api_key)}
    data = _request_bytes(
        "GET",
        f"{base}/v1/admin/agents/{urllib.parse.quote(name)}",
        headers=headers,
        timeout=timeout,
    )
    return _write_agent(dest, data)


def approve_agent(
    name: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    actor: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> HubAgent:
    validate_local_name(name)
    base = (base_url or require_master_url()).rstrip("/")
    headers = {"X-API-Key": _api_key(api_key)}
    if actor:
        headers["X-Actor"] = actor[:128]
    payload = _request_json(
        "POST",
        f"{base}/v1/admin/agents/{urllib.parse.quote(name)}/approve",
        headers=headers,
        timeout=timeout,
    )
    return _parse_agent(payload)


def reject_agent(
    name: str,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    actor: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> None:
    validate_local_name(name)
    base = (base_url or require_master_url()).rstrip("/")
    headers = {"X-API-Key": _api_key(api_key)}
    if actor:
        headers["X-Actor"] = actor[:128]
    _request_bytes(
        "POST",
        f"{base}/v1/admin/agents/{urllib.parse.quote(name)}/reject",
        headers=headers,
        timeout=timeout,
    )


def upload_agent(
    name: str,
    path: Path,
    *,
    base_url: str | None = None,
    api_key: str | None = None,
    full_name: str | None = None,
    uploader: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> HubAgent:
    validate_local_name(name)
    person = full_name if full_name is not None else uploader
    validate_full_name(person)
    assert person is not None
    person = " ".join(person.strip().split())
    path = Path(path)
    if not path.is_file():
        raise HubError(f"file not found: {path}")
    base = (base_url or require_master_url()).rstrip("/")
    raw = path.read_bytes()
    boundary = "----coupHubBoundary7d3a9c"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="name"\r\n\r\n',
            name.encode("utf-8"),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="full_name"\r\n\r\n',
            person.encode("utf-8"),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="agent.py"\r\n',
            b"Content-Type: text/x-python\r\n\r\n",
            raw,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
        "X-Uploader": person[:128],
    }
    key = api_key if api_key is not None else os.environ.get("COUP_MASTER_API_KEY", "").strip()
    if key:
        headers["X-API-Key"] = key
    payload = _request_json("POST", f"{base}/v1/agents", data=body, headers=headers, timeout=timeout)
    return _parse_agent(payload)


def _write_agent(dest: Path, data: bytes) -> Path:
    dest = Path(dest)
    if dest.exists() and dest.is_dir():
        dest = dest / "agent.py"
    elif dest.suffix != ".py":
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / "agent.py"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def _request_json(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    raw = _request_bytes(method, url, data=data, headers=headers, timeout=timeout)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HubError("master returned non-JSON body") from exc
    if not isinstance(payload, dict):
        raise HubError("master returned non-object JSON")
    return payload


def _request_bytes(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        issues: list[str] = []
        message = body.strip() or exc.reason
        try:
            parsed = json.loads(body)
            detail = parsed.get("detail", parsed)
            if isinstance(detail, dict):
                message = str(detail.get("error") or message)
                raw_issues = detail.get("issues") or []
                if isinstance(raw_issues, list):
                    issues = [str(item) for item in raw_issues]
            elif isinstance(detail, str):
                message = detail
        except json.JSONDecodeError:
            pass
        raise HubError(message, status=exc.code, issues=issues) from exc
    except urllib.error.URLError as exc:
        raise HubError(f"cannot reach master: {exc.reason}") from exc
