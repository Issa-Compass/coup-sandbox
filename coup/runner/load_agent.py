"""Load the single Agent subclass from a candidate file."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

from coup.agent_api import Agent


def load_agent_class(path: Path) -> type[Agent]:
    digest = hashlib.sha1(str(path.resolve()).encode()).hexdigest()[:10]
    module_name = f"candidate_{path.stem}_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # dataclasses and typing resolve a class's module through sys.modules.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
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


def unique_instance_names(names: list[str]) -> list[str]:
    """Keep the first of each name; suffix later copies ``_2``, ``_3``, …"""

    seen: dict[str, int] = {}
    out: list[str] = []
    for name in names:
        count = seen.get(name, 0) + 1
        seen[name] = count
        out.append(name if count == 1 else f"{name}_{count}")
    return out
