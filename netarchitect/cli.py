"""Argparse-only CLI over the deterministic NetArchitect AI engines.

Every command is a thin adapter: it reads UTF-8 input from an explicit path,
calls a lower-layer engine, and writes deterministic JSON or export bytes. The
CLI never reads a wall clock, never imports the web UI, and writes to disk only
when the caller supplies an explicit ``--out`` path.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from config import limits as config_limits
from config.settings import Settings
from core.exceptions import NetArchitectError

# A deliberately small, stable subset of the free-tier limits. These are
# constants, so ``info`` is byte-identical on every run.
_INFO_LIMITS: tuple[str, ...] = (
    "MAX_NODES",
    "MAX_EDGES",
    "MAX_DEMANDS",
    "MAX_SCENARIOS",
    "MAX_INPUT_BYTES",
    "MAX_REPORT_BYTES",
    "MAX_EVALUATIONS",
)

_EXPORT_MODULES: dict[str, str] = {
    "graphml": "services.export.graphml",
    "mermaid": "services.export.mermaid",
    "inventory": "services.export.inventory",
    "drawio": "services.export.drawio",
}

# B5 exporters may settle on any of these conventional names. The first
# callable found in the module wins, so the CLI does not depend on a particular
# re-export from ``services.export``.
_EXPORT_NAMES: dict[str, tuple[str, ...]] = {
    "graphml": ("to_graphml", "export_graphml", "graphml", "build_graphml"),
    "mermaid": ("to_mermaid", "export_mermaid", "mermaid", "build_mermaid"),
    "inventory": (
        "to_inventory",
        "to_inventory_csv",
        "export_inventory",
        "inventory",
        "build_inventory",
    ),
    "drawio": ("to_drawio", "export_drawio", "drawio", "build_drawio"),
}


class CliError(NetArchitectError):
    """A CLI adapter error with a short, actionable message."""


def _json_text(payload: object) -> str:
    """Serialize ``payload`` with fixed key order and a trailing newline."""
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_stdout(text: str) -> None:
    """Write UTF-8 text to stdout without depending on the console code page."""
    sys.stdout.buffer.write(text.encode("utf-8"))
    sys.stdout.buffer.flush()


def _write_payload(payload: bytes, out: str | None) -> None:
    """Write export bytes to ``out``, or to stdout when no path was supplied."""
    if out:
        Path(out).write_bytes(payload)
        return
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def _error_text(error: BaseException) -> str:
    """Build the short typed error envelope printed on stderr."""
    message = " ".join(str(error).split())
    if len(message) > 240:
        message = message[:237] + "..."
    return _json_text(
        {"error": {"type": type(error).__name__, "message": message}}
    )


def _read_text(path: str) -> str:
    """Read a UTF-8 input file supplied on the command line."""
    # ``utf-8-sig`` accepts both plain UTF-8 and files carrying a BOM.
    return Path(path).read_text(encoding="utf-8-sig")


def _load_twin(path: str) -> Any:
    """Parse and limit-check a digital twin from a JSON file."""
    from digital_twin.serialization import from_json

    return from_json(_read_text(path))


def _cmd_info(_args: argparse.Namespace) -> int:
    settings = Settings()
    payload = {
        "app_name": settings.APP_NAME,
        "app_version": settings.APP_VERSION,
        "deployment_target": settings.DEPLOYMENT_TARGET,
        "limits": {
            name: getattr(config_limits, name) for name in _INFO_LIMITS
        },
    }
    _write_stdout(_json_text(payload))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    from digital_twin.validation import validate_twin
    from simulation.evaluator import twin_fingerprint

    twin = _load_twin(args.twin)
    report = validate_twin(twin)
    payload = {
        "valid": report.is_valid,
        "findings": [finding.model_dump(mode="json") for finding in report.findings],
        "fingerprint": twin_fingerprint(twin),
    }
    _write_stdout(_json_text(payload))
    return 0 if report.is_valid else 1


def _cmd_simulate(args: argparse.Namespace) -> int:
    if args.scenario:
        from core.schemas.scenario import Scenario
        from simulation.scenarios import run_scenario

        scenario = Scenario.model_validate_json(_read_text(args.scenario))
        result = run_scenario(_load_twin(args.twin), scenario)
    else:
        from simulation.evaluator import evaluate

        result = evaluate(_load_twin(args.twin))
    _write_stdout(_json_text(result.model_dump(mode="json")))
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from services.export import to_json as render_json
    from services.export import to_markdown as render_markdown
    from services.reporting import ReportSources, build_report

    twin = _load_twin(args.twin)
    # Reuse the twin's own timestamp so the report never reads a clock.
    document = build_report(
        ReportSources(twin=twin, generated_at=twin.metadata.created_at)
    )
    rendered = (
        render_json(document) if args.format == "json" else render_markdown(document)
    )
    _write_payload(rendered, args.out)
    return 0


def _find_exporter(fmt: str) -> Callable[[Any], Any]:
    """Resolve one B5 exporter without requiring a package-level re-export."""
    module_name = _EXPORT_MODULES[fmt]
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise CliError(f"Export module {module_name} is unavailable: {error}") from error

    for name in _EXPORT_NAMES[fmt]:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    raise CliError(f"Export module {module_name} has no supported renderer.")


def _call_exporter(renderer: Callable[[Any], Any], twin: Any) -> Any:
    """Call a renderer that accepts either a positional or a ``twin`` argument."""
    try:
        return renderer(twin)
    except TypeError as positional_error:
        try:
            return renderer(twin=twin)
        except TypeError:
            name = getattr(renderer, "__name__", type(renderer).__name__)
            raise CliError(
                f"Export renderer {name!r} cannot be called with a digital twin."
            ) from positional_error


def _export_bytes(fmt: str, twin: Any) -> bytes:
    renderer = _find_exporter(fmt)
    payload = _call_exporter(renderer, twin)
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, bytearray):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("utf-8")
    raise CliError(f"Export renderer returned {type(payload).__name__}, not bytes.")


def _cmd_export(args: argparse.Namespace) -> int:
    twin = _load_twin(args.twin)
    _write_payload(_export_bytes(args.format, twin), args.out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser. Usage errors exit with status 2 via argparse."""
    parser = argparse.ArgumentParser(
        prog="python -m netarchitect",
        description="Deterministic NetArchitect AI command-line tools.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    info = commands.add_parser("info", help="Show non-secret application metadata.")
    info.set_defaults(handler=_cmd_info)

    validate = commands.add_parser(
        "validate", help="Validate a digital twin JSON file."
    )
    validate.add_argument("twin", help="Path to a twin JSON file.")
    validate.set_defaults(handler=_cmd_validate)

    simulate = commands.add_parser(
        "simulate", help="Evaluate a twin, optionally under a what-if scenario."
    )
    simulate.add_argument("twin", help="Path to a twin JSON file.")
    simulate.add_argument(
        "--scenario", metavar="PATH", help="Optional scenario JSON file."
    )
    simulate.set_defaults(handler=_cmd_simulate)

    report = commands.add_parser("report", help="Build a design report.")
    report.add_argument("twin", help="Path to a twin JSON file.")
    report.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Report rendering (default: markdown).",
    )
    report.add_argument(
        "--out", metavar="PATH", help="Write bytes to this path instead of stdout."
    )
    report.set_defaults(handler=_cmd_report)

    export = commands.add_parser("export", help="Export a twin diagram or inventory.")
    export.add_argument("twin", help="Path to a twin JSON file.")
    export.add_argument(
        "--format",
        choices=tuple(_EXPORT_MODULES),
        required=True,
        help="Export rendering.",
    )
    export.add_argument(
        "--out", metavar="PATH", help="Write bytes to this path instead of stdout."
    )
    export.set_defaults(handler=_cmd_export)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit status (0, 1, or argparse's 2)."""
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (
        NetArchitectError,
        OSError,
        ValidationError,
        ValueError,
        TypeError,
    ) as error:
        sys.stderr.write(_error_text(error))
        return 1


__all__ = ["build_parser", "main"]
