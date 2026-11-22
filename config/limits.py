"""Bounded resource limit constants for NetArchitect AI.

These constants cap nodes, links, scenarios, optimization runs, and agent
workflows so the application stays within Streamlit Community Cloud Free
resource limits. This module contains no logic - only constants with
explanatory comments.
"""

# Maximum number of network nodes (devices) modeled in a single topology.
MAX_NODES: int = 500

# Maximum number of links (edges) modeled in a single topology.
MAX_EDGES: int = 2000

# Maximum number of subnets in one addressing plan or VLSM allocation.
MAX_SUBNETS: int = 256

# Maximum number of host addresses requested or assigned for one subnet.
# Address arithmetic never enumerates hosts, so this caps user requests rather
# than loop iterations.
MAX_HOSTS_PER_SUBNET: int = 1_000_000

# Maximum number of alternative simple paths returned for one source/destination
# pair. Keeps k-shortest-path enumeration bounded on the deployment target.
MAX_ALTERNATIVE_PATHS: int = 10

# Maximum number of equal-cost paths considered by ECMP and capacity-aware
# admission control. When more paths exist, the lexicographically first paths
# are used and the result carries an explicit truncation warning.
MAX_ECMP_PATHS: int = 16

# Maximum number of device/link pairs evaluated by an N-2 failure sweep. The
# chosen subset may be larger, but only the lexicographically first capped pairs
# are evaluated and the result records the truncation.
MAX_N2_PAIRS: int = 200

# Maximum number of shared-risk groups stored on one twin. Groups are design
# annotations, so this keeps validation and sweep planning bounded.
MAX_SHARED_RISK_GROUPS: int = 20

# Maximum members in one shared-risk group. Reuses the scenario element cap so
# one modeled correlated failure cannot exceed one scenario's entity budget.
MAX_SHARED_RISK_MEMBERS: int = 50

# Maximum number of what-if scenarios retained for comparison. The previous
# value of 50 could reserve roughly 37 MiB of session data for the largest twin.
# The default is lowered to 20 for free-tier safety; this is a retained-history
# cap, not an interactive work budget.
MAX_SCENARIOS: int = 20

# Maximum number of entities (links, devices, demands, or expansion records) a
# single what-if scenario may name or add.
MAX_SCENARIO_ELEMENTS: int = 50

# Maximum zones in one modeled security design. Zones are design constructs,
# not live network hosts, so this bound keeps editors and analysis deterministic.
MAX_ZONES: int = 32

# Maximum firewall rules in one modeled policy. First-match evaluation is linear
# in rule count, so this keeps interactive flow checks bounded.
MAX_FIREWALL_RULES: int = 128

# Maximum named services in one modeled policy.
MAX_SERVICES: int = 32

# Maximum assumptions recorded with one security model.
MAX_SECURITY_ASSUMPTIONS: int = 50

# Maximum hop depth for the bounded modeled reachability closure used by the
# security blast-radius view. The closure is also bounded by the zone count, so
# this is an explicit, visible cap rather than an unbounded graph traversal.
MAX_BLAST_RADIUS_HOPS: int = 8

# Maximum member devices probed per zone when deciding whether a routed path
# exists between two modeled zones. Keeps pairwise routing probes bounded on
# the free tier even if a zone names many devices.
MAX_ROUTE_PROBE_DEVICES: int = 8

# Maximum deterministic policy-optimization proposals shown for one design.
# Proposals are inert; the cap keeps the decision table and proposal list small
# enough for an interactive free-tier session.
MAX_OPTIMIZATION_PROPOSALS: int = 12

# Maximum high-criticality zones with an individual inert microsegmentation
# suggestion. Each suggestion recomputes before/after modeled metrics, so the
# cap keeps interactive analysis bounded on the free tier.
MAX_MICROSEGMENTATION_PROPOSALS: int = 4

# Maximum inert rules emitted across one microsegmentation suggestion. The grid
# is large on paper, so the cap keeps the proposal list reviewable.
MAX_MICROSEGMENTATION_RULES: int = 48

# Maximum number of snapshots retained for one digital twin.
MAX_SNAPSHOTS: int = 20

# Maximum number of traffic demands stored in one digital twin.
MAX_DEMANDS: int = 100

# Maximum total serialized bytes of all snapshots retained for one digital
# twin. Bounds session memory on the Streamlit Community Cloud free tier.
MAX_TWIN_SNAPSHOT_BYTES: int = 2_000_000

# Maximum iterations for any single optimization run.
MAX_OPTIMIZATION_ITERATIONS: int = 1000

# Maximum population size for population-based optimization algorithms.
MAX_POPULATION: int = 200

# Maximum number of candidate evaluations for one optimization run. Every
# candidate is a full modeled evaluation, so this bounds CPU and memory.
MAX_EVALUATIONS: int = 20_000

# Default wall-clock seconds for the search phase of one optimization run. The
# previous default of 30 seconds was lowered to 20 for free-tier safety. Users
# may still raise the value to the hard cap below.
DEFAULT_OPTIMIZATION_RUNTIME_SECONDS: int = 20

# Hard cap on the search-phase wall-clock budget. Baseline evaluation is
# performed first and is not counted against this budget. The deadline is checked
# before each candidate evaluation. This is a user-triggered search, not a
# page-rerun cost, so the cap remains above the 5-second interactive target.
MAX_OPTIMIZATION_RUNTIME_SECONDS: int = 60

# Maximum number of optimization runs retained in one session history. A
# 60-second run on the 500-device profile twin keeps about 76 candidates and
# serializes to about 2.4 MiB, so the worst case is roughly 48 MiB.
MAX_OPTIMIZATION_RUNS: int = 20

# Maximum number of caller-supplied hybrid-start candidates accepted by one
# simulated-annealing run. The first candidates are evaluated in order; an
# over-long list is rejected rather than silently truncated.
MAX_SA_INITIAL_CANDIDATES: int = 8

# Bounded robustness analysis defaults. Sensitivity runs re-evaluate a small
# subset of an existing run against perturbed demand/capacity twins, so both the
# candidate count and the wall-clock budget are capped.
DEFAULT_SENSITIVITY_RUNTIME_SECONDS: float = 10.0
MAX_SENSITIVITY_RUNTIME_SECONDS: float = 30.0
MAX_SENSITIVITY_SCENARIOS: int = 4
MAX_SENSITIVITY_CANDIDATES: int = 8

# Maximum wall-clock seconds for a single simulation run.
MAX_SIMULATION_RUNTIME_SECONDS: int = 30

# Maximum attempts an agent may make on a recoverable tool failure, including
# the first attempt. Must be at least 1.
MAX_AGENT_RETRIES: int = 3

# Maximum number of steps in a single agent workflow before it must stop.
MAX_WORKFLOW_STEPS: int = 50

# Maximum wall-clock seconds for one complete agent workflow.
MAX_AGENT_RUNTIME_SECONDS: int = 120

# Maximum characters accepted in one free-text requirements description. The
# requirements agent rejects longer input instead of truncating it silently.
MAX_REQUIREMENTS_TEXT_CHARS: int = 20_000

# Maximum departments the requirements agent may emit from one description.
MAX_REQUIREMENTS_DEPARTMENTS: int = 64

# Maximum constraints, design goals, or assumptions accepted from one
# requirements extraction. Keeps a malformed response from flooding memory/UI.
MAX_REQUIREMENTS_LIST_ITEMS: int = 50

# Maximum clarification questions returned by the requirements agent.
MAX_CLARIFICATION_QUESTIONS: int = 20

# Maximum characters accepted from the critic's optional model-written
# summary. The deterministic verdict never depends on this text.
MAX_CRITIC_SUMMARY_CHARS: int = 1_500

# Maximum characters accepted from the documentation agent's optional
# model-written explanation. It is never treated as a source of design data.
MAX_DOCUMENTATION_EXPLANATION_CHARS: int = 2_000

# Maximum characters accepted from the security agent's optional model-written
# explanation. It is never treated as a source of security data.
MAX_SECURITY_EXPLANATION_CHARS: int = 1_200

# Maximum number of modeled flow checks one security agent run may request.
MAX_SECURITY_FLOW_CHECKS: int = 20

# Maximum number of selective re-plans (re-running the responsible task and its
# dependents) allowed in one workflow. Prevents a validation/re-plan loop.
MAX_AGENT_REPLANS: int = 2

# Maximum number of LLM requests allowed in one browser session. The budget
# covers every request, including structured-output repair attempts.
MAX_LLM_CALLS_PER_SESSION: int = 20

# Maximum total tokens (prompt plus completion) allowed in one browser session.
MAX_LLM_TOKENS_PER_SESSION: int = 60_000

# Maximum repair attempts after a schema-invalid structured LLM response.
MAX_LLM_REPAIR_RETRIES: int = 2

# Maximum additional attempts after an HTTP 429 rate-limit response.
MAX_LLM_RATE_LIMIT_RETRIES: int = 2

# Base exponential-backoff delay, in seconds, for retried LLM requests.
LLM_RETRY_BASE_SECONDS: float = 1.0

# Upper bound, in seconds, on a single backoff wait, including Retry-After.
MAX_LLM_RETRY_AFTER_SECONDS: int = 30

# Maximum wall-clock seconds for one LLM HTTP request.
MAX_LLM_TIMEOUT_SECONDS: int = 30

# Maximum completion tokens requested from the LLM provider.
MAX_LLM_RESPONSE_TOKENS: int = 4_096

# Maximum data rows one report table may contain. Longer engine results are
# truncated with an explicit "showing first N of M rows" note; the report never
# silently drops rows.
MAX_REPORT_TABLE_ROWS: int = 500

# Maximum serialized bytes for one report export (Markdown, JSON, CSV bundle, or
# PDF). Exports are built in memory, so this bounds session memory on the
# Streamlit Community Cloud free tier.
MAX_REPORT_BYTES: int = 5_000_000

# Maximum serialized bytes for one in-memory project bundle (B1). A bundle is a
# ZIP of guarded JSON sections; the cap bounds peak upload memory on the free
# tier and is checked against both the compressed and uncompressed totals.
MAX_BUNDLE_BYTES: int = 5_000_000

# Maximum number of ZIP members in one project bundle. Sections are small, so a
# larger member count is always hostile input rather than a legitimate export.
MAX_BUNDLE_MEMBERS: int = 200

# Minimum observations required in one time series before it can be forecast.
# A chronological evaluation split needs at least this many points so the
# training and held-out portions are both non-trivial.
MIN_FORECAST_POINTS: int = 8

# Maximum observations accepted across all uploaded or generated series in one
# capacity-planning session. Bounds CSV parsing and chart payload size.
MAX_FORECAST_POINTS: int = 2_000

# Maximum number of separate series accepted in one capacity-planning session.
MAX_FORECAST_SERIES: int = 20

# A forecast may cover at most this fraction of the observed history. For
# example, eight observations allow at most four projected steps.
MAX_FORECAST_HORIZON_RATIO: float = 0.5

# Absolute ceiling on projected steps, independent of the history ratio.
MAX_FORECAST_HORIZON_STEPS: int = 24

# Maximum number of modeled network evaluations in one capacity analysis. This
# is distinct from simulation/optimization limits because each step evaluates a
# newly projected demand set.
MAX_CAPACITY_EVALUATIONS: int = 240

# Maximum horizon steps in one capacity analysis. Each step is one full
# simulation evaluation and one row in the utilization-over-time result.
MAX_CAPACITY_HORIZON_STEPS: int = 12

# Maximum wall-clock seconds for one complete capacity analysis, including all
# projected-step and upgrade evaluations.
MAX_CAPACITY_RUNTIME_SECONDS: float = 30.0

# Maximum number of bounded capacity runs retained in one Streamlit session.
MAX_CAPACITY_RUNS: int = 20

# Maximum UTF-8 byte size accepted by one untrusted JSON or text upload. The cap
# is checked before decoding or parsing so a malformed payload cannot consume
# unbounded memory on the free tier.
MAX_INPUT_BYTES: int = 2_000_000

# Maximum UTF-8 byte size accepted from one pasted or uploaded CSV payload. This
# is deliberately below the generic JSON cap because CSV parsing is row-based.
MAX_CSV_INPUT_BYTES: int = 1_000_000

# Maximum nesting depth accepted in untrusted JSON. The depth is checked with a
# linear scan before json.loads so deeply nested input cannot trigger recursion.
MAX_JSON_DEPTH: int = 64

# Maximum number of keys accepted in one untrusted JSON object.
MAX_JSON_OBJECT_KEYS: int = 1_000

# Maximum characters accepted in one untrusted JSON string value or object key.
MAX_INPUT_STRING_CHARS: int = 4_000

# Maximum characters accepted in one identifier (device id, link id, series id,
# zone id, and similar fields) taken from untrusted input.
MAX_IDENTIFIER_CHARS: int = 128

# Largest absolute numeric magnitude accepted from untrusted JSON or CSV input.
# Values beyond this are rejected with a typed finding before model projection.
MAX_INPUT_NUMERIC_MAGNITUDE: float = 1e12

# Maximum number of IPv6 /64 prefix assignments in one dual-stack plan. The
# planner uses prefix arithmetic only, so this caps design size rather than
# host enumeration or loop iterations.
MAX_V6_PREFIXES: int = 256

# Maximum number of modeled NAT rules in one NAT/PAT plan. Sizing and overlap
# checks are linear in rule count, so this keeps interactive review bounded.
MAX_NAT_RULES: int = 64

# Maximum number of OSPF areas in one modeled design. Area ids and membership
# are design annotations; this bound keeps the derivation checks interactive.
MAX_OSPF_AREAS: int = 32

# Configurable *heuristic* device count per OSPF area. Exceeding it produces a
# warning only: this is a planning guideline, NOT an OSPF protocol limit.
DEFAULT_OSPF_AREA_DEVICE_THRESHOLD: int = 50

# Maximum number of inert summarization suggestions emitted by one OSPF review.
MAX_OSPF_SUMMARY_SUGGESTIONS: int = 16

# Maximum number of modeled first-hop gateway redundancy groups on one twin.
MAX_HA_GROUPS: int = 16

# Maximum number of modeled Layer-2 EtherChannel bundles on one twin. Bundles are
# design annotations over existing links, so this caps review/editor size.
MAX_ETHERCHANNEL_BUNDLES: int = 32

# Maximum member links in one modeled EtherChannel bundle. The analyzer is
# linear in member count; this keeps bundle math and findings bounded.
MAX_ETHERCHANNEL_MEMBERS: int = 8

# Configurable *heuristic* switch count for VLAN sprawl. Exceeding it produces a
# warning only: this is a planning guideline, NOT a protocol or device limit.
DEFAULT_VLAN_SPREAD_SWITCHES: int = 6

# Maximum number of sites described by one modeled WAN design.
MAX_WAN_DESIGN_SITES: int = 64

# Maximum number of inter-site WAN links reviewed by one WAN analysis.
MAX_WAN_LINKS: int = 128

# Maximum number of abstract wireless areas reviewed by one wireless analysis.
MAX_WIRELESS_AREAS: int = 32

# Maximum number of per-link QoS class-share caps stored on one twin.
MAX_QOS_CLASS_CAPS: int = 128

# Maximum member devices in one modeled HA group. Two is the common campus
# case; the cap keeps priority/election and shared-fate checks bounded.
MAX_HA_MEMBERS: int = 8

# Maximum characters accepted in one copilot scenario sentence. This is a UI
# input bound, not a token budget; deterministic parsing always runs first.
MAX_COPILOT_TEXT_CHARS: int = 1_000

# Maximum optional AI explanation characters shown by a copilot "why?" button.
MAX_COPILOT_EXPLANATION_CHARS: int = 1_200

# Maximum deterministic suggestions produced by one copilot suggest call. Every
# suggestion is re-evaluated by an engineering engine before it is ranked.
MAX_COPILOT_SUGGESTIONS: int = 8

# Bounded session stores used by the copilot features. None grows without limit.
MAX_COPILOT_DECISIONS: int = 40
MAX_COPILOT_CACHE_ENTRIES: int = 24
MAX_COPILOT_TRACE_ENTRIES: int = 40
