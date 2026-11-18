"""Forbidden-import audit for the design-time security package."""

from __future__ import annotations

import ast
from pathlib import Path

SECURITY_DIR = Path(__file__).resolve().parents[3] / "security"

# Only deterministic, offline model/engineering modules are allowed. The audit
# intentionally does not permit OS, process, filesystem, or network modules.
ALLOWED_ROOTS = frozenset(
    {
        "__future__",
        "collections",
        "config",
        "core",
        "dataclasses",
        "digital_twin",
        "enum",
        "functools",
        "ipaddress",
        "itertools",
        "json",
        "math",
        "network",
        "pydantic",
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
        "nmap",
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
        "urllib",
    }
)

DYNAMIC_EXECUTION = frozenset({"eval", "exec", "compile", "__import__"})


def _module_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_security_package_imports_only_allowed_offline_modules() -> None:
    files = sorted(SECURITY_DIR.glob("*.py"))
    assert files

    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        roots = _module_roots(tree)
        assert roots <= ALLOWED_ROOTS, f"{path.name} imports {sorted(roots - ALLOWED_ROOTS)}"
        assert not roots & FORBIDDEN_ROOTS, f"{path.name} imports forbidden modules"
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not calls & DYNAMIC_EXECUTION, f"{path.name} uses dynamic execution"


def test_security_package_has_no_network_or_device_libraries() -> None:
    for path in sorted(SECURITY_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8").lower()
        for token in ("socket", "requests", "httpx", "paramiko", "netmiko", "scapy", "nmap"):
            assert token not in source, f"{path.name} mentions forbidden library {token!r}"
