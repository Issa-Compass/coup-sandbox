"""In-process and subprocess agent adapters.

Both adapters return a legal value or the safe default. The game engine
therefore never has to accept an illegal move. Timeouts, exceptions, and
illegal returns are counted separately.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from coup.agent_api import (
    Action,
    Agent,
    Block,
    Card,
    GameResult,
    PlayerView,
    current_standings,
    default_action,
    default_exchange,
    default_loss,
)
from coup.engine.rules import exchange_keep_is_legal, response_is_legal
from coup.runner.load_agent import load_agent_class
from coup.serialize import from_data, to_data

ROOT = Path(__file__).resolve().parents[2]
LOAD_TIMEOUT = 10.0


class Player:
    def __init__(self, name: str, timeout: float):
        self.name = name
        # What agents see at the table. Tournaments overwrite with an opaque UID.
        self.public_id = name
        self.timeout = timeout
        self.errors = 0
        self.timeouts = 0
        self.illegals = 0
        self.decisions = 0
        self.decision_time = 0.0
        self.load_error: str | None = None

    def on_game_start(self, view: PlayerView, seed: int) -> None:
        raise NotImplementedError

    def on_game_end(self, view: PlayerView, result: GameResult) -> None:
        raise NotImplementedError

    def choose_action(self, view: PlayerView) -> Action:
        raise NotImplementedError

    def respond_to_action(self, view: PlayerView, action: Action):
        raise NotImplementedError

    def respond_to_block(self, view: PlayerView, block: Block):
        raise NotImplementedError

    def choose_card_to_lose(self, view: PlayerView) -> Card:
        raise NotImplementedError

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...]) -> list[Card]:
        raise NotImplementedError

    def close(self) -> None:
        return None

    def snapshot(self) -> tuple[int, int, int, int, float]:
        return (self.illegals, self.errors, self.timeouts, self.decisions, self.decision_time)


class InProcessPlayer(Player):
    def __init__(self, agent: Agent, name: str, timeout: float):
        super().__init__(name, timeout)
        self.agent = agent

    def on_game_start(self, view: PlayerView, seed: int) -> None:
        self._call(lambda: self.agent.on_game_start(view, seed))

    def on_game_end(self, view: PlayerView, result: GameResult) -> None:
        self._call(lambda: self.agent.on_game_end(view, result))

    def choose_action(self, view: PlayerView) -> Action:
        status, raw = self._call(lambda: self.agent.choose_action(view))
        if status == "ok" and isinstance(raw, Action) and raw in view.legal_actions:
            return raw
        if status == "ok":
            self.illegals += 1
        return default_action(view)

    def respond_to_action(self, view: PlayerView, action: Action):
        status, raw = self._call(lambda: self.agent.respond_to_action(view, action))
        return self._response_or_pass(status, raw, view)

    def respond_to_block(self, view: PlayerView, block: Block):
        status, raw = self._call(lambda: self.agent.respond_to_block(view, block))
        return self._response_or_pass(status, raw, view)

    def choose_card_to_lose(self, view: PlayerView) -> Card:
        status, raw = self._call(lambda: self.agent.choose_card_to_lose(view))
        if status == "ok" and isinstance(raw, Card) and raw in view.your_cards:
            return raw
        if status == "ok":
            self.illegals += 1
        return default_loss(view)

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...]) -> list[Card]:
        status, raw = self._call(lambda: self.agent.choose_exchange(view, drawn))
        keep = list(raw) if isinstance(raw, list | tuple) else None
        pool = list(view.your_cards) + list(drawn)
        if (
            status == "ok"
            and keep is not None
            and all(isinstance(card, Card) for card in keep)
            and exchange_keep_is_legal(keep, pool, len(view.your_cards))
        ):
            return keep
        if status == "ok":
            self.illegals += 1
        return default_exchange(view)

    def _response_or_pass(self, status: str, raw: object, view: PlayerView):
        from coup.agent_api import Pass

        if status == "ok" and response_is_legal(raw, view.legal_responses):
            return raw
        if status == "ok":
            self.illegals += 1
        return Pass()

    def _call(self, fn) -> tuple[str, object]:
        started = time.perf_counter()
        try:
            value = fn()
        except Exception:
            self.decision_time += time.perf_counter() - started
            self.decisions += 1
            self.errors += 1
            return "error", None
        elapsed = time.perf_counter() - started
        self.decision_time += elapsed
        self.decisions += 1
        if elapsed > self.timeout:
            self.timeouts += 1
            return "timeout", None
        return "ok", value


class SandboxPlayer(Player):
    """One child process per agent. A hung move is killed and replaced with the default."""

    def __init__(self, path: Path, name: str, timeout: float):
        super().__init__(name, timeout)
        self.path = path
        self.proc: subprocess.Popen[str] | None = None
        self._next_id = 1
        self._start: tuple[PlayerView, int] | None = None
        self._start_sent = False
        self._fallback = False
        self._booting = False
        self.stderr_tail = ""

    def on_game_start(self, view: PlayerView, seed: int) -> None:
        self._start = (view, seed)
        self._fallback = False
        self._start_sent = False
        if self.proc is not None and self.proc.poll() is None:
            self._send_start()
            return
        self._ensure()

    def on_game_end(self, view: PlayerView, result: GameResult) -> None:
        if self._fallback or self.proc is None or self.proc.poll() is not None:
            return
        self._roundtrip("on_game_end", {"view": to_data(view), "result": to_data(result)})

    def choose_action(self, view: PlayerView) -> Action:
        status, raw = self._decision("choose_action", {"view": to_data(view)})
        action = raw if status == "ok" else None
        if isinstance(action, Action) and action in view.legal_actions:
            return action
        if status == "ok":
            self.illegals += 1
        return default_action(view)

    def respond_to_action(self, view: PlayerView, action: Action):
        status, raw = self._decision(
            "respond_to_action",
            {"view": to_data(view), "action": to_data(action)},
        )
        return self._response_or_pass(status, raw, view)

    def respond_to_block(self, view: PlayerView, block: Block):
        status, raw = self._decision(
            "respond_to_block",
            {"view": to_data(view), "block": to_data(block)},
        )
        return self._response_or_pass(status, raw, view)

    def choose_card_to_lose(self, view: PlayerView) -> Card:
        status, raw = self._decision("choose_card_to_lose", {"view": to_data(view)})
        if status == "ok" and isinstance(raw, Card) and raw in view.your_cards:
            return raw
        if status == "ok":
            self.illegals += 1
        return default_loss(view)

    def choose_exchange(self, view: PlayerView, drawn: tuple[Card, ...]) -> list[Card]:
        status, raw = self._decision(
            "choose_exchange",
            {"view": to_data(view), "drawn": to_data(drawn)},
        )
        keep = list(raw) if isinstance(raw, list | tuple) else None
        pool = list(view.your_cards) + list(drawn)
        if (
            status == "ok"
            and keep is not None
            and all(isinstance(card, Card) for card in keep)
            and exchange_keep_is_legal(keep, pool, len(view.your_cards))
        ):
            return keep
        if status == "ok":
            self.illegals += 1
        return default_exchange(view)

    def close(self) -> None:
        self._kill()

    def _response_or_pass(self, status: str, raw: object, view: PlayerView):
        from coup.agent_api import Pass

        if status == "ok" and response_is_legal(raw, view.legal_responses):
            return raw
        if status == "ok":
            self.illegals += 1
        return Pass()

    def _decision(self, method: str, payload: dict[str, Any]) -> tuple[str, object]:
        if not self._ensure():
            return "error", None
        return self._roundtrip(method, payload, timeout=self.timeout)

    def _send_start(self) -> None:
        if self._start is None or self.proc is None:
            return
        view, seed = self._start
        status, detail = self._roundtrip(
            "on_game_start",
            {"view": to_data(view), "seed": seed, **_standings_payload()},
            timeout=LOAD_TIMEOUT,
            respawn=False,
        )
        if status == "ok":
            self._start_sent = True
            return
        self.load_error = str(detail)
        self._fallback = True
        self._kill()

    def _ensure(self) -> bool:
        if self._fallback or self._booting:
            return False
        if self.proc is not None and self.proc.poll() is None:
            return True
        self._booting = True
        try:
            self._spawn()
            status, detail = self._roundtrip(
                "load",
                {"path": str(self.path)},
                timeout=LOAD_TIMEOUT,
                respawn=False,
            )
            if status != "ok":
                self.load_error = str(detail)
                self._fallback = True
                self._kill()
                return False
            if self._start is not None:
                self._send_start()
                return self._start_sent
            return True
        except Exception as exc:
            self.load_error = str(exc)
            self.errors += 1
            self._fallback = True
            self._kill()
            return False
        finally:
            self._booting = False

    def _spawn(self) -> None:
        self._kill()
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        self.proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "coup.runner.worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ROOT),
            bufsize=1,
            env=env,
        )
        self.stderr_tail = ""
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    def _pump_stderr(self) -> None:
        proc = self.proc
        if proc is None or proc.stderr is None:
            return
        try:
            for line in proc.stderr:
                self.stderr_tail = (self.stderr_tail + line)[-4000:]
        except Exception:
            return

    def _roundtrip(
        self,
        method: str,
        payload: dict[str, Any],
        timeout: float | None = None,
        respawn: bool = True,
    ) -> tuple[str, object]:
        if self.proc is None or self.proc.poll() is not None or self.proc.stdin is None:
            if respawn and method != "load":
                if not self._ensure():
                    return "error", None
            else:
                return "error", "agent process is not running"
        request_id = self._next_id
        self._next_id += 1
        if method != "load" and "standings" not in payload:
            payload = {**payload, **_standings_payload()}
        message = {"id": request_id, "method": method, **payload}
        try:
            assert self.proc is not None and self.proc.stdin is not None
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except Exception as exc:
            self._kill()
            self.errors += 1
            return "error", str(exc)
        limit = self.timeout if timeout is None else timeout
        started = time.perf_counter()
        line = _readline(self.proc, limit)
        elapsed = time.perf_counter() - started
        self.decision_time += elapsed
        self.decisions += 1
        if line is None:
            self.timeouts += 1
            self._kill()
            return "timeout", None
        if line == "":
            detail = self.stderr_tail.strip() or "agent process exited"
            self.errors += 1
            self._kill()
            self.load_error = detail
            return "error", detail
        try:
            body = json.loads(line)
        except json.JSONDecodeError as exc:
            self.errors += 1
            self._kill()
            return "error", str(exc)
        if body.get("id") != request_id or not body.get("ok"):
            self.errors += 1
            self.load_error = str(body.get("error", "agent error"))
            return "error", body.get("error")
        try:
            return "ok", from_data(body.get("result"))
        except Exception as exc:
            self.errors += 1
            return "error", str(exc)

    def _kill(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None or proc.poll() is not None:
            return
        proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return


def _readline(proc: subprocess.Popen[str], timeout: float) -> str | None:
    if proc.stdout is None:
        return ""
    mailbox: queue.Queue[str | Exception] = queue.Queue()

    def read() -> None:
        try:
            mailbox.put(proc.stdout.readline() if proc.stdout is not None else "")
        except Exception as exc:
            mailbox.put(exc)

    threading.Thread(target=read, daemon=True).start()
    try:
        item = mailbox.get(timeout=timeout)
    except queue.Empty:
        return None
    if isinstance(item, Exception):
        return ""
    return item


def _standings_payload() -> dict[str, Any]:
    snapshot = current_standings()
    if snapshot is None:
        return {"standings": None}
    return {"standings": to_data(snapshot)}


def open_player(path: Path, name: str, sandbox: bool, timeout: float) -> Player:
    if sandbox:
        return SandboxPlayer(path, name, timeout)
    try:
        agent = load_agent_class(path)()
    except Exception as exc:
        player = InProcessPlayer(Agent(), name, timeout)
        player.load_error = f"{type(exc).__name__}: {exc}"
        player.errors += 1
        return player
    return InProcessPlayer(agent, name, timeout)
