"""Load the single Agent subclass from a candidate file."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from coup.agent_api import Agent


def load_agent_class(path: Path) -> type[Agent]:
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
        raise RuntimeError(
            f"{path} must define exactly one Agent subclass (found {len(classes)})"
        )
    return classes[0]


def agent_name_from_path(path: Path) -> str:
    if path.name == "agent.py":
        return path.parent.name
    return path.stem
