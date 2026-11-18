# Runtime limits and input bounds

NetArchitect AI targets the Streamlit Community Cloud Free tier. Every bound
below is compiled into `config/limits.py` or `.streamlit/config.toml`; the UI
never raises these ceilings. Limits are enforced before work is done, and
rejections are explicit rather than silent truncation.

## Bounds table

| Area | Bound | Value | Enforcement / failure behavior |
|---|---:|---:|---|
| Topology size | Devices | 500 | `enforce_limits()` raises `LimitsExceededError` before graph work. |
| Topology size | Links | 2,000 | Same as above. |
| Addressing | Subnets per plan | 256 | Engine rejects larger requests. |
| Addressing | Hosts requested per subnet | 1,000,000 | Address arithmetic is formula-based; this caps user requests, not loop iterations. |
| Routing | Alternative paths per pair | 10 | k-shortest-path enumeration is bounded. |
| Simulation | Scenarios retained | 20 | Old sessions cannot grow without limit. |
| Simulation | Entities per scenario | 50 | Each scenario names at most 50 links, devices, demands, or expansion records. |
| Simulation | Wall-clock per run | 30 s | A deadline is checked during the run. |
| Security model | Zones | 32 | Editor and analysis stay deterministic. |
| Security model | Firewall rules | 128 | First-match flow checks stay linear and bounded. |
| Security model | Services | 32 | Named service list is capped. |
| Security model | Assumptions | 50 | Model metadata is capped. |
| Security agent | Modeled flow checks | 20 | One agent run cannot flood the flow engine. |
| Digital twin | Demands | 100 | Twin import and editors reject more. |
| Digital twin | Snapshots retained | 20 | Oldest snapshots are bounded by count. |
| Digital twin | Snapshot bytes retained | 2,000,000 | Oldest snapshots are bounded by serialized size as well. |
| Optimization | Iterations per run | 1,000 | Search loop hard cap. |
| Optimization | Population size | 200 | Population-based algorithms are capped. |
| Optimization | Candidate evaluations | 20,000 | Every candidate is a full modeled evaluation. |
| Optimization | Search time | 20 s default / 60 s hard cap | Deadline checked before each candidate. |
| Optimization | Runs retained | 20 | Session history is bounded. |
| Capacity planning | Observations across series | 2,000 | CSV parsing and chart payload size are bounded. |
| Capacity planning | Series | 20 | Session limit on separate time series. |
| Capacity planning | Forecast horizon | 24 steps; at most 50% of history | Both absolute and ratio caps apply. |
| Capacity planning | Full analysis time | 30 s | Includes projected-step and upgrade evaluations. |
| Capacity planning | Evaluations per analysis | 240 | One bound per projected demand set. |
| Capacity planning | Runs retained | 20 | Session history is bounded. |
| Agent workflow | Steps | 50 | Workflow stops before unbounded task chains. |
| Agent workflow | Wall-clock | 120 s | Checked across the complete workflow. |
| Agent workflow | Retries per recoverable failure | 3 | Includes the first attempt. |
| Agent workflow | Selective re-plans | 2 | Prevents a validation / re-plan loop. |
| LLM budget | Calls per browser session | 20 | Includes structured-output repair attempts. |
| LLM budget | Tokens per browser session | 60,000 | Prompt plus completion across all requests. |
| LLM robustness | Schema repair retries | 2 | Bounded response repair after invalid JSON. |
| LLM robustness | Rate-limit retries | 2 | Bounded additional attempts after HTTP 429. |
| LLM robustness | Backoff | 1 s base, 30 s cap | Exponential backoff including `Retry-After`. |
| LLM robustness | Request timeout | 30 s | One HTTP request cannot hang the session. |
| LLM robustness | Completion tokens | 4,096 | Provider response length is capped. |
| Untrusted JSON / text | Payload size | 2,000,000 bytes | Checked before decode or parse. |
| Untrusted CSV | Payload size | 1,000,000 bytes | Checked before row parsing. |
| Untrusted JSON | Nesting depth | 64 | Linear pre-scan prevents recursion from untrusted nesting. |
| Untrusted JSON | Object keys | 1,000 | Object width is capped during decode. |
| Untrusted JSON | String / key length | 4,000 characters | Hidden controls and bidi overrides are rejected. |
| Untrusted identifiers | Length | 128 characters | Device, link, series, zone, and similar ids are bounded and path-like values rejected. |
| Untrusted numbers | Magnitude | 1e12 | NaN, infinity, and oversized values are rejected before models see them. |
| Reports | Rows per table | 500 | Longer results are truncated with an explicit "showing first N of M rows" note. |
| Reports | Export size | 5,000,000 bytes | Markdown, JSON, CSV bundle, and PDF exports are built in memory under this cap. |

## Execution and injection surface

- No runtime path uses `eval`, `exec`, `subprocess`, `os.system`, `shell=True`, or
  `__import__`. A release test scans every non-test Python module for these
  constructs.
- No runtime path opens files or writes to disk. Exports and reports are built
  in memory. A release test scans every non-test Python module for direct file
  writes.
- All CSV writers pass cells through `core.csv_safe.neutralize_cell`, so a cell
  beginning with `=`, `+`, `-`, `@`, tab, or carriage return cannot become a
  spreadsheet formula. Plain signed numbers remain numeric.
- Untrusted JSON and CSV pass through `core.inputs` before Pydantic validation.
  Duplicate keys, hidden formatting characters, path-like identifiers, deep
  nesting, and non-finite numbers are rejected with typed errors.
- Prompt-injection text in optional LLM replies is treated as untrusted data.
  Agent outputs must still satisfy their Pydantic schemas, and numeric design
  values must still match computed values; a release test verifies that an
  "ignore previous instructions" payload cannot call an unlisted tool.
- API keys are never displayed, logged, traced, serialized into reports or
  exports, or written to disk. A release test checks all of those sinks.
