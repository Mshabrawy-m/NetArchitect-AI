"""Offline import audit for the W1-W4 modeled design engines.

The engines are design models only. They may depend on typed schemas, pure
mathematics, and the existing deterministic evaluation engine, but they must not
import runtime, process, filesystem, or network libraries.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

ENGINE_DIRS = (
    "network/l2",
    "network/wan",
    "network/wireless",
    "network/qos",
)

ALLOWED_ROOTS = frozenset(
    {
        "__future__",
        "collections",
        "config",
        "core",
        "dataclasses",
        "digital_twin",
        "enum",
        "math",
        "network",
        "pydantic",
        "simulation",
        "typing",
    }
)

FORBIDDEN_ROOTS = frozenset(
    {
        "asyncio",
        "ftplib",
        "http",
        "httpx",
        "importlib",
        "multiprocessing",
        "netmiko",
        "os",
        "paramiko",
        "pathlib",
        "pickle",
        "requests",
        "scapy",
        "shutil",
        "socket",
        "sqlite3",
        "subprocess",
        "sys",
        "threading",
        "time",
        "urllib",
    }
)

FORBIDDEN_TOKENS = re.compile(
    r"(?<![A-Za-z0-9_])(?:socket|requests|httpx|paramiko|netmiko|scapy|nmap|"
    r"subprocess|threading|multiprocessing|asyncio|urllib|os\.system)(?![A-Za-z0-9_])"
)

DYNAMIC_CALLS = frozenset({"eval", "exec", "compile", "__import__", "open"})


def _engine_files() -> list[Path]:
    files = [
        path
        for directory in ENGINE_DIRS
        for path in sorted((ROOT / directory).glob("*.py"))
    ]
    assert files
    return files


def _module_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_w5_engines_import_only_allowed_offline_modules() -> None:
    for path in _engine_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots = _module_roots(tree)
        assert roots <= ALLOWED_ROOTS, f"{path} imports {sorted(roots - ALLOWED_ROOTS)}"
        assert not roots & FORBIDDEN_ROOTS, f"{path} imports a forbidden module"


def test_w5_engines_have_no_dynamic_execution_or_disk_io() -> None:
    for path in _engine_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not calls & DYNAMIC_CALLS, f"{path} uses {sorted(calls & DYNAMIC_CALLS)}"


def test_w5_engines_mention_no_network_or_device_libraries() -> None:
    for path in _engine_files():
        source = path.read_text(encoding="utf-8")
        match = FORBIDDEN_TOKENS.search(source)
        assert match is None, f"{path} mentions forbidden token {match.group(0)!r}"
