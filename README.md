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

Open the URL printed by Streamlit. The **Dashboard** is the root page and the sidebar lists all 15 pages:

1. Dashboard
2. AI Network Designer
3. Topology Editor
4. IP Addressing & Subnetting
5. VLAN & DHCP Planner
6. Routing Analysis
7. Network Analytics
8. Digital Twin
9. Simulation Lab
10. Optimization Center
11. Capacity Planning
12. Security Analysis
13. Agent Control Center
14. Reports & Documentation
15. Settings

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

At `v1.0.0-rc1`:

- `pytest -q`: **975 passed**
- `pytest -q -m smoke`: **12 passed, 963 deselected**
- `ruff check .`: **All checks passed!**
- Clean Python 3.11 venv: **975 passed**
- Clean Python 3.12 venv: **975 passed**
- `pip-audit -r requirements.txt`: **No known vulnerabilities found**
- Headless local startup: health `ok`, root title `Dashboard`, `exceptions: 0`

These checks were run locally on Windows. A real browser, a deployed Community Cloud instance, live Groq responses, PDF visual layout, and remote GitHub Actions execution were **not** verified. See [docs/TEST_STRATEGY.md](docs/TEST_STRATEGY.md).

## Documentation

- [Architecture](docs/ARCHITECTURE.md) - layers, data flow, state, and deployment boundaries.
- [API contracts](docs/API_CONTRACTS.md) - Python-level engineering, agent, reporting, and LLM contracts.
- [Agent specifications](docs/AGENT_SPECIFICATIONS.md) - allowlists, workflow, budgets, traces, and no-key behavior.
- [Test strategy](docs/TEST_STRATEGY.md) - test layers, evidence, profile, scans, and unverified items.
- [Deployment](docs/DEPLOYMENT.md) - exact manual Streamlit Community Cloud steps.
- [Release audit](docs/RELEASE_AUDIT.md) - criterion-by-criterion Blueprint §11/§16 review.
- [Runtime limits](docs/RUNTIME_LIMITS.md) - every compiled cap and input guard.
- [Roadmap](docs/ROADMAP.md) - post-RC verification and future candidates.
- [Changelog](docs/CHANGELOG.md) - phase history and release notes.
- [Known limitations](KNOWN_LIMITATIONS.md) - scope, model fidelity, and verification gaps.
- [Current status](CURRENT_STATUS.md) - living implementation and evidence record.

## Dependencies

Eleven pinned packages are declared inline in `requirements.txt`. `pyarrow==23.0.1` is listed directly so Community Cloud installs need no separate constraints file; it is already required by Streamlit, so this is not a new runtime dependency. No `packages.txt` is needed.

## License

No `LICENSE` file is included in this release candidate. The owner must choose and add one before public distribution if desired.
