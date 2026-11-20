"""Measure cold import time and Streamlit Dashboard first render.

This is a development tool. It uses ``python -X importtime`` in a fresh child
process so module imports are not cached, then times one clean AppTest run of
the Dashboard. Run it before and after lazy-import changes.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import time
from pathlib import Path

logging.getLogger(
    "streamlit.runtime.scriptrunner_utils.script_run_context"
).setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TARGET_PREFIXES = (
    "reportlab",
    "services.reporting",
    "services.export",
    "ui.pages.reports",
    "ui.pages.agent_control_center",
    "ui.pages.ai_designer",
    "ui.pages.security_analysis",
)
LINE = re.compile(r"^import time:\s+(\d+) \|\s+(\d+) \|\s+(\S+)$")


def _importtime() -> dict[str, int]:
    completed = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "import app"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    totals: dict[str, int] = {prefix: 0 for prefix in TARGET_PREFIXES}
    app_time = 0
    for raw in completed.stderr.splitlines():
        match = LINE.match(raw)
        if match is None:
            continue
        _self_us, cumulative_us, module = match.groups()
        cumulative = int(cumulative_us)
        if module == "app":
            app_time = cumulative
        for prefix in TARGET_PREFIXES:
            if module == prefix or module.startswith(f"{prefix}."):
                totals[prefix] += cumulative
    totals["app (total cumulative)"] = app_time
    return totals


def _dashboard_first_render() -> float:
    from streamlit.testing.v1 import AppTest

    started = time.perf_counter()
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120)
    at.run()
    elapsed = time.perf_counter() - started
    if at.exception:
        raise RuntimeError(f"Dashboard render failed: {at.exception[0].value}")
    return elapsed


def main() -> int:
    importtime = _importtime()
    print("| import target | cumulative us |")
    print("| --- | ---: |")
    for name, value in importtime.items():
        print(f"| {name} | {value} |")

    print()
    print("| measurement | seconds |")
    print("| --- | ---: |")
    print(f"| Dashboard first render | {_dashboard_first_render():.3f} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
