"""Prove the runtime-only install works without pytest.

Run with a fresh virtualenv that installed only ``requirements.txt``:

    python scripts/verify_runtime_only.py

It starts Streamlit headless, checks the health endpoint and root page, then
renders all 17 navigation pages with ``streamlit.testing.AppTest``. Each page
runs in its own interpreter so an import warmed by an earlier page cannot hide
an import cycle. No pytest is imported or required. Exit code 0 means every
check passed.
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP = ROOT / "app.py"
PAGE_ROOT = ROOT / "app_pages"


def _wait_for_url(url: str, timeout: float) -> str:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as error:  # noqa: BLE001 - startup polling
            last_error = error
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}: {last_error}")


def check_headless(port: int, timeout: float) -> None:
    """Start Streamlit, check health/root, and always stop the process."""
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP),
        "--server.headless=true",
        "--server.address=127.0.0.1",
        "--server.port",
        str(port),
        "--browser.gatherUsageStats=false",
    ]
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        health = _wait_for_url(
            f"http://127.0.0.1:{port}/_stcore/health", timeout
        ).strip()
        if health != "ok":
            raise RuntimeError(f"Unexpected health response: {health!r}")
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/", timeout=5
        ) as response:
            root_status = response.status
            root_body = response.read().decode("utf-8", errors="replace")
        if root_status != 200 or "streamlit" not in root_body.lower():
            raise RuntimeError(f"Unexpected root page: status {root_status}")
        print(f"health: {health}; root status: {root_status}")
    finally:
        process.terminate()
        try:
            output = process.communicate(timeout=10)[0] or ""
        except subprocess.TimeoutExpired:
            process.kill()
            output = process.communicate()[0] or ""
        if process.returncode not in (0, -15, 1):
            print(f"streamlit exit code: {process.returncode}")
        if "Traceback (most recent call last)" in output:
            raise RuntimeError(f"Streamlit logged a traceback:\n{output}")


def navigation_pages() -> list[str]:
    """Return every navigation page path, including all thin app_pages entries."""
    from ui.navigation import PAGE_SPECS

    pages = [spec.path for spec in PAGE_SPECS]
    page_files = {
        path.relative_to(ROOT).as_posix() for path in PAGE_ROOT.glob("*.py")
    }
    missing = sorted(page_files - set(pages))
    if missing:
        raise RuntimeError(f"app_pages files missing from navigation: {missing}")
    return pages


def render_page(page_path: str) -> None:
    """Render app.py and one page in this interpreter; never reuse AppTest."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP), default_timeout=120).run()
    if at.exception:
        raise RuntimeError(f"Root render failed: {at.exception[0].message}")
    at.switch_page(page_path).run()
    if at.exception:
        raise RuntimeError(f"Page {page_path!r} failed: {at.exception[0].message}")


def render_all_pages_in_fresh_interpreters() -> None:
    """Give every page a clean sys.modules so cycles cannot hide behind order."""
    script = Path(__file__).resolve()
    for page_path in navigation_pages():
        result = subprocess.run(
            [sys.executable, str(script), "--render-page", page_path],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Fresh-interpreter render failed for {page_path!r}:\n"
                f"{result.stdout}\n{result.stderr}"
            )
    print(
        f"AppTest rendered {len(navigation_pages())} pages in fresh "
        "interpreters with no exceptions"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8599)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--render-page",
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    if args.render_page:
        page = (ROOT / args.render_page).resolve()
        if not page.is_relative_to(PAGE_ROOT):
            raise RuntimeError(f"Not an app page: {args.render_page!r}")
        render_page(page.relative_to(ROOT).as_posix())
        print(f"fresh page render OK: {args.render_page}")
        return 0

    if importlib.util.find_spec("pytest") is not None:
        raise RuntimeError("pytest is installed; this check must run without it")
    check_headless(args.port, args.timeout)
    render_all_pages_in_fresh_interpreters()
    print("runtime-only verification: PASS (pytest not installed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
