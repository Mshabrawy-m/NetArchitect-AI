"""Fail if the imported app plus a Dashboard render exceeds the Linux RSS gate.

The CI gate is 450 MB. Community Cloud Free provides about 1 GB RAM; the OS,
Streamlit server, and one user session need the remainder. 450 MB leaves
headroom for a slow cold start and one interactive session while still catching
an accidental import or cache regression. This is a process RSS check, not a
tracemalloc peak, and it only runs on Linux (CI uses ubuntu-latest).
"""

from __future__ import annotations

import gc
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

LIMIT_MB = 450


def rss_mb() -> float:
    """Return current resident set size in MiB from /proc/self/status."""
    with open("/proc/self/status", encoding="utf-8") as status:
        for line in status:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("VmRSS not found in /proc/self/status")


def main() -> int:
    if not sys.platform.startswith("linux"):
        print(f"RSS gate skipped on {sys.platform}; CI runs on Linux")
        return 0

    importlib.import_module("app")
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=120).run()
    if at.exception:
        raise RuntimeError(f"Dashboard render failed: {at.exception[0].message}")
    gc.collect()
    used = rss_mb()
    print(f"VmRSS after app import and Dashboard render: {used:.1f} MiB")
    print(f"CI budget: {LIMIT_MB} MiB")
    if used > LIMIT_MB:
        raise SystemExit(
            f"RSS {used:.1f} MiB exceeds the {LIMIT_MB} MiB Linux budget"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
