"""Reject unsafe / invalid agent source before local READY or hub upload.

Mirrors coup-master ``app.validation`` so a local READY/safe result matches what
the hub will accept on upload (master never executes candidate code). Prefer an
import allowlist (not a banlist) plus bans on dynamic execution / reflection
primitives that commonly bypass static import checks.
"""

from __future__ import annotations

import ast

DEFAULT_MAX_BYTES = 256 * 1024

# Safe, game-logic stdlib only. Anything else (os/sys/pathlib/io/…) is rejected.
ALLOWED_STDLIB_ROOTS = frozenset(
    {
        "__future__",
        "abc",
        "array",
        "bisect",
        "collections",
        "copy",
        "dataclasses",
        "decimal",
        "enum",
        "fractions",
        "functools",
        "heapq",
        "itertools",
        "math",
        "numbers",
        "operator",
        "random",
        "re",
        "statistics",
        "string",
        "typing",
    }
)
ALLOWED_COUP = "coup.agent_api"

# Calls that open escape hatches even with a tight import allowlist.
BANNED_CALLS = frozenset(
    {
        "__import__",
        "eval",
        "exec",
        "compile",
        "breakpoint",
        "open",
        "input",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "globals",
        "locals",
        "vars",
        "memoryview",
        "type",
    }
)
BANNED_NAMES = frozenset(
    {
        "__builtins__",
        "__loader__",
        "__spec__",
        "__import__",
    }
)


def validate_source(source: str, *, max_bytes: int = DEFAULT_MAX_BYTES) -> list[str]:
    """Full static safety + exactly-one Agent subclass (hub-equivalent)."""

    raw = source.encode("utf-8", errors="surrogatepass")
    issues: list[str] = []
    if len(raw) == 0:
        issues.append("agent file is empty")
        return issues
    if len(raw) > max_bytes:
        issues.append(f"agent file exceeds {max_bytes} bytes")
    if "\x00" in source:
        issues.append("agent file must be UTF-8 text without null bytes")
    try:
        source.encode("utf-8")
    except UnicodeEncodeError:
        issues.append("agent file must be valid UTF-8")
        return issues

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"line {exc.lineno}: {exc.msg}"]

    issues.extend(static_issues_from_tree(tree))
    agent_classes = _agent_subclasses(tree)
    if len(agent_classes) == 0:
        issues.append("file must define exactly one Agent subclass (found 0)")
    elif len(agent_classes) > 1:
        issues.append(f"file must define exactly one Agent subclass (found {len(agent_classes)})")
    return issues


def static_issues(source: str) -> list[str]:
    """Import / call / dunder checks only (shared shape with coup-master)."""

    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"line {exc.lineno}: {exc.msg}"]
    return static_issues_from_tree(tree)


def static_issues_from_tree(tree: ast.AST) -> list[str]:
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
            if node.module is None:
                issues.append(f"line {node.lineno}: import is not allowed")
                continue
            _check_module(node.module, node.lineno, issues)
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in BANNED_CALLS:
                issues.append(f"line {node.lineno}: {name}() is not allowed")
        elif isinstance(node, ast.Attribute):
            if _is_dunder(node.attr):
                issues.append(f"line {node.lineno}: attribute {node.attr!r} is not allowed")
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in BANNED_NAMES or _is_dunder(node.id):
                issues.append(f"line {node.lineno}: name {node.id!r} is not allowed")
    return issues


def _check_module(name: str, lineno: int, issues: list[str]) -> None:
    if name == ALLOWED_COUP or name.startswith(ALLOWED_COUP + "."):
        return
    root = name.split(".", 1)[0]
    if root in ALLOWED_STDLIB_ROOTS:
        return
    if root == "coup":
        issues.append(f"line {lineno}: only coup.agent_api may be imported, not {name}")
        return
    issues.append(f"line {lineno}: import of {name} is not allowed")


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        # builtins.eval / os.system style — flag the attribute leaf when banned
        if func.attr in BANNED_CALLS:
            return func.attr
    return None


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__") and len(name) >= 4


def _agent_subclasses(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in tree.body if isinstance(tree, ast.Module) else []:
        if not isinstance(node, ast.ClassDef):
            continue
        if any(_is_agent_base(base) for base in node.bases):
            found.append(node.name)
    return found


def _is_agent_base(base: ast.AST) -> bool:
    if isinstance(base, ast.Name):
        return base.id == "Agent"
    if isinstance(base, ast.Attribute) and isinstance(base.value, ast.Name):
        return base.attr == "Agent"
    return False
