# NetArchitect AI

- **Release:** `v1.0.0-rc1` (2026-11-18)
- **Target:** Streamlit Community Cloud Free
- **Status:** release candidate prepared locally; deployment by the repository owner is still required.

NetArchitect AI is a deterministic, design-time network engineering workspace. It generates and edits topologies, validates IP and VLAN plans, analyzes routing and graph properties, maintains a bounded digital twin, runs reproducible simulations and multi-objective optimization, performs capacity and offline security analysis, and produces provenance-tagged reports with in-memory exports.

It is **not** a network scanner, penetration tester, hardware emulator, device controller, or a source of guaranteed operational outcomes. Results are modeled from the current twin and stated assumptions. See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

## Quick start

Python 3.11 and Python 3.12 were verified for this release. Run commands from the repository root, because Community Cloud also executes from the root.

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

**macOS / Linux:**

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

For development and CI, install the tools separately (Cloud does **not** install this file):

```bash
python -m pip install -r requirements-dev.txt
```

Open the URL printed by Streamlit. The **Dashboard** is the root page and the sidebar lists all 17 pages:

1. Dashboard
2. AI Network Designer
3. Topology Editor
4. IP Addressing & Subnetting
5. VLAN & DHCP Planner
6. L3 Design
7. L2 Design
8. Routing Analysis
9. Network Analytics
10. Security Analysis
11. Digital Twin
12. Simulation Lab
13. Optimization Center
14. Capacity Planning
15. Reports & Documentation
16. Agent Control Center
17. Settings

## Sharing and reports

The `feature/v2-share` package adds in-memory project bundle Save/Open on the Digital Twin page, with a preview, confirmation, and import-as-new-snapshot. Bundles carry the twin, retained runs, snapshots, provenance, decisions, and secret-free settings; import is guarded against hostile ZIP input. No bundle is written by the app.

Reports & Documentation includes a two-page executive summary in English or Arabic, generated only from computed data with per-value provenance and explicit not-run notes. PDFs embed a bundled SIL OFL Arabic font in Arabic mode, and the pure interchange exporters cover GraphML, Mermaid, inventory CSV, draw.io mxfile, and a bounded vector topology figure.

## Command-line interface

The deterministic engines are also available without Streamlit through the standard-library CLI. It never imports the web UI, never reads a clock, and writes to disk only when you pass an explicit `--out` path.

```powershell
python -m netarchitect info
python -m netarchitect validate path\to\twin.json
python -m netarchitect simulate path\to\twin.json [--scenario path\to\scenario.json]
python -m netarchitect report path\to\twin.json [--format markdown|json] [--out PATH]
python -m netarchitect export path\to\twin.json --format graphml|mermaid|inventory|drawio [--out PATH]
```

All commands emit deterministic UTF-8 output. Exit codes are `0` for success, `1` for a domain/validation error (with a typed JSON error on stderr), and `2` for argparse usage errors. The `export` formats are the same pure interchange exporters used by the app and describe modeled design intent, not device-applied configuration. See [API contracts](docs/API_CONTRACTS.md) for the Python-level equivalents.

## No API key required

Every deterministic engineering page works without external AI access. With no key configured, Settings shows `API key configured No`, the AI Designer uses the structured requirements form, and agent workflows run through real deterministic tools.

Groq is optional. To enable it locally, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` (gitignored) and set top-level keys:

```toml
GROQ_API_KEY = "your-key"
GROQ_MODEL = "your-model"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
```

Never commit the key, paste it into reports, or place it in application logs. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for Community Cloud secrets.

## Verification summary

At `feature/v2-share` B1-B6 on Python 3.12.10:

- `pytest -q`: **1760 passed, 14 deselected in 140.96s (0:02:20)**
- `ruff check .`: **All checks passed!**
- `pytest -q -m smoke`: **13 passed, 1761 deselected in 8.48s**
- `pytest -q -m imports`: **1 passed, 1773 deselected in 66.79s (0:01:06)**
- Runtime-only fresh venv without `pytest`: health `ok`, root status `200`, all 17 pages rendered by `scripts/verify_runtime_only.py`

These checks were run locally on Windows. A real browser, a deployed Community Cloud instance, live Groq responses, owner visual signoff of PDF/topology layout, and remote GitHub Actions execution were **not** verified. See [docs/TEST_STRATEGY.md](docs/TEST_STRATEGY.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - layers, data flow, state, and deployment boundaries.
- [API contracts](docs/API_CONTRACTS.md) - Python-level engineering, agent, reporting, and LLM contracts.
- [Agent specifications](docs/AGENT_SPECIFICATIONS.md) - allowlists, workflow, budgets, traces, and no-key behavior.
- [Test strategy](docs/TEST_STRATEGY.md) - test layers, evidence, profile, scans, and unverified items.
- [LLM evaluation](docs/LLM_EVALUATION.md) - offline golden set, cache checks, and local-only response recording.
- [Deployment](docs/DEPLOYMENT.md) - exact manual Streamlit Community Cloud steps.
- [Release audit](docs/RELEASE_AUDIT.md) - criterion-by-criterion Blueprint §11/§16 review.
- [Runtime limits](docs/RUNTIME_LIMITS.md) - every compiled cap and input guard.
- [Roadmap](docs/ROADMAP.md) - post-RC verification and future candidates.
- [Changelog](docs/CHANGELOG.md) - phase history and release notes.
- [Known limitations](KNOWN_LIMITATIONS.md) - scope, model fidelity, and verification gaps.
- [Current status](CURRENT_STATUS.md) - living implementation and evidence record.

## Dependencies

Nine pinned runtime packages are declared inline in `requirements.txt`. `pyarrow==23.0.1` is listed directly so Community Cloud installs need no separate constraints file; it is already required by Streamlit, so this is not a new runtime dependency. No `packages.txt` is needed.

Development-only tools (`pytest`, `ruff`, `hypothesis`) live in `requirements-dev.txt`, which starts with `-r requirements.txt`. `scripts/verify_runtime_only.py` checks that a fresh runtime-only install starts Streamlit headless and renders all 17 pages without pytest.

## License

No `LICENSE` file is included in this release candidate. The owner must choose and add one before public distribution if desired.
