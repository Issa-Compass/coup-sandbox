"""Agent subprocess. Speaks one JSON object per line on stdin and stdout.

Prints from the agent are sent to stderr so they cannot break the protocol.
Imports of the engine, the runner, and the network are refused.
"""

from __future__ import annotations

import importlib.abc
import importlib.util
import json
import sys
import traceback
from pathlib import Path

from coup.agent_api import Agent
from coup.serialize import from_data, to_data

_BLOCKED_ROOTS = {"socket", "requests", "urllib", "http", "subprocess", "ctypes"}
_BLOCKER_INSTALLED = False


class _DenyFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path, target=None):  # noqa: ANN001
        root = fullname.split(".")[0]
        if root in _BLOCKED_ROOTS:
            raise ImportError(f"importing {fullname} is not allowed")
        if fullname == "coup.engine" or fullname.startswith("coup.engine."):
            raise ImportError("coup.engine is not available to agents")
        if fullname == "coup.runner" or fullname.startswith("coup.runner."):
            raise ImportError("coup.runner is not available to agents")
        return None


def _install_blocker() -> None:
    global _BLOCKER_INSTALLED
    if _BLOCKER_INSTALLED:
        return
    sys.meta_path.insert(0, _DenyFinder())
    _BLOCKER_INSTALLED = True


def _load(path: Path) -> Agent:
    _install_blocker()
    spec = importlib.util.spec_from_file_location(f"candidate_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    classes = [
        obj
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, Agent)
        and obj is not Agent
        and obj.__module__ == module.__name__
    ]
    if len(classes) != 1:
        raise RuntimeError(f"{path} must define exactly one Agent subclass (found {len(classes)})")
    return classes[0]()


def _reply(stream, payload: dict) -> None:
    stream.write(json.dumps(payload) + "\n")
    stream.flush()


def _dispatch(agent: Agent | None, request: dict) -> tuple[Agent | None, object]:
    method = request["method"]
    if method == "load":
        return _load(Path(request["path"])), None
    if agent is None:
        raise RuntimeError("load an agent before calling it")
    view = from_data(request["view"]) if "view" in request else None
    if method == "on_game_start":
        agent.on_game_start(view, int(request["seed"]))
        return agent, None
    if method == "on_game_end":
        agent.on_game_end(view, from_data(request["result"]))
        return agent, None
    if method == "choose_action":
        return agent, agent.choose_action(view)
    if method == "respond_to_action":
        return agent, agent.respond_to_action(view, from_data(request["action"]))
    if method == "respond_to_block":
        return agent, agent.respond_to_block(view, from_data(request["block"]))
    if method == "choose_card_to_lose":
        return agent, agent.choose_card_to_lose(view)
    if method == "choose_exchange":
        drawn = tuple(from_data(request["drawn"]))
        return agent, agent.choose_exchange(view, drawn)
    raise RuntimeError(f"unknown method {method}")


def main() -> None:
    protocol = sys.stdout
    sys.stdout = sys.stderr
    agent: Agent | None = None
    while True:
        raw = sys.stdin.readline()
        if raw == "":
            return
        if not raw.strip():
            continue
        request: dict = {}
        try:
            request = json.loads(raw)
            agent, result = _dispatch(agent, request)
            _reply(protocol, {"id": request.get("id"), "ok": True, "result": to_data(result)})
        except Exception:
            _reply(
                protocol,
                {
                    "id": request.get("id"),
                    "ok": False,
                    "error": traceback.format_exc(limit=12),
                },
            )


if __name__ == "__main__":
    main()
