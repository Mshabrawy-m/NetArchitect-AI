"""Dev-only black-box browser smoke test for the deployed Streamlit app.

Run with::

    python scripts/e2e_live.py https://your-app.example/

The target URL is a required argument; no deployed URL or secret is embedded.
This script deliberately imports no application code, reads no secrets, and
writes only screenshots and downloaded artifacts under ``e2e_out/``. It drives
the public browser UI through Playwright at desktop and mobile viewports.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from playwright.sync_api import Browser, Frame, Page, sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TARGET_URL: str | None = None
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "e2e_out"
VIEWPORTS = ((1440, 900), (390, 844))
WAKE_TIMEOUT_SECONDS = 120
ARABIC_SENTENCE = "زود حركة المرور بنسبة 50%"

# (sidebar slug, expected English page title)
PAGES: tuple[tuple[str, str], ...] = (
    ("", "Dashboard"),
    ("ai_designer", "AI Network Designer"),
    ("topology", "Topology Editor"),
    ("ip_addressing", "IP Addressing & Subnetting"),
    ("vlan_dhcp", "VLAN & DHCP Planner"),
    ("l3_design", "L3 Design"),
    ("l2_design", "L2 Design"),
    ("routing", "Routing Analysis"),
    ("analytics", "Network Analytics"),
    ("security", "Security Analysis"),
    ("digital_twin", "Digital Twin"),
    ("simulation", "Simulation Lab"),
    ("optimization", "Optimization Center"),
    ("capacity", "Capacity Planning"),
    ("reports", "Reports & Documentation"),
    ("agent_center", "Agent Control Center"),
    ("settings", "Settings"),
)


@dataclass
class Result:
    step: str
    passed: bool
    detail: str
    screenshot: Path


RESULTS: list[Result] = []
EXCEPTION_TEXTS: list[tuple[str, str]] = []


def viewport_name(width: int, height: int) -> str:
    return f"{width}x{height}"


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def target_url() -> str:
    """Return the runtime target URL or explain that it was not supplied."""
    if TARGET_URL is None:
        raise RuntimeError("Target URL is not set; pass it as an argument")
    return TARGET_URL


def cell(text: str) -> str:
    return " ".join(text.replace("|", "\\|").split())


def screenshot_path(width: int, height: int, step: str) -> Path:
    path = OUT_DIR / viewport_name(width, height) / f"{slug(step)}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def shot(page: Page, width: int, height: int, step: str) -> Path:
    path = screenshot_path(width, height, step)
    page.screenshot(path=str(path), full_page=True)
    return path


def add_result(
    step: str,
    passed: bool,
    detail: str,
    screenshot: Path,
) -> None:
    RESULTS.append(Result(step, passed, detail, screenshot))


def app_frame(page: Page, timeout_seconds: int = 60) -> Frame:
    """Return the active Streamlit application iframe once it has rendered."""
    for _ in range(timeout_seconds * 4):
        for frame in page.frames:
            if "/~/+/" in frame.url:
                try:
                    if (
                        frame.locator('[data-testid="stApp"]').count()
                        and frame.locator("h1").count()
                    ):
                        return frame
                except Exception:  # noqa: BLE001, S110 - frame may be detaching
                    pass
        page.wait_for_timeout(250)
    raise RuntimeError("Streamlit app iframe did not become ready")


def wake_and_wait(page: Page, timeout_seconds: int = WAKE_TIMEOUT_SECONDS) -> Frame:
    """Wake a sleeping Cloud app if needed, then wait for its iframe."""
    deadline_seconds = timeout_seconds
    for _ in range(deadline_seconds * 2):
        wake = page.get_by_role("button", name=re.compile(r"wake\s*up", re.IGNORECASE))
        if wake.count() and wake.first.is_visible():
            wake.first.click()
        try:
            return app_frame(page, timeout_seconds=2)
        except RuntimeError:
            page.wait_for_timeout(500)
    raise RuntimeError(f"App did not wake within {timeout_seconds}s")


def expand_nav(page: Page) -> Frame:
    frame = app_frame(page)
    sidebar = frame.locator('[data-testid="stSidebar"]')
    if sidebar.count() and sidebar.get_attribute("data-collapsed") == "true":
        expand = frame.get_by_role("button", name="Expand sidebar")
        if expand.count() and expand.first.is_visible():
            expand.first.click()
            page.wait_for_timeout(600)
            frame = app_frame(page)
    more = frame.get_by_role("button", name="View 7 more")
    if more.count() and more.first.is_visible():
        more.first.click()
        page.wait_for_timeout(600)
        frame = app_frame(page)
    return frame


def collapse_nav(page: Page) -> Frame:
    frame = app_frame(page)
    sidebar = frame.locator('[data-testid="stSidebar"]')
    if sidebar.count() and sidebar.get_attribute("data-collapsed") != "true":
        collapse = frame.get_by_role("button", name="Collapse sidebar")
        if collapse.count() and collapse.first.is_visible():
            collapse.first.click()
            page.wait_for_timeout(600)
            frame = app_frame(page)
    return frame


def navigate(page: Page, slug: str) -> Frame:
    frame = expand_nav(page)
    if slug:
        link = frame.locator(f'a[href$="/{slug}"]').first
    else:
        link = frame.locator(f'a[href="{target_url()}"]').first
    if not link.count():
        raise RuntimeError(f"Sidebar link not found for {slug or 'dashboard'!r}")
    link.click()
    page.wait_for_timeout(2500)
    collapse_nav(page)
    return app_frame(page)


def wait_for_h1(frame: Frame, expected: str | None, timeout_seconds: int = 30) -> str:
    for _ in range(timeout_seconds * 4):
        titles = frame.locator("h1").all_text_contents()
        if titles and (expected is None or any(t == expected for t in titles)):
            return titles[0].strip()
        frame.page.wait_for_timeout(250)
    raise RuntimeError(f"Expected page title {expected!r} was not visible")


def exception_texts(frame: Frame) -> list[str]:
    return [
        text.strip()
        for text in frame.locator('[data-testid="stException"]').all_text_contents()
        if text.strip()
    ]


def collect_exceptions(step: str, frame: Frame) -> list[str]:
    texts = exception_texts(frame)
    for text in texts:
        EXCEPTION_TEXTS.append((step, text))
    return texts


def check_page(
    page: Page,
    frame: Frame,
    width: int,
    height: int,
    slug: str,
    expected_title: str,
) -> None:
    step = f"{viewport_name(width, height)} / page / {expected_title}"
    path = shot(page, width, height, step)
    try:
        title = wait_for_h1(frame, expected_title)
        exceptions = collect_exceptions(step, frame)
        passed = title == expected_title and not exceptions
        detail = f"title={title!r}; exceptions={len(exceptions)}"
        if exceptions:
            detail += f"; first={cell(exceptions[0])[:160]}"
    except Exception as error:  # noqa: BLE001 - report and continue
        passed = False
        detail = f"{type(error).__name__}: {cell(str(error))[:200]}"
    add_result(step, passed, detail, path)


def run_page_visits(page: Page, width: int, height: int) -> None:
    for slug, title in PAGES:
        frame = navigate(page, slug)
        check_page(page, frame, width, height, slug, title)


def load_spine_leaf_sample(page: Page) -> None:
    """Load the small sample used by the later bundle and scenario checks."""
    frame = navigate(page, "")
    wait_for_h1(frame, "Dashboard")
    frame.get_by_role("button", name="Select sample").nth(2).click()
    page.wait_for_timeout(900)
    frame = app_frame(page)
    confirm = frame.get_by_role("button", name="Confirm and load sample")
    confirm.wait_for(state="visible", timeout=15000)
    confirm.click()
    page.wait_for_timeout(2500)
    app_frame(page)


def run_sample_load(page: Page, width: int, height: int) -> None:
    step = f"{viewport_name(width, height)} / flow / spine-leaf sample"
    path = shot(page, width, height, step)
    try:
        load_spine_leaf_sample(page)
        frame = app_frame(page)
        wait_for_h1(frame, "Dashboard")
        body = frame.locator("body").inner_text()
        exceptions = collect_exceptions(step, frame)
        loaded = "SAMPLE - Spine-leaf DC" in body or "6 devices" in body
        passed = loaded and not exceptions
        detail = f"confirm_dialog=seen; loaded={loaded}; exceptions={len(exceptions)}"
    except Exception as error:  # noqa: BLE001
        passed = False
        detail = f"{type(error).__name__}: {cell(str(error))[:200]}"
    add_result(step, passed, detail, path)


def generate_large_topology(page: Page) -> str:
    """Generate a dense mesh so the sweep stays active long enough to cancel."""
    frame = navigate(page, "topology")
    wait_for_h1(frame, "Topology Editor")
    frame.get_by_label("Topology family").click()
    frame.get_by_role("option", name="Full mesh").click()
    page.wait_for_timeout(500)
    frame = app_frame(page)
    nodes = frame.get_by_label("Mesh nodes")
    nodes.fill("63")
    nodes.press("Tab")
    page.wait_for_timeout(300)
    frame = app_frame(page)
    frame.get_by_role("button", name="Generate topology").click()
    for _ in range(60):
        page.wait_for_timeout(250)
        frame = app_frame(page)
        if "1953 links" in frame.locator("body").inner_text():
            return "Full mesh 63 nodes / 1953 links"
    raise RuntimeError("Large topology generation did not report 1953 links")


def run_sweep_cancel(page: Page, width: int, height: int) -> None:
    step = f"{viewport_name(width, height)} / flow / sweep + cancel"
    path = screenshot_path(width, height, step)
    try:
        topology = generate_large_topology(page)
        frame = navigate(page, "simulation")
        wait_for_h1(frame, "Simulation Lab")
        frame.get_by_text("N-2 (pairs from a chosen subset)", exact=True).click()
        page.wait_for_timeout(600)
        frame = app_frame(page)
        for label in ("Link subset", "Device subset"):
            frame.get_by_label(label).click()
            page.wait_for_timeout(250)
            frame.get_by_role("option", name="Select all").click()
            page.wait_for_timeout(250)
            page.keyboard.press("Escape")
            frame = app_frame(page)
        max_pairs = frame.get_by_label("Max failure pairs")
        max_pairs.focus()
        max_pairs.press("End")
        frame.get_by_label("Result slice").focus()
        frame.get_by_label("Result slice").press("Home")
        page.wait_for_timeout(300)
        frame = app_frame(page)
        shot(page, width, height, step)
        frame.get_by_role("button", name="Run sweep").click()
        cancelled = False
        for _ in range(1200):
            frame = app_frame(page)
            cancel = frame.get_by_role("button", name="Cancel sweep")
            if cancel.count() and cancel.is_enabled():
                cancel.click()
                cancelled = True
                break
            page.wait_for_timeout(25)
        page.wait_for_timeout(2500)
        frame = app_frame(page)
        sweep_exceptions = collect_exceptions(step, frame)
        load_spine_leaf_sample(page)
        frame = app_frame(page)
        body = frame.locator("body").inner_text()
        restored = "SAMPLE - Spine-leaf DC" in body or "6 devices" in body
        exceptions = sweep_exceptions + collect_exceptions(step, frame)
        passed = cancelled and restored and not exceptions
        detail = (
            f"topology={topology}; run=clicked; "
            f"cancel={'clicked' if cancelled else 'stayed disabled'}; "
            f"sample_restored={restored}; exceptions={len(exceptions)}"
        )
    except Exception as error:  # noqa: BLE001
        passed = False
        detail = f"{type(error).__name__}: {cell(str(error))[:200]}"
    add_result(step, passed, detail, path)


def run_arabic_scenario(page: Page, width: int, height: int) -> None:
    step = f"{viewport_name(width, height)} / flow / Arabic scenario"
    path = shot(page, width, height, step)
    try:
        frame = app_frame(page)
        frame.get_by_label("Scenario sentence").fill(ARABIC_SENTENCE)
        frame.get_by_role("button", name="Interpret sentence").click()
        page.wait_for_timeout(1500)
        frame = app_frame(page)
        body = frame.locator("body").inner_text()
        deterministic = "Draft from deterministic parser" in body
        frame.get_by_role("button", name="Use in scenario form").click()
        page.wait_for_timeout(2000)
        frame = app_frame(page)
        frame.get_by_role("button", name="Run scenario").click()
        page.wait_for_timeout(2500)
        frame = app_frame(page)
        body = frame.locator("body").inner_text()
        ran = "AI-assisted traffic scale" in body
        exceptions = collect_exceptions(step, frame)
        passed = deterministic and ran and not exceptions
        detail = (
            f"sentence={ARABIC_SENTENCE!r}; deterministic={deterministic}; "
            f"ran={ran}; exceptions={len(exceptions)}"
        )
    except Exception as error:  # noqa: BLE001
        passed = False
        detail = f"{type(error).__name__}: {cell(str(error))[:200]}"
    add_result(step, passed, detail, path)


def run_bundle_save(page: Page, width: int, height: int) -> Path | None:
    step = f"{viewport_name(width, height)} / flow / save bundle"
    path = shot(page, width, height, step)
    saved: Path | None = None
    try:
        frame = navigate(page, "digital_twin")
        wait_for_h1(frame, "Digital Twin")
        frame.get_by_role("button", name="Prepare bundle").click()
        page.wait_for_timeout(1800)
        frame = app_frame(page)
        download_button = frame.get_by_role("button", name="Download project bundle")
        download_button.wait_for(state="visible", timeout=15000)
        with page.expect_download(timeout=60000) as info:
            download_button.click()
        download = info.value
        saved = OUT_DIR / f"{viewport_name(width, height)}-bundle.zip"
        download.save_as(str(saved))
        exceptions = collect_exceptions(step, frame)
        passed = saved.stat().st_size > 0 and not exceptions
        detail = (
            f"file={download.suggested_filename}; bytes={saved.stat().st_size}; "
            f"exceptions={len(exceptions)}"
        )
    except Exception as error:  # noqa: BLE001
        passed = False
        detail = f"{type(error).__name__}: {cell(str(error))[:200]}"
    add_result(step, passed, detail, path)
    return saved


def run_bundle_open(
    page: Page,
    width: int,
    height: int,
    bundle: Path | None,
) -> None:
    step = f"{viewport_name(width, height)} / flow / open bundle"
    path = shot(page, width, height, step)
    try:
        if bundle is None or not bundle.exists():
            raise RuntimeError("No saved bundle was available to reopen")
        page.reload(wait_until="domcontentloaded", timeout=120000)
        wake_and_wait(page)
        frame = navigate(page, "digital_twin")
        wait_for_h1(frame, "Digital Twin")
        frame.locator('input[type="file"]').set_input_files(str(bundle))
        page.wait_for_timeout(1800)
        frame = app_frame(page)
        confirm = frame.get_by_role("button", name="Confirm import")
        confirm.wait_for(state="visible", timeout=15000)
        confirm.click()
        page.wait_for_timeout(2000)
        frame = app_frame(page)
        body = frame.locator("body").inner_text()
        imported = "SAMPLE - Spine-leaf DC" in body or "6 devices" in body
        exceptions = collect_exceptions(step, frame)
        passed = imported and not exceptions
        detail = f"imported={imported}; exceptions={len(exceptions)}"
    except Exception as error:  # noqa: BLE001
        passed = False
        detail = f"{type(error).__name__}: {cell(str(error))[:200]}"
    add_result(step, passed, detail, path)


def download_pdf(
    page: Page,
    frame: Frame,
    width: int,
    height: int,
    label: str,
    button_name: str | re.Pattern[str],
) -> None:
    step = f"{viewport_name(width, height)} / flow / {label} executive PDF"
    path = shot(page, width, height, step)
    try:
        button = frame.get_by_role("button", name=button_name)
        button.wait_for(state="visible", timeout=15000)
        with page.expect_download(timeout=60000) as info:
            button.click()
        download = info.value
        saved = OUT_DIR / f"{viewport_name(width, height)}-{slug(label)}-executive.pdf"
        download.save_as(str(saved))
        payload = saved.read_bytes()
        exceptions = collect_exceptions(step, frame)
        passed = bool(payload) and payload.startswith(b"%PDF") and not exceptions
        detail = (
            f"file={download.suggested_filename}; bytes={len(payload)}; "
            f"prefix={payload[:5]!r}; exceptions={len(exceptions)}"
        )
    except Exception as error:  # noqa: BLE001
        passed = False
        detail = f"{type(error).__name__}: {cell(str(error))[:200]}"
    add_result(step, passed, detail, path)


def run_pdfs(page: Page, width: int, height: int) -> None:
    frame = navigate(page, "reports")
    wait_for_h1(frame, "Reports & Documentation")
    download_pdf(page, frame, width, height, "english", "Download executive PDF")

    step = f"{viewport_name(width, height)} / flow / switch to Arabic"
    path = shot(page, width, height, step)
    try:
        frame = navigate(page, "settings")
        wait_for_h1(frame, "Settings")
        frame = collapse_nav(page)
        frame.get_by_text("العربية", exact=True).click()
        page.wait_for_timeout(1800)
        frame = app_frame(page)
        wait_for_h1(frame, None)
        passed = frame.locator("h1").first.inner_text().strip() == "الإعدادات"
        detail = f"language=Arabic; title={frame.locator('h1').first.inner_text().strip()!r}"
    except Exception as error:  # noqa: BLE001
        passed = False
        detail = f"{type(error).__name__}: {cell(str(error))[:200]}"
    add_result(step, passed, detail, path)

    frame = navigate(page, "reports")
    wait_for_h1(frame, None)
    download_pdf(
        page,
        frame,
        width,
        height,
        "arabic",
        re.compile(r"تنزيل الملخص التنفيذي.*PDF"),
    )


def run_viewport(browser: Browser, width: int, height: int) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        accept_downloads=True,
    )
    page = context.new_page()
    try:
        page.goto(target_url(), wait_until="domcontentloaded", timeout=120000)
        wake_and_wait(page)
        run_page_visits(page, width, height)
        run_sample_load(page, width, height)
        run_sweep_cancel(page, width, height)
        run_arabic_scenario(page, width, height)
        bundle = run_bundle_save(page, width, height)
        run_bundle_open(page, width, height, bundle)
        run_pdfs(page, width, height)
    finally:
        context.close()


def print_report() -> None:
    print("\n| step | pass/fail | detail | screenshot path |")
    print("| --- | --- | --- | --- |")
    for result in RESULTS:
        relative = result.screenshot.relative_to(ROOT).as_posix()
        flag = "pass" if result.passed else "FAIL"
        print(
            f"| {cell(result.step)} | {flag} | {cell(result.detail)} | "
            f"{relative} |"
        )

    print("\nEXCEPTION TEXT (verbatim):")
    if EXCEPTION_TEXTS:
        for step, text in EXCEPTION_TEXTS:
            print(f"- [{step}]\n{text}")
    else:
        print("- none")

    print("\nNOT VERIFIED:")
    for item in (
        "visual correctness, layout, color, contrast, or typography",
        "Arabic glyph rendering, shaping, or RTL alignment beyond visible labels",
        "PDF page content, glyph coverage, or visual layout beyond %PDF and bytes",
        "calculation correctness or engineering validity of any result",
        "provider/LLM response quality; no secrets were read or written",
        "mobile ergonomics beyond selector reachability at 390x844",
    ):
        print(f"- {item}")

    print("\nHUMAN CHECKS:")
    for item in (
        "review screenshots in e2e_out/ at both viewports",
        "open both downloaded PDFs and inspect pages visually",
        "inspect Arabic text direction and PDF glyphs",
        "confirm the mobile sidebar flow feels usable in a real browser",
    ):
        print(f"- {item}")


def main(argv: Sequence[str] | None = None) -> int:
    global TARGET_URL
    parser = argparse.ArgumentParser(
        description="Black-box Playwright smoke test for a deployed Streamlit app"
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="Target app URL, including scheme (required)",
    )
    args = parser.parse_args(argv)
    if not args.url:
        print("error: a target URL is required", file=sys.stderr)
        parser.print_usage(sys.stderr)
        return 2
    TARGET_URL = args.url.rstrip("/") + "/"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for width, height in VIEWPORTS:
                run_viewport(browser, width, height)
        finally:
            browser.close()
    print_report()
    return 0 if all(result.passed for result in RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
