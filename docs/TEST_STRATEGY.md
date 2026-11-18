# Test strategy

The release strategy is layered: pure logic gets fast unit tests, UI behavior gets Streamlit `AppTest`, release invariants get integration-style tests, and deployment assumptions get local headless and clean-environment checks. Real-browser, deployed-cloud, live-provider, and remote-CI checks are explicitly listed as unverified rather than assumed.

## Commands

Run from the repository root:

```powershell
& ".venv\Scripts\python.exe" -m pytest -q
& ".venv\Scripts\python.exe" -m pytest -q -m smoke
& ".venv\Scripts\python.exe" -m ruff check .
& ".venv\Scripts\python.exe" scripts\profile_phase12.py
& ".venv\Scripts\python.exe" scripts\profile_phase12.py --no-memory
```

`pytest.ini` defines the `smoke` marker. The marker selects a fast regression subset; it does not replace the full suite.

## Test layers

| Layer | What it covers | Representative location |
|---|---|---|
| Pure engine unit tests | Graph algorithms, CIDR/VLSM arithmetic, VLAN/DHCP, routing, analysis, scenario mechanics, optimization objectives, forecast rules, capacity evaluation, security policy/risk | `tests/unit/<domain>/` |
| Model and schema tests | Pydantic validation, compatibility, canonical serialization, typed errors, sample fixtures | `tests/unit/schemas/`, `tests/unit/digital_twin/` |
| Service tests | Report IR, provenance, consistency, exports, design health, LLM provider fakes and budgets | `tests/unit/services/` |
| Agent tests | Tool registry, plan validation, orchestrator retries/replans/stop reasons, critic, documentation and security agents | `tests/unit/agents/` |
| UI tests with `AppTest` | All 15 pages, no-key states, empty states, widget flows, navigation, cache behavior, disclosures | `tests/unit/ui/` |
| Release acceptance | Blueprint §11/§16 invariants, adversarial input, secret containment, deployment artifacts | `tests/unit/release/` |

## Suite composition at `v1.0.0-rc1`

`pytest --collect-only -q` collected 975 tests.

| Area | Tests |
|---|---:|
| addressing | 39 |
| agents | 91 |
| analysis | 41 |
| capacity | 14 |
| digital_twin | 55 |
| forecasting | 18 |
| optimization | 92 |
| release (Phase 15) | 37 |
| routing | 50 |
| schemas | 113 |
| security | 55 |
| services | 79 |
| simulation | 54 |
| topology | 94 |
| ui | 105 |
| vlan | 36 |
| root test files | 2 |
| **Total** | **975** |

The `release` directory contains:

- `test_phase15_acceptance.py` (18): IP overlap/duplicates, graph-walk validity, failure exclusion, reproducible simulation and optimization, hard constraints, invalid LLM output, report/computed-value consistency, no-key all-pages behavior, and the security criticality decision.
- `test_phase15_hardening.py` (14): payload caps, malformed/hidden/duplicate JSON, path-like identifiers, CSV findings and formula neutralization, prompt-injection tool allowlisting, secret containment, dynamic-execution/disk-write source scan, gitignore/secrets example, and dependency pins.
- `test_phase15_deployment.py` (5): headless/bounded Streamlit config, CI workflow contents, deployment docs and secrets placeholder, in-app release limitations with no key, and About-menu scope.

## Release evidence

Verbatim final outputs are reproduced in the final release report and summarized here.

| Check | Command | Result |
|---|---|---|
| Full suite (main venv) | `pytest -q` | `975 passed in 33.79s` |
| Smoke subset | `pytest -q -m smoke` | `12 passed, 963 deselected in 8.55s` |
| Lint | `ruff check .` | `All checks passed!` |
| Clean Python 3.11 venv | `python -m pytest -q` then `python -m ruff check .` | `975 passed in 38.79s`; `All checks passed!` |
| Clean Python 3.12 venv | `python -m pytest -q` then `python -m ruff check .` | `975 passed in 44.79s`; `All checks passed!` |
| Dependency audit | `pip-audit -r requirements.txt --progress-spinner off` | `No known vulnerabilities found` |
| Headless startup | local Streamlit with agent API, no `GROQ_*` env vars | `health: ok`, `agent status: ready`, root title `Dashboard`, `exceptions: 0` |

## Clean-clone note

A fresh 3.11 environment initially resolved `pyarrow==26.0.1`, whose wheel was blocked on this Windows host by an application-control policy. `pyarrow==17.0.0` loaded but was vulnerable (`PYSEC-2026-113`, fix `23.0.1`). The final `constraints.txt` pins `pyarrow==23.0.1`, which is a transitive Streamlit dependency, not an eleventh direct package. Clean 3.11 and 3.12 installs then passed the full suite, lint, and audit. Community Cloud uses Linux; that platform was not exercised locally.

## Performance profile

`scripts/profile_phase12.py` was rerun at the release tree. The tracemalloc run recorded peak Python allocations; the `--no-memory` run gives wall-clock numbers.

| Operation | With tracing (s / peak MiB) | No memory (s) | Interpretation |
|---|---:|---:|---|
| Generate max-size topology | 0.075 / 1.4 | 0.005 | Well under budget. |
| Build max twin | 0.207 / 0.8 | 0.084 | Well under budget. |
| All-pairs routing | 3.812 / 4.8 | 1.094 | Well under budget. |
| Evaluate with MAX_DEMANDS | 5.226 / 4.6 | 0.860 | Well under budget. |
| Genetic at configured maxima | 65.230 / 7.1 | 61.206 | Script flags >5 s wall clock; bounded by `MAX_OPTIMIZATION_RUNTIME_SECONDS=60`. |
| NSGA-II at configured maxima | 67.530 / 6.4 | 60.903 | Script flags >5 s wall clock; bounded by the same hard cap. |
| Report build | 12.971 / 6.2 | 2.954 | Tracing overhead dominates; no-memory run is under 5 s. |
| PDF build | 9.636 / 8.7 | 1.680 | Tracing overhead dominates; no-memory run is under 5 s. |

The script flags any no-memory row over 5 seconds, so the two user-triggered maximum optimization searches are marked `yes`. They are intentional bounded operations, not unbounded loops. Peak traced allocation was 8.7 MiB, far below the script's 300 MiB memory threshold. These are Python-allocation measurements, not total process RSS, and they are not Community Cloud measurements.

## Security and adversarial checks

- Tree and full-history scans for common provider-key, private-key, and token
  patterns produced no matches.
- No tracked `.env`, `.streamlit/secrets.toml`, `.pem`, `.key`, `.pfx`, or `.p12` file exists.
- Runtime source scan found no dynamic execution, shell invocation, or direct disk writes outside tests.
- Guarded parsers reject oversized/deep/duplicate/hidden JSON, malformed numbers, path-like identifiers, and oversized CSV payloads with typed errors.
- Every CSV writer neutralizes formula prefixes; signed numeric values remain numeric.
- A prompt-injection payload telling an LLM to call an unlisted tool fails because the trace records only the allowlisted tool.

## Not verified

- Real browser rendering, screenshots, or client-side JavaScript behavior.
- A deployed Streamlit Community Cloud Free instance and its actual resource behavior.
- Live Groq requests, model availability, or provider uptime.
- PDF visual layout, font rendering, and non-Latin shaping.
- Remote execution of `.github/workflows/ci.yml`.
- Total process RSS on Community Cloud; the profile measures tracemalloc Python allocations only.
