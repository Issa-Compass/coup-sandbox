"""Reject agent files that import the network, processes, or the engine."""

from __future__ import annotations

import ast

BANNED_ROOTS = {"socket", "requests", "urllib", "http", "subprocess", "importlib", "ctypes"}
ALLOWED_COUP = "coup.agent_api"


def static_issues(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"line {exc.lineno}: {exc.msg}"]
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                _check_module(alias.name, node.lineno, issues)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                issues.append(f"line {node.lineno}: relative imports are not allowed")
                continue
            if node.module == "coup" and all(alias.name == "agent_api" for alias in node.names):
                continue
            if node.module:
                _check_module(node.module, node.lineno, issues)
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "__import__":
                issues.append(f"line {node.lineno}: __import__ is not allowed")
    return issues


def _check_module(name: str, lineno: int, issues: list[str]) -> None:
    if name == ALLOWED_COUP or name.startswith(ALLOWED_COUP + "."):
        return
    root = name.split(".")[0]
    if root in BANNED_ROOTS:
        issues.append(f"line {lineno}: import of {name} is not allowed")
        return
    if root == "coup":
        issues.append(f"line {lineno}: only coup.agent_api may be imported, not {name}")
