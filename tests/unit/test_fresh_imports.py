"""Fresh-interpreter import checks for every production module.

A single pytest process hides circular imports because earlier tests warm
``sys.modules``. This test spawns one clean interpreter per module and asserts
that ``python -c "import <module>"`` exits successfully. It also imports the
``ui.pages.*`` target of every ``app_pages/*.py`` entry and the ``app`` module.

The checks take about a minute with four workers (well under the 90 s budget),
so the ``imports`` marker is included in the default pytest run and is also
selected explicitly in CI.
"""

from __future__ import annotations

import ast
import concurrent.futures
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MAX_WORKERS = 4
IMPORT_TIMEOUT = 90

PACKAGES = (
    "agents",
    "app_pages",
    "capacity",
    "config",
    "core",
    "digital_twin",
    "forecasting",
    "network",
    "optimization",
    "scripts",
    "security",
    "services",
    "simulation",
    "ui",
)


def _page_targets() -> set[str]:
    """Read the ``ui.pages.*`` module rendered by each thin page entry."""
    targets: set[str] = set()
    for path in sorted((ROOT / "app_pages").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "ui.pages."
            ):
                targets.add(node.module)
    return targets


def _module_names() -> list[str]:
    names: set[str] = set()
    for package in PACKAGES:
        for path in (ROOT / package).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            parts = list(path.relative_to(ROOT).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            names.add(".".join(parts))
    names.update(_page_targets())
    names.add("app")
    return sorted(names)


def _import_in_fresh_interpreter(module: str) -> tuple[str, int, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        result = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return module, -1, f"timed out after {IMPORT_TIMEOUT}s: {error}"
    output = (result.stderr or result.stdout or "").strip()
    return module, result.returncode, output[-1200:]


@pytest.mark.imports
def test_every_module_imports_in_a_fresh_interpreter() -> None:
    """No module may depend on import order warmed by another test."""
    modules = _module_names()
    assert modules, "No modules discovered"
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        results = list(pool.map(_import_in_fresh_interpreter, modules))
    failures = [
        f"{module} (exit {code}):\n{output}"
        for module, code, output in results
        if code != 0
    ]
    assert not failures, (
        f"{len(failures)} of {len(modules)} fresh imports failed:\n"
        + "\n\n".join(failures)
    )
