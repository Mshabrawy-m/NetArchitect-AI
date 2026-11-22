"""AST guard for the production layer dependency rule.

Lowest to highest::

    core -> network -> digital_twin -> simulation
         -> optimization/security/capacity/forecasting
         -> services/agents -> ui

A module may import only its own layer or a lower one. ``config`` is a
foundation layer beside ``core``, ``app_pages`` and ``app`` belong to ``ui``,
``scripts`` and ``netarchitect`` are top-level tool layers. Imports deferred to function bodies
or ``if TYPE_CHECKING:`` blocks are not evaluated at module import time, so
they cannot create an import-time cycle and are outside this guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

LAYERS: dict[str, int] = {
    "config": 0,
    "core": 0,
    "network": 1,
    "digital_twin": 2,
    "simulation": 3,
    "optimization": 4,
    "security": 4,
    "capacity": 4,
    "forecasting": 4,
    "services": 5,
    "agents": 5,
    "ui": 6,
    "app_pages": 6,
    "app": 6,
    "scripts": 7,
    "netarchitect": 7,
}


def _production_files() -> list[Path]:
    files: list[Path] = []
    for package in LAYERS:
        if package == "app":
            files.append(ROOT / "app.py")
            continue
        files.extend(
            path
            for path in (ROOT / package).rglob("*.py")
            if "__pycache__" not in path.parts
        )
    return sorted(files)


def _layer_for(path: Path) -> int:
    parts = path.relative_to(ROOT).parts
    key = "app" if parts == ("app.py",) else parts[0]
    return LAYERS[key]


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


class _ImportCollector(ast.NodeVisitor):
    """Collect module-level import targets from one parsed file."""

    def __init__(self, package: tuple[str, ...]) -> None:
        self.package = package
        self.targets: list[tuple[int, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Skip deferred imports inside functions."""

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Skip deferred imports inside async functions."""

    def visit_If(self, node: ast.If) -> None:
        if _is_type_checking(node.test):
            return
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.targets.append((node.lineno, alias.name))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            base = self.package[: len(self.package) - (node.level - 1)]
            module = ".".join(list(base) + ([node.module] if node.module else []))
        else:
            module = node.module or ""
        self.targets.append((node.lineno, module))


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    relative = path.relative_to(ROOT)
    parts = list(relative.with_suffix("").parts)
    package = tuple(parts if parts[-1] == "__init__" else parts[:-1])
    collector = _ImportCollector(package)
    collector.visit(tree)

    source_layer = _layer_for(path)
    violations: list[str] = []
    for lineno, target in collector.targets:
        top_level = target.split(".")[0]
        if top_level in LAYERS and LAYERS[top_level] > source_layer:
            violations.append(
                f"{relative.as_posix()}:{lineno}: imports {target} "
                f"(layer {LAYERS[top_level]} > {source_layer})"
            )
    return violations


@pytest.mark.parametrize(
    "path",
    _production_files(),
    ids=lambda path: path.relative_to(ROOT).as_posix(),
)
def test_no_higher_layer_imports(path: Path) -> None:
    """Every production module respects the declared layer order."""
    violations = _violations(path)
    assert not violations, "Higher-layer imports found:\n" + "\n".join(violations)


def test_layering_guard_covers_every_production_file() -> None:
    """The scan set stays in sync with the layer map."""
    missing = [
        path
        for path in _production_files()
        if ("app" if path.name == "app.py" else path.relative_to(ROOT).parts[0])
        not in LAYERS
    ]
    assert not missing, [str(path) for path in missing]
