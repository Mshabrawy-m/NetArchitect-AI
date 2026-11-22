"""Subprocess tests for the ``python -m netarchitect`` CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from core.schemas.network import Topology
from digital_twin.serialization import to_json
from tests.unit.digital_twin.helpers import make_twin

ROOT = Path(__file__).resolve().parents[2]
CLI_PACKAGE = ROOT / "netarchitect"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "netarchitect", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _twin_file(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "twin.json"
    path.write_text(to_json(make_twin(**overrides)), encoding="utf-8")
    return path


def _stdout_json(result: subprocess.CompletedProcess[str]) -> Any:
    return json.loads(result.stdout)


def test_info_is_deterministic() -> None:
    first = _run("info")
    second = _run("info")

    assert first.returncode == 0
    assert second.returncode == 0
    assert first.stdout == second.stdout
    payload = _stdout_json(first)
    assert {"app_name", "app_version", "deployment_target", "limits"} <= set(payload)
    assert payload["limits"]["MAX_NODES"] == 500


@pytest.mark.parametrize("args", [(), ("unknown-command",)])
def test_usage_errors_exit_two(args: tuple[str, ...]) -> None:
    result = _run(*args)
    assert result.returncode == 2


def test_validate_valid_twin(tmp_path: Path) -> None:
    twin_path = _twin_file(tmp_path)

    result = _run("validate", str(twin_path))

    assert result.returncode == 0, result.stderr
    payload = _stdout_json(result)
    assert payload["valid"] is True
    assert payload["findings"] == []
    assert isinstance(payload["fingerprint"], str) and payload["fingerprint"]


def test_validate_malformed_json_reports_typed_error(tmp_path: Path) -> None:
    twin_path = tmp_path / "bad.json"
    twin_path.write_text("{not valid json", encoding="utf-8")

    result = _run("validate", str(twin_path))

    assert result.returncode == 1
    assert result.stdout == ""
    error = json.loads(result.stderr)["error"]
    assert error["type"]
    assert error["message"]


def test_simulate_is_deterministic(tmp_path: Path) -> None:
    twin_path = _twin_file(tmp_path)

    first = _run("simulate", str(twin_path))
    second = _run("simulate", str(twin_path))

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    payload = _stdout_json(first)
    assert payload["device_count"] == 3
    assert payload["demand_count"] == 1


def test_report_markdown_matches_out_file(tmp_path: Path) -> None:
    twin_path = _twin_file(tmp_path)
    out_path = tmp_path / "report.md"

    stdout_run = _run("report", str(twin_path), "--format", "markdown")
    assert stdout_run.returncode == 0, stdout_run.stderr
    assert stdout_run.stdout
    assert not out_path.exists()

    file_run = _run(
        "report", str(twin_path), "--format", "markdown", "--out", str(out_path)
    )
    assert file_run.returncode == 0, file_run.stderr
    assert file_run.stdout == ""
    assert out_path.read_bytes() == stdout_run.stdout.encode("utf-8")


@pytest.mark.parametrize("fmt", ["graphml", "mermaid", "inventory", "drawio"])
def test_export_is_deterministic(tmp_path: Path, fmt: str) -> None:
    twin_path = _twin_file(tmp_path)

    first = _run("export", str(twin_path), "--format", fmt)
    second = _run("export", str(twin_path), "--format", fmt)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout
    assert first.stdout == second.stdout


def test_validate_empty_topology_returns_typed_json(tmp_path: Path) -> None:
    twin_path = _twin_file(
        tmp_path, topology=Topology(name="Empty"), demands=()
    )

    result = _run("validate", str(twin_path))

    assert result.returncode in (0, 1)
    assert result.stderr == ""
    payload = _stdout_json(result)
    assert set(payload) == {"valid", "findings", "fingerprint"}
    assert isinstance(payload["valid"], bool)


def test_cli_sources_have_no_forbidden_runtime_dependencies() -> None:
    forbidden = (
        "import streamlit",
        "from streamlit",
        "threading",
        "multiprocessing",
        "open(",
    )
    sources = sorted(CLI_PACKAGE.rglob("*.py"))
    assert sources
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{token!r} found in {path}"
