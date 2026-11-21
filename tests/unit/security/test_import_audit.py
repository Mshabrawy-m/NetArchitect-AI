"""Forbidden-import audit for the design-time security package."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SECURITY_DIR = ROOT / "security"
S6_MODULES = (
    "agents/critic.py",
    "services/copilot/__init__.py",
    "services/copilot/explain.py",
    "services/copilot/models.py",
    "services/reporting/builder.py",
    "ui/cache.py",
    "ui/i18n.py",
    "ui/pages/security_analysis.py",
    "ui/theme.py",
)
FORBIDDEN_TOKENS = re.compile(
    r"(?<![A-Za-z0-9_])(?:socket|subprocess|urllib|http|requests|ssl|os\.system)(?![A-Za-z0-9_])"
)

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


def test_s6_modules_have_no_forbidden_imports_or_source_tokens() -> None:
    for relative in S6_MODULES:
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        roots = _module_roots(tree)

        assert not roots & FORBIDDEN_ROOTS, f"{relative} imports forbidden modules"
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert not calls & DYNAMIC_EXECUTION, f"{relative} uses dynamic execution"
        token = FORBIDDEN_TOKENS.search(source)
        assert token is None, f"{relative} mentions forbidden token {token.group(0)!r}"
