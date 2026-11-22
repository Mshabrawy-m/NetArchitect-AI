# Current Project Status

## Overall
- Current phase: v1.0.0 released; V2 L2 package on `feature/v2-l2`
- Current task: W1-W5 complete (L2/WAN/Wireless/QoS design package ready for review)
- Overall status: `main` was synchronized and pushed through `3a4aa53 Merge feature/v2-l3 into main`, including hotfix `6f3cd7a hotfix: failure sweep first-run IndexError`. `feature/v2-l2` was created from that `main` and adds deterministic, offline, design-time L2 switching, WAN, abstract wireless, and QoS admission models plus W5 validation, Critic, Copilot, report, and UI integration. All additions are additive optional fields: legacy twin JSON and the schema-v1 fingerprint remain byte-identical and tested. No new runtime dependency, worker, thread, or app disk write was added. The feature branch is not pushed.
- Last updated: 2026-11-22
- Branch: `feature/v2-l2` (created from `main` at `3a4aa53`)

## V2 L2 package (feature/v2-l2)

- Scope: DESIGN MODELS only. L2 switching derives deterministic modeled trunk,
  access VLAN, bundle, and loop-blocking rules; WAN uses explicit site/cost/
  latency assumptions; wireless uses circular-area and per-client Mbps estimates
  with no RF propagation; QoS is a strict-priority admission model with no
  queueing simulation. Nothing contacts a device, runs a protocol, measures a
  circuit, pushes configuration, or simulates packets. `TWIN_SCHEMA_VERSION`
  stays `2`, supported versions remain `(1, 2)`, defaults are omitted from
  canonical JSON, and no new runtime dependency, worker, thread, or app disk
  write was added.
- W1 (`9c25860`, lint fix `312e049`): `network/l2/switching.py` adds bounded
  per-VLAN graph review, deterministic minimum-spanning-forest blocking, trunk
  downstream-VLAN checks, native-VLAN mismatch, VLAN sprawl heuristics, and
  EtherChannel capacity grouping. Additive twin/link/demand fields and local
  VLAN constants keep schema imports acyclic and legacy bytes unchanged.
- W2 (`bb9c1c5`): `network/wan/planning.py` adds inter-site link discovery,
  modeled monthly cost proxies, assumed latency, site-type checks, SRG/SPOF
  findings, and an opt-in capacity-aware evaluation. `optimization/objectives.py`
  adds baseline inter-site and explicit selected-pool proxy terms that contribute
  zero under legacy inputs. Hand checks preserved: infrastructure proxy `220`,
  same-tier upgrade `0.0`, unknown capacity `100.0`, and new WAN case `245.0`.
- W3 (`b34f0ad`): `network/wireless/planning.py` adds capacity/coverage AP
  counts, deterministic binding-constraint labels, uplink requirements, and
  explicit no-RF/modeled-estimate notes. IPv4/IPv6 VLSM, VLAN, and DHCP engines
  are untouched.
- W4 (`465973d`): `network/qos/admission.py` and
  `SimulationAssumptions.enable_strict_priority_qos` add default-off class
  ordering, per-link share caps, and modeled starvation labels. Legacy
  best-effort results are byte-identical. `network/qos/review.py` is a W5 pure
  review layer and is intentionally imported directly to avoid a
  `core.schemas.routing` / `network.qos` circular import.
- W5: `services/validation` adds bounded `l2`, `wan`, `wireless`, and `qos`
  categories and runs each engine only when its additive fields exist; WAN's
  capacity-aware check runs only under `include_expensive=True`. `agents/critic.py`
  re-derives W1-W4 findings independently, maps their codes to `topology` or
  `optimization`, and lets error/critical findings block with a deterministic
  re-plan target. `services/reporting` adds four provenance-tagged sections with
  `not_run` producer page `L2 Design`. `services/copilot` adds four
  `ExplanationTarget` values and deterministic “why?” requests.
  `ui/pages/l2_design.py` provides five tabs, versioned editors, notices,
  theme-backed tokens, and a bounded Run/Cancel/Clear review fragment.
  Navigation grows from 16 to 17 pages. EN/AR catalog parity, first-click
  AppTests, fingerprint caches, and an offline import audit are covered by tests.
- Additive twin fields: `DigitalTwin.l2_design`, `DigitalTwin.wan_design`,
  `DigitalTwin.wireless_design`, `DigitalTwin.qos_design`; additive link fields
  `l2_mode`, `l2_access_vlan`, `l2_native_vlan`, `l2_peer_native_vlan`,
  `l2_allowed_vlans`, `wan_type`, `wan_capacity_mbps`,
  `wan_monthly_cost_proxy`, `wan_latency_ms`, `wan_srg_tag`; additive demand
  field `traffic_class`; additive assumption field
  `SimulationAssumptions.enable_strict_priority_qos`. Bounds:
  `MAX_ETHERCHANNEL_BUNDLES=32`, `MAX_ETHERCHANNEL_MEMBERS=8`,
  `MAX_WAN_DESIGN_SITES=64`, `MAX_WAN_LINKS=128`, `MAX_WIRELESS_AREAS=32`,
  `MAX_QOS_CLASS_CAPS=128`.
- Additive non-twin APIs: validation categories `l2`, `wan`, `wireless`, `qos`;
  `ExplanationTarget.l2_design`, `wan_design`, `wireless_design`, `qos_design`;
  request builders with the same four names; report IDs
  `l2_switching_design`, `wan_design`, `wireless_design`, `qos_design`; and
  `L2DesignReview`. The schema-v1 fingerprint
  `4212909d2624a026229027d4266267906ae6a040df00678bf200d0430c2d802c`
  is unchanged and tested.
- Max-size W-check timing (`pytest -q -m perf -o addopts= tests/unit/test_w5_design_perf.py -s`):
  W1 32 x 8 bundles `0.0022s`, W2 64 sites / 128 links `0.0022s`, W3 32 areas
  `0.0002s`, W4 128 caps `0.0025s`.
- Final verification: `pytest -q` → `1426 passed, 14 deselected in 57.41s`;
  `ruff check .` → `All checks passed!`; `pytest -q -m smoke` → `13 passed,
  1427 deselected in 6.62s`; i18n parity → `True ()`.
- Not verified: real-browser rendering, Streamlit Cloud deployment, Linux CI.

## V2 L3 package (feature/v2-l3)

- Scope: DESIGN MODELS only. Every output is labeled as modeled design rules;
  no packet behavior, protocol exchange, device access, live measurement, or
  generated configuration is involved. `TWIN_SCHEMA_VERSION` stays `2` and
  supported versions remain `(1, 2)`. No new runtime dependency, worker,
  thread, or app disk write was added, and `requirements.txt` stays flat.
- L1 (`16438e2`): `network/addressing/dual_stack.py` adds documented IPv6
  prefix arithmetic, deterministic `/64` VLAN assignments, scope/overlap/
  outside-block/exhaustion findings, prefix-based utilization, and the
  `MAX_V6_PREFIXES=256` bound. IPv6 hosts are never enumerated. Tests cover
  hand-computed `/48` boundaries, index 65535, auto-allocation order, `/64`
  rule violations, scope classification, and legacy JSON.
- L2 (`27c37fa`): `network/addressing/nat.py` adds static, dynamic-pool, and
  PAT-overload sizing with the documented `65535 - 1024 + 1 = 64512` usable
  ports per address, derivation of inside hosts from IPv4 prefixes only,
  overlap/private-space findings, and the `MAX_NAT_RULES=64` bound. Tests use
  hand-computed host counts, pool shortfalls, and PAT capacities.
- L3 (`5ee5c07`): `network/routing/ospf.py` derives router roles (ASBR >
  ABR > internal), area membership, backbone contiguity, virtual-link-needed
  flags, inert summarization suggestions, and cost from `Link.cost` unless
  `reference_bandwidth_mbps` is set. The area size threshold is explicitly a
  heuristic, NOT a protocol limit; `MAX_OSPF_AREAS=32`. Tests cover hand-
  computed roles, costs, SPOF reuse, and the documented disclaimer.
- L4 (`ce32395`): `network/routing/ha.py` adds modeled first-hop redundancy
  groups with priority election (ties by lexicographically lowest device id),
  VIP/subnet/collision/VLAN/shared-fate findings, VLAN-plan checks, and bounds
  `MAX_HA_GROUPS=16`, `MAX_HA_MEMBERS=8`. `SimulationAssumptions.enable_first_hop_failover`
  and `NetworkState.first_hop_failovers` are additive and default off, so the
  legacy state bytes stay unchanged. `preempt` is metadata only.
- L5: all L1-L4 fields are stored additively on the twin with defaults omitted
  from JSON. `services/validation/health.py` adds bounded `dual_stack`, `nat`,
  `ospf`, and `ha` categories; `services/copilot` adds `ospf_design`/
  `ha_group` explanation targets; `agents/critic.py` maps the new finding codes
  and re-derives them deterministically; `services/reporting/builder.py` adds
  four provenance-tagged report sections that show `not_run` with producer page
  `L3 Design` when no plan exists. `ui/pages/l3_design.py` is a five-tab page,
  `app_pages/l3_design.py` is its thin navigation entry, and the IP page reuses
  the dual-stack/NAT tab helpers. Navigation now has 16 pages. EN/AR catalog
  parity, versioned editor keys, queued notices, and a bounded `L3DesignReview`
  cache keyed by canonical twin JSON plus fingerprint are covered by tests.
- Additive twin fields: `DigitalTwin.ipv6_plan`, `DigitalTwin.nat_plan`,
  `DigitalTwin.ospf_design`, `DigitalTwin.ha_groups`,
  `SimulationAssumptions.enable_first_hop_failover`,
  `NetworkState.first_hop_failovers`, and the `FirstHopFailover` model.
  Additive non-twin APIs: validation categories `dual_stack`, `nat`, `ospf`,
  `ha`; `ExplanationTarget.ospf_design`, `ExplanationTarget.ha_group`; report
  section IDs `ipv6_dual_stack`, `nat_plan`, `ospf_area_design`,
  `gateway_redundancy`; and `L3DesignReview`. The schema-v1 fingerprint
  `4212909d2624a026229027d4266267906ae6a040df00678bf200d0430c2d802c` is
  unchanged and tested.
- Focused evidence: reporting 39 passed, UI page 5 passed, cache 1 passed,
  i18n/navigation 45 passed, design health 5 passed, twin fields 3 passed,
  Copilot 14 passed, Critic 1 passed, and the focused cross-module regression
  `416 passed in 34.83s`. Max-size L-check timing from the opt-in perf test:
  L1 256 prefixes `0.0550s`, L2 64 rules `0.0010s`, L3 32 areas `0.0346s`,
  L4 16 x 8 groups `0.0003s`.
- Final verification: `pytest -q` -> `1332 passed, 10 deselected in 52.67s`;
  `ruff check .` -> `All checks passed!`; `pytest -q -m smoke` ->
  `13 passed, 1329 deselected in 6.19s`. Not verified: real-browser rendering,
  Streamlit Cloud deployment, and Linux CI.

## V2 security package (feature/v2-security)

- Scope: deterministic, offline design-time zero-trust/security modeling only.
  No scanning, probing, CVE lookup, exploit/attack description, pentesting, SOC
  analysis, device access, or network I/O. Every output carries the exact
  `SECURITY_DISCLAIMER`. `TWIN_SCHEMA_VERSION` stays `2` and all additions are
  additive optional fields.
- S1: `security/reachability.py` builds a full zone x zone x service modeled
  **policy reachability** matrix, a bounded transitive-closure blast radius
  (`MAX_BLAST_RADIUS_HOPS=8`), and exposure highlights for `untrusted_external`,
  `guest`, and `iot` zones whose closure reaches a designer-set criticality >= 4.
  Results are explicitly labeled policy reachability, not an attack path or
  exploit chain. Routing is probed from bounded zone member devices
  (`MAX_ROUTE_PROBE_DEVICES=8`); VLAN-only cells are marked policy-only.
  `SecurityAnalysis.reachability` is an additive optional field. Tests cover the
  4-zone matrix, transitive closure, deny removes reachability, routing-absent,
  exposure findings, hop limit, and legacy JSON. Max-count timing (32 zones x 32
  services = 32,768 cells): 0.241 s. `pytest -q` 1219 passed, 6 deselected;
  `ruff check .` clean.
- S2: `security/segmentation.py` adds a visible 0--100 score with its full
  formula in the module docstring. Inputs: explicit default-deny (0.25),
  allowed-vs-needed service precision (0.30), lower-to-higher trust *transitive*
  reach from the S1 closure (0.30), and shared broadcast-domain size (0.15).
  Criticality is weighted exactly c/5 (0.2..1.0) only in the trust term; the
  >= 4 exposure highlight stays a separate finding. Every weighted input is
  returned in `SegmentationScore.inputs`. `SecurityAnalysis.segmentation` is an
  additive optional field. Tests cover the documented formula, a hand-computed
  score, monotone deny behavior, criticality, modeled needs, shared VLANs, and
  legacy JSON. `pytest -q` 1228 passed, 6 deselected; `ruff check .` clean.
- S3: `security/optimizer.py` builds bounded, inert deterministic policy
  proposals: adjacent-duplicate merge, shadowed/redundant removal, specific-first
  reordering, any-service tightening, and explicit default deny. Every proposal
  carries a full finite decision-table equivalence proof (zone pairs x
  `{tcp,udp,icmp,any}` x port breakpoints plus default). Behavior-changing
  proposals are flagged and remain selectable. Applying selected proposals
  creates a NEW twin through `set_security_model` and emits one optional C4
  `optimization_candidate_selected` decision through an injected callback (no
  `ui`/`services` import inside `security/`). `SecurityAnalysis.optimizer` is
  additive and optional; `MAX_OPTIMIZATION_PROPOSALS=12`. Tests cover every
  proposal kind, proof correctness, NEW-twin/C4 behavior, legacy JSON, bounds,
  and a bounded Hypothesis cross-check against `evaluate_policy`. `pytest -q`
  1241 passed, 6 deselected; `ruff check .` clean.
- S4: `security/microsegmentation.py` adds inert, demand-scoped zero-trust
  suggestions for zones with designer-set criticality >= 4. New allow rules are
  a strict subset of demand-implied zone-pair/services needs; explicit denies
  cover lower-trust pairs with no modeled need, and default deny is requested
  when the baseline default is allow. Each proposal shows before/after
  segmentation score, reachable inter-zone pair count, and max criticality
  reached (S1/S2 engines). Selection applies to a NEW twin only and optionally
  emits a C4 `security_proposal_accepted` decision. Bounds:
  `MAX_MICROSEGMENTATION_PROPOSALS=4`, `MAX_MICROSEGMENTATION_RULES=48`.
  `SecurityAnalysis.microsegmentation` is additive and optional. `pytest -q`
  1249 passed, 6 deselected; `ruff check .` clean.
- S5: `security/checklist.py` adds a fixed, versioned (`DESIGN_CHECKLIST_VERSION=1.0`)
  eight-item design checklist derived only from modeled facts. Each item has a
  stable ID, fixed text, explicit rule linkage, evidence, and exactly one of
  `pass` / `fail` / `not-modeled`. The logging item is always `not-modeled`
  because the model has no logging field; absence is never a pass or failure.
  Wording is limited to "design checklist aligned with common practice
  (design-level)" with no compliance claim. `SecurityAnalysis.checklist` is an
  additive optional field. Tests cover every item's three possible statuses,
  version stability, counts, disclosure, and legacy JSON. `pytest -q` 1260
  passed, 6 deselected; `ruff check .` clean.
- S6: `ui/pages/security_analysis.py` integrates the package as ten tabs: Zones,
  Policy, Flow check, Reachability, Segmentation, Optimizer, Zero-trust,
  Findings, Checklist, and Templates. Labels use new EN/AR `ui/i18n.py` keys
  with full parity; status chips use `ui/theme.py` tokens; editor keys are
  versioned; `cached_security_analysis` takes an optional twin fingerprint key
  while preserving existing three-argument callers. Reachability and
  Segmentation add deterministic C3 "why?" requests; Optimizer and Zero-trust
  apply only selected proposals to a NEW twin and emit one C4 decision each.
  The Checklist tab shows version `1.0`, item statuses, and basic design health.
  `agents/critic.py` maps `REACH-` codes to the `security` step and feeds S1
  exposure findings into the existing deterministic gate, which can reject and
  selectively re-plan to security. The report's new security values carry
  step/tool provenance and pass numeric consistency checks. Every new module is
  covered by the forbidden network/process import and token audit. No schema
  version bump: `TWIN_SCHEMA_VERSION` stays `2`. Focused tests: 60 passed.
  `pytest -q` 1270 passed, 6 deselected in 47.72s; `ruff check .` clean;
  `pytest -q -m smoke` 13 passed, 1263 deselected in 6.44s. Live Streamlit agent
  API: health `ok`, security page rendered all 10 tabs with no exceptions and no
  server warnings; the server was stopped afterward. Not verified: real-browser
  rendering, Cloud deployment, Linux CI.

## V2 package (feature/v2-tech)

- Scope: free-tier-safe speed, install-size, and verification work only. No
  features, UI changes, schema changes, or new runtime dependencies.
- T0: `docs/V2_SPEC.md` created as the shared roadmap and free-tier reference.
- T1: runtime/dev dependency split complete. `requirements.txt` has nine flat
  inline pins; `requirements-dev.txt` adds pytest, ruff, and Hypothesis. Clean
  venv runtime-only install proved headless health `ok`, root 200, and all 15
  pages via `scripts/verify_runtime_only.py` with pytest absent. Local Windows
  install: 254.6 s / 568.6 MiB before vs 262.1 s / 556.3 MiB after
  (`--no-cache-dir`; network time varied). `pytest -q` 975 passed;
  `pytest -q -m smoke` 12 passed, 963 deselected; `ruff check .` clean.
- T2: CI rewritten for `ubuntu-latest` with Python 3.11/3.12, pip cache, dev
  install/ruff/pytest/smoke, a runtime-only 15-page job, a Linux VmRSS gate at
  450 MB (`scripts/check_linux_memory.py`), and a throwaway-venv pip-audit job.
  Weekly `dependabot.yml` added. Remote Actions execution was not performed;
  owner checks are listed in `docs/DEPLOYMENT.md`.
- T3: sparse CSR routing/evaluation hot paths complete. All-pairs 0.970 s to
  0.066 s (14.7x) and evaluate 0.762 s to 0.045 s (16.9x) in the reproducible
  profile; 5 s GA throughput 1.0 to 10.1 evaluations/sec. The >=3x target was
  met; GA/NSGA-II wall clock is still limited by the configured 60 s budget.
  Frozen NetworkX reference equivalence tests cover ties, parallel/directed
  links, failures, disconnection, star/ring/campus/spine-leaf/max-size. Seeded
  GA/NSGA-II objective vectors are byte-identical to commit `3e31a41`. Opt-in
  `perf` budgets use a 2x margin and are excluded from default/smoke runs.
  `pytest -q` 988 passed/3 deselected; `pytest -q -m smoke` 12 passed/
  979 deselected; `pytest -q -m perf` 3 passed/988 deselected; `ruff check .`
  clean. See `docs/PERFORMANCE.md`.
- T4: lazy imports complete. `app.py` imports page modules only when selected; `services.export` defers all implementation modules, and `ui/cache.py` imports reporting/export helpers inside cached functions. Cold `import app` now has zero cumulative importtime for reportlab, reporting, export, and four rare pages. App import `2327519` to `1564059` us and Dashboard first render `1.994` to `1.363` s in fresh one-run measurements against `bf2b5b8`. All six `st.cache_data` uses remain bounded at 8 entries. `pytest -q` 992 passed/3 deselected; `pytest -q -m smoke` 12 passed/983 deselected; `ruff check .` clean. See `docs/PERFORMANCE.md`.
- T5: bounded Hypothesis suite complete. Eight property tests cover IPv4/IPv6 VLSM allocation, deterministic route walks with device/link failures, twin JSON/fingerprint/legacy-v1 compatibility, CSV formula neutralization, and optimizer infeasibility. Shared settings use `max_examples=50`, `derandomize=True`, and `deadline=None`; a local 1000-example probe also passed. No product bug was found by the properties (one incorrect IPv6 prefix assertion in the new test was corrected before commit). `pytest -q` 1000 passed/3 deselected; `pytest -q -m smoke` 12 passed/991 deselected; `pytest -q -m perf` 3 passed/1000 deselected; `ruff check .` clean.

## V2 design package (feature/v2-design)

- Scope: UI design system, guided workflow, topology UX, ar/en i18n, and
  accessibility polish. No engine, schema, export, or runtime dependency changes.
- D1: `ui/theme.py` is the only UI module with raw color literals. Light and
  dark palettes are mirrored in `.streamlit/config.toml` with one typeface.
  Native `st.navigation`/`st.Page` replaces the sidebar selectbox; Dashboard is
  first, followed by Design, Analyze, Operate, and Output groups. The 15
  existing render functions are reached through thin files in `app_pages/`.
  Shared metric, status, section, callout, empty-state, and key/value helpers
  are available from `ui.components`.
- D1 evidence: `pytest -q` 1006 passed/3 deselected; `pytest -q -m smoke` 12
  passed/997 deselected; `ruff check .` clean. Changed assertion: the old
  navigation test asserted that Security followed Capacity in the flat
  selectbox order; it now asserts the specified group contents and Dashboard
  first/Settings last. Navigation tests switch pages through registered
  `st.Page` files instead of `page_nav`.
- D2: `ui/progress.py` renders Design -> Addressing -> Validate -> Simulate ->
  Optimize -> Report above every page. Each step links to its engineering page
  and reports Done, Incomplete, or Stale from read-only `state.peek_*` accessors.
  Stale means a retained result's twin fingerprint differs from the current
  twin. Bounded source-fingerprint maps for subnet checks and optimization runs
  keep the evidence in session state without creating empty histories. The
  Dashboard quick start offers three clearly labeled `SAMPLE - ...` projects
  built through the existing generators, VLSM/VLAN/DHCP engines, and twin model.
  Selection only records a pending key; the twin is replaced only by an explicit
  confirm action, and cancel leaves the current twin untouched.
- D2 evidence: focused UI tests 50 passed; `pytest -q` 1020 passed/3 deselected;
  `pytest -q -m smoke` 12 passed/1011 deselected; `ruff check .` clean; fresh
  runtime-only venv health `ok`, root 200, 15 pages rendered, pytest absent.
  No existing assertion was changed in D2; the new tests cover progress states,
  ordered page links, sample validity/determinism, and no-overwrite confirmation.
  The optimizer fixture in the progress tests uses the matching a-b-c-d pool
  twin because the default pool links are not endpoints of the campus fixture;
  source fingerprint assertions remain explicit in the crafted session data.
- D3: `ui/topology_view.py` replaces the spring-layout figure with bounded
  left-to-right tiers ordered by role (WAN/border, DMZ/core, distribution/
  aggregation, access/edge, endpoints). Device type is encoded by marker shape,
  and color can be switched between role, stable site-derived zone, and latest
  baseline-simulation utilization. A fixed legend covers every type and color
  mode; labels thin out above 30 devices while hover details stay available.
  Clicking a device or link midpoint populates an inspector with properties and
  quick actions that queue node/link failure scenarios. The picker is also a
  keyboard-accessible selection path. Plotly selection uses two alternating
  widget keys so clearing/reselecting stays bounded and never assigns a widget
  key directly.
- D3 evidence: focused tests 11 passed; `pytest -q` 1030 passed/3 deselected;
  `pytest -q -m smoke` 12 passed/1021 deselected; `ruff check .` clean; fresh
  runtime-only venv health `ok`, root 200, 15 pages rendered, pytest absent.
  Live Streamlit agent API switched to the Topology page, generated a star
  topology, showed Color by / Inspect entity / Clear selection controls, and
  reported no exceptions or server warnings. No engine, schema, or editor table
  behavior was changed.
- D4: `ui/i18n.py` is the single ar/en UI catalog. Language is a session-only
  key (`ui_language`) with a segmented control on Settings; no file, secret,
  export, or PDF behavior was changed. Navigation labels/help, progress strip,
  shared components, Dashboard, Settings, and the layered topology view use
  catalog keys. Engineering terms (VLAN, CIDR, OSPF), identifiers, numbers, IPs,
  and CIDRs are isolated with Unicode direction marks so they stay LTR in
  Arabic. A scoped stylesheet sets RTL direction only when Arabic is active;
  widget internals are not restyled. Missing keys and malformed placeholder
  substitutions fall back to English.
- D4 evidence: `i18n.catalog_parity()` `True`, `missing_translation_keys()`
  `()`; focused UI tests 81 passed; `pytest -q` 1038 passed/3 deselected;
  `pytest -q -m smoke` 12 passed/1029 deselected; `ruff check .` clean; fresh
  runtime-only venv health `ok`, root 200, 15 pages rendered, pytest absent.
  AppTest set Arabic before first render and confirmed the RTL stylesheet,
  localized Dashboard/navigation/progress text, LTR-isolated VLAN, and Settings
  toggle back to English. One existing release test was updated: the About-menu
  source scan now reads `i18n.EN["app.about"]` because the wording moved from
  `app.py` into the catalog. English defaults preserve existing test wording.
- D5: `ui/formatting.py` centralizes grouped numbers, percentages, ratios,
  Mbps/ms units, signed deltas, and bounded missing-value handling. English and
  Arabic tokens are explicit; Arabic numeric/unit tokens receive the same LTR
  isolation as other engineering terms. `ui/components/feedback.py` adds one
  shared spinner for the bounded synchronous provider, workflow, connection,
  CSV, forecast, capacity, and scenario actions. Domain errors use the shared
  `format_error` helper. The simulation congestion chart adds visible level
  labels and hover text so its colors are not the only meaning. Static tests
  enforce visible widget labels, full-width tables, one RTL stylesheet, text
  contrast >= 4.5:1, and no raw `st.error(str(error))`.
- D5 evidence: focused UI tests 153 passed; `pytest -q` 1048 passed/3 deselected;
  `pytest -q -m smoke` 12 passed/1039 deselected; `ruff check .` clean; fresh
  runtime-only venv health `ok`, root 200, 15 pages rendered, pytest absent.
  Final clean profile imports: app total `1459589` us; Dashboard first render
  `1.340` s.
  No engine, schema, export, PDF, state, or runtime dependency changed.
- Final package: `docs/V2_FINAL_REPORT.md` records the D1-D5 file/change table,
  verbatim final command output, before/after Dashboard timing, six real-browser
  screens in `docs/screenshots/`, and the remaining unverified items. The live
  Streamlit server and CDP browser used for the screens were stopped afterward.

## V2 engine package (feature/v2-engine)

- Scope: E1-E5 additive engine, UI, and report wiring. No schema-version bump;
  `TWIN_SCHEMA_VERSION` stays `2`. All new fields are optional and default to
  legacy behavior. Free-tier rules are unchanged: flat `requirements.txt`, no
  new runtime dependency, no workers/threads, no app disk writes, and bounded
  session/cache/sweep state.
- E1: `single_path` remains the default. Bounded `ecmp` splits equally across
  all deterministic lowest-cost paths up to `MAX_ECMP_PATHS` with an explicit
  truncation warning; directed links carry only forward load, undirected links
  sum both directions, and unserved reasons are unchanged. Legacy twin/run JSON
  and fingerprint fixtures stay byte-identical.
- E2: `capacity_aware` is a deterministic largest-first admission-control model
  (ties by demand id) on the lowest-cost path with residual capacity. It emits
  `unserved: insufficient capacity` with the best blocked path and supports a
  side-by-side mode comparison.
- E3: N-1 and caller-subset N-2 sweeps are bounded by `MAX_NODES`/`MAX_EDGES`
  and `MAX_N2_PAIRS`. Additive shared-risk groups expand targets, not case count.
  The page uses slice-based `st.fragment`, Cancel, real progress, typed stop
  reason, and "showing X of Y" without threads. Medium N-1 went from
  `0.355934 s` (direct repeated runs) to `0.140281 s` (sweep); max N-1 went from
  `1.339096 s` to `0.648555 s`.
- E4: seeded bounded simulated annealing supports an optional hybrid start from
  retained greedy/baseline candidates. Bounded demand/capacity sensitivity uses
  the documented robust definition; weight changes re-rank stored Pareto
  evaluations only. GA/NSGA-II seeded vectors and the pre-E4 optimization
  JSON/hash fixture remain byte-identical.
- E5: Simulation Lab exposes routing mode, shared-risk groups, mode comparison,
  and sweeps. Optimization Center exposes SA, hybrid start, sensitivity, and
  re-ranking. Reports select all four new result types with provenance, stale
  warnings, and not-run states. EN/AR catalog parity remains green.
- Schema additions reported to the user: `RoutingMode`, `PathSplit`,
  `SimulationAssumptions.routing_mode`, `DemandEvaluation.splits`, blocked-path
  fields on demand evaluations and unserved demands, `SharedRiskGroup`,
  `DigitalTwin.shared_risk_groups`, sweep case/plan/impact/result models,
  `Algorithm.simulated_annealing`, `RerankedCandidate`, `ParetoReranking`,
  `SensitivityScenario`, `SensitivityCase`, `SensitivityScenarioResult`, and
  `SensitivityReport`.
- Final evidence: `pytest -q` -> `1130 passed, 5 deselected in 40.59s`;
  `ruff check .` -> `All checks passed!`; `pytest -q -m smoke` ->
  `13 passed, 1122 deselected in 5.87s`; `pytest -q -m perf` ->
  `5 passed, 1130 deselected in 10.85s`. Focused E5 evidence: i18n 9 passed,
  state 7 passed, reporting/cache 43 passed, UI pages 26 passed. Not verified in
  this package: real-browser rendering, Cloud timing/RSS, and Linux CI.

## V2 copilot package (feature/v2-copilot)

- Scope: C1-C5 add optional copilot interpretation, deterministic explanations,
  a session decision log, and cache/budget visibility. No standalone chatbot,
  no sparkle icons, no "Ask AI" on unrelated pages. Free-tier rules are intact:
  stdlib HTTP only for optional provider calls, no new runtime dependency, no
  threads, no app disk writes, flat `requirements.txt`, and bounded session,
  cache, trace, and decision state. The LLM interprets or explains only; every
  scenario, verdict, decision, execution, and mutation stays in deterministic
  engines.
- C1 (`39dae53`): deterministic-first EN/AR sentence parser, typed
  `ScenarioInterpretation`, injected allowlist/number audits, editable preview,
  and no scenario run before confirmation. LLM calls: 0 for supported phrases,
  at most 1 audited draft (plus bounded repair retries) otherwise.
- C2 (`b25eb6a`): deterministic `suggest` from SPOF, overloaded links, security
  design issues, and worst failure-sweep cases; typed proposals; exact
  before/after metrics; engine re-evaluation; apply to a NEW snapshot only after
  confirmation. No-key path works fully. LLM calls: 0.
- C3 (`efa86f8`): "why?" buttons for routes, findings, simulation results, and
  optimization picks. Deterministic text is always shown; optional AI prose is
  labeled, audited for invented numbers/out-of-scope content/verdict language,
  and never sets a level or verdict. LLM calls: 0 without a key, at most 1 per
  requested explanation.
- C4 (`93a99bf`): frozen `DecisionRecord`/`DecisionLog` with injected UTC
  timestamps and `MAX_COPILOT_DECISIONS=40` bound. Explicitly recorded after
  accepted suggestions, applied samples/snapshots, accepted security proposals,
  and selected optimization candidates. Viewed/exported in Digital Twin and
  rendered as a provenance-tagged `design_decisions` report section. LLM calls: 0.
- C5 (`da5d192`): Settings shows remaining requests/tokens, cache hits/misses/
  entries, prompt trace rows, and a cache reset. Cache keys hash model, prompt
  id/version, schema name, and typed input; hits skip provider and budget.
  Prompts remain in `services/llm/prompts.py`; native JSON with extract-and-
  repair fallback and Pydantic validation is used both ways. `tests/eval` holds
  24 EN/AR golden cases with `FakeProvider`; `scripts/record_llm_responses.py`
  is a manual local-only, CI-refusing, key-redacting recorder writing to an
  ignored directory. LLM calls in tests: 0 real calls.
- Schema additions are additive only: `DecisionKind`, `DecisionRecord`,
  `DecisionLog`, `design_decisions` report section, and optional copilot result
  metadata already introduced in C1/C3. No persisted twin field changed;
  `TWIN_SCHEMA_VERSION` remains `2` and legacy JSON/fingerprints are unchanged.
- Final evidence: `pytest -q` -> `1213 passed, 5 deselected in 43.92s`;
  `ruff check .` -> `All checks passed!`; `pytest -q -m smoke` ->
  `13 passed, 1205 deselected in 5.80s`. Focused C3 `46 passed in 10.00s`,
  C4 `84 passed in 13.32s`, C5 golden `25 passed in 0.87s`.
  Not verified: live Groq responses, real-browser rendering, and deployed
  Community Cloud.

## Completed
- [x] Phase 1: Project Foundation and Environment
- [x] Phase 2: Requirements and Domain Modeling
- [x] Phase 3: Network Topology Engine
- [x] Phase 4: IP Addressing and VLAN Engine
- [x] Phase 5: Routing and Graph Analysis Engine
- [x] Phase 6: Network Digital Twin
- [x] Phase 7: Network Simulation Engine
- [x] Phase 8: Multi-Objective Optimization Engine
- [x] Phase 9: Agentic AI Framework
- [x] Phase 10: Specialized AI Agents
- [x] Phase 11: Reports and Explainability
- [x] Phase 12: Frontend Integration and User Experience
- [x] Phase 13: Predictive Capacity Planning (13a/13b/13c complete)
- [x] Phase 14: Design-time Network Security Analysis (14.0/14a/14b/14c/14d complete)
- [x] Phase 15: Testing, Security review, and Deployment (15a/15b/15c/15d prepared locally; Cloud deployment pending owner action)

## Task 0 evidence (verification and version control)
- `python --version`: `Python 3.11.15` (system interpreter and `.venv`).
- Phase 1-2 baseline re-verified before changes:
  - `python -m pytest -q`: `114 passed in 1.33s`
  - `python -m ruff check .`: `All checks passed!`
- Secrets scan over the working tree (excluding `.venv`, caches, `.agents`):
  no API keys, tokens, or passwords found. `.streamlit/secrets.toml.example`
  contains placeholders only. Real `.streamlit/secrets.toml` is absent.
- `.gitignore` verified to exclude `.venv/`, `.streamlit/secrets.toml`,
  `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `.agents/`, and logs.
- `git init` performed; `main` created; commit
  `d24c75c Phase 1-2: foundation and domain schemas` contains the verified
  Phase 1-2 baseline (no secrets, no virtualenv, no agent scratch files).
- Working branch created: `feature/phase3-topology`.

## Phase 3a delivered - topology engine core
Location: `network/topology/` (pure Python, no Streamlit, no LLM, no I/O).

- `graph.py`
  - `to_networkx` always returns `networkx.MultiDiGraph`; directed links are
    one arc, undirected links are two reciprocal arcs tagged `directed=False`.
  - Graph metadata stores the topology name and overall directedness
    (`undirected`, `directed`, `mixed`).
  - `from_networkx` reconstructs the exact topology, including endpoint order,
    and accepts plain `Graph`/`DiGraph` inputs with typed `SchemaError` on bad
    node/link attributes.
- `operations.py`
  - `add_device`, `remove_device`, `update_device`, `add_link`, `remove_link`,
    `update_link`, `enforce_limits`.
  - Pure functions: input topology is never mutated; every result is
    re-validated.
  - Raises `DuplicateIdError`, `MissingEndpointError`, `DeviceNotFoundError`,
    `LinkNotFoundError`, `LimitsExceededError` with specific messages.
  - Device removal cascades attached links; `MAX_NODES`/`MAX_EDGES` are
    enforced on adds and via `enforce_limits`.
- `connectivity.py`
  - Frozen `ConnectivityReport` / `ConnectedComponent` Pydantic models.
  - Physical connectivity: directed links count both ways; empty topology is
    not connected; isolated devices are listed.
- `serialization.py`
  - `to_json` / `from_json`; exact round-trip (`from_json(to_json(t)) == t`
    and byte-stable re-export); limits enforced on both paths.
- `generators.py`
  - Deterministic `generate_star`, `generate_ring`, `generate_mesh`,
    `generate_tree`; counts validated against limits before construction.

## Phase 3b delivered - remaining generators and Topology Editor
### Generators (`network/topology/generators.py`)
- `generate_hierarchical_campus(distribution_count, access_per_distribution,
  redundant_uplinks)`:
  - Devices `(2 if redundant else 1) + D + D*A`.
  - Links `(2 if redundant else 1) * D + (2 if redundant else 1) * D*A`.
  - Single-homed: every distribution switch uplinks to the single core router.
  - Redundant: two core routers; every distribution switch dual-homes to both
    and every access switch dual-homes to two adjacent distribution switches
    (ring order). Requires `distribution_count >= 2`.
- `generate_spine_leaf(spines, leaves, full_mesh)`:
  - Devices `spines + leaves`.
  - Links `spines * leaves` when `full_mesh=True`; otherwise
    `leaves * min(spines, 2)` (each leaf dual-homes to a rotating adjacent
    spine pair, keeping the fabric connected).
- `generate_hybrid(core_nodes, access_per_core)`:
  - Composition: `generate_ring` core plus one `generate_star` cluster per ring
    node; star hubs are re-roled to `distribution`; joined by one uplink per
    ring node.
  - Devices `core_nodes * (2 + access_per_core)`.
  - Links `core_nodes * (access_per_core + 2)`.
- All three reject invalid parameters with `ValueError` and oversized requests
  with `LimitsExceededError` before building anything.

### Topology Editor (`ui/pages/topology_editor.py`, `app.py`)
- New page wired into a sidebar `st.selectbox` (`page_nav`); Dashboard and
  Topology Editor are functional, all other planned pages keep their
  placeholder state.
- Generator selection and parameters for all seven families, with generate,
  connectivity summary (devices, links, components, isolated devices), Plotly
  diagram, device/link `st.data_editor` tables, and JSON download/upload.
- UI delegates all engineering to `network.topology`; it contains no graph or
  validation logic of its own.
- One session-state key holds the model: `st.session_state["topology"]`. One
  extra key (`topology_editor_flash`) holds short-lived success messages.
- Ids are immutable; renamed id columns and invalid rows are rejected with an
  inline `st.error` and never written to state. Limit errors from the engine
  surface as readable messages.
- Deterministic diagram layout (`nx.spring_layout(seed=42)`), role-colored
  nodes, and a legend for node roles and link direction.
- App icon changed to `:material/hub:`; no emojis or decorative elements.

### Tests
- 16 new generator tests: count formulas, connectivity, degrees for
  dual-homing, invalid parameters, node/edge limit rejection, no duplicate
  ids, JSON round-trip, determinism.
- `tests/unit/ui/test_topology_editor.py`: AppTest smoke test that loads the
  app, navigates to the editor, generates a star, and asserts the resulting
  topology and chart.

## Phase 4a delivered - addressing engine
Location: `network/addressing/` (pure Python, stdlib `ipaddress` only, no
Streamlit, no LLM, no new dependencies). Engines are stateless functions that
return new typed Pydantic results.

- `cidr.py`
  - `calculate_subnet` returns `SubnetInfo` with normalized network, version,
    prefix length, IPv4 netmask and wildcard mask, network/broadcast/last
    addresses, first/last usable host, usable count, total count, and a
    `special_case` marker.
  - Documented special prefixes: IPv4 `/31` (RFC 3021, two usable, no
    broadcast) and `/32` (one usable); IPv6 `/127` (RFC 6164, two usable) and
    `/128` (one usable). Ordinary IPv6 prefixes exclude the subnet-router
    anycast address, so usable = total - 1.
  - Host bits in input strings are normalized (`10.0.0.5/24` -> `10.0.0.0/24`).
- `vlsm.py`
  - `allocate_vlsm(parent, requirements, reserved_addresses=None)` sorts
    largest-first with stable input-order ties, picks the smallest permitted
    prefix that fits `required_hosts + reserved`, and carves blocks
    sequentially so allocations never overlap and always lie inside the parent.
  - Reserved-address defaults: 3 for IPv4 (network, broadcast, gateway) and
    2 for IPv6 (anycast, gateway); minimums are 2 and 1. Allocation is capped
    at `/30` (IPv4) and `/126` (IPv6); point-to-point prefixes are available
    from the CIDR calculator but are not produced by VLSM.
  - Insufficient space raises `InsufficientAddressSpaceError` listing every
    requirement that could not be placed; no partial result and no silent
    truncation. Duplicate names, invalid reserved counts, and limits are
    rejected before allocation.
- `validation.py`
  - `detect_overlaps` returns one `Finding` per overlapping subnet pair;
    touching blocks and mixed IP versions produce no finding.
  - `detect_duplicate_ips` returns one finding per address assigned to more
    than one entity. `validate_addressing` aggregates both into the existing
    `ValidationReport` contract.
- `utilization.py`
  - Per-subnet used/usable/remaining addresses and percent utilization, plus
    parent totals when a parent is supplied. Usage above capacity, mismatched
    versions, and subnets outside the parent are rejected.
  - All counts are prefix arithmetic; large IPv6 blocks are never enumerated.
- `tables.py` returns plain row dictionaries for UI-independent presentation.
- `config/limits.py` adds `MAX_SUBNETS = 256` and
  `MAX_HOSTS_PER_SUBNET = 1_000_000`; `core.exceptions` adds
  `InsufficientAddressSpaceError`.

## Phase 4b delivered - VLAN and DHCP
Location: `network/vlan/` (plain dict rows, UI-agnostic).

- `plan.py`
  - `plan_vlans` maps one department to one VLAN id and one subnet. IDs are
    validated against 1-4094; reserved IDs `{1, 1002, 1003, 1004, 1005}` are
    never auto-assigned, and `0`/`4095` are rejected as out of schema range.
  - Auto-assignment starts at 10 and skips reserved and already-used IDs.
    Explicit IDs are validated and checked for duplicates against both explicit
    and automatic assignments. Duplicate departments/subnet names and
    overlapping subnets are rejected with typed exceptions.
- `dhcp.py`
  - `plan_dhcp_scope` reserves the network/anycast address, gateway (default
    first usable), and IPv4 broadcast, validates caller exclusions, and derives
    the first contiguous free pool when boundaries are omitted.
  - Explicit pools must lie inside the usable range and must not include a
    gateway, reserved address, or exclusion. `validate_dhcp_scope` reports
    pool, gateway, exclusion, version, and boundary violations as `Finding`
    objects. `/32` and `/128` subnets have no DHCP pool.
- `tables.py` provides `vlan_rows`; `dhcp_scope_rows` provides one row per
  scope with pool size and exclusions.

## Phase 4c delivered - planning pages
- `ui/pages/ip_addressing.py`: CIDR calculator (IPv4/IPv6, special-prefix
  caption), VLSM planner with editable requirement table, allocation table,
  utilization progress bars, subnet-overlap checker, and CSV downloads.
- `ui/pages/vlan_dhcp.py`: editable department requirements (prefilled from
  `st.session_state["organization"]` when present), VLAN mapping table, DHCP
  scope table, validation findings, and CSV downloads.
- `ui/components.py`: shared validation-error formatting, CSV serialization,
  and findings table rendering.
- `app.py` routes `IP Addressing & Subnetting` and `VLAN & DHCP Planner`;
  sidebar and dashboard text updated. The remaining planned pages are still
  placeholders.
- Session state holds only derived results: `ip_cidr_result`,
  `addressing_result`, `addressing_check_report`, and `vlan_plan_result`.
  Topology and organization state are read, never duplicated.

## Phase 5a delivered - routing engine
Location: `network/routing/` (pure Python plus NetworkX, no Streamlit, no LLM,
no new dependencies). Every function is stateless: it takes a `Topology` and
optional failed device/link ids and returns new typed Pydantic results. The
input topology is never modified.

- Link semantics (documented in `graph.py`):
  - `Link.directed=True` adds one directed arc from `endpoints[0]` to
    `endpoints[1]`; an undirected link adds reciprocal arcs.
  - `Link.cost` is the edge weight; `capacity_mbps` is metadata only and never
    participates in path selection.
  - Parallel links between the same ordered pair collapse to the lowest
    `(cost, link_id)` tuple, so the chosen physical link is deterministic.
- `paths.py`
  - `shortest_path` returns a typed `RoutePath` (`device_ids`, `hops`,
    `total_cost`, `hop_count`, `reachable`, `reason`). Unreachable pairs return
    `reachable=False` instead of raising; unknown devices raise
    `DeviceNotFoundError`, unknown failure ids raise `LinkNotFoundError` /
    `DeviceNotFoundError`.
  - Equal-cost paths break ties by the lexicographically smallest device-id
    sequence. Source = destination is reachable with an empty path, cost 0,
    and 0 hops.
  - `alternative_paths` enumerates simple paths (Yen) over distinct device
    sequences, ordered by total cost then device sequence, bounded by
    `MAX_ALTERNATIVE_PATHS`.
  - `routing_table` returns one deterministic next-hop entry per reachable
    destination, excluding the source.
  - `reachability_matrix` returns a directed boolean matrix with per-ordered-
    pair counts; `component_summary` reports weak/strong components and
    isolated devices.
- `tables.py` exposes UI-agnostic `path_rows`, `alternative_rows`,
  `routing_table_rows`, and `reachability_rows`.
- `config/limits.py` adds `MAX_ALTERNATIVE_PATHS = 10`; `MAX_NODES` bounds the
  graph size and the documented complexity (Dijkstra per source).

## Phase 5b delivered - structural analysis engine
Location: `network/analysis/` (pure Python plus NetworkX, no Streamlit, no LLM,
no new dependencies). All metrics are design-time structural indicators, not
measurements of traffic, latency, utilization, or availability.

- Analysis basis (documented in `graph.py`): a simple undirected projection
  where a link contributes one edge regardless of `directed`, and parallel
  links collapse into one edge that keeps all link ids and the lowest cost.
- `metrics.py`
  - Degree centrality (parallel links count once) and betweenness centrality
    (weighted by `Link.cost`).
  - Connected components and isolated devices; hop-based diameter reported per
    component with `overall_diameter=None` when disconnected.
  - Articulation points and bridges, each with the component count and any
    newly isolated devices after removal. A pair joined by parallel links is
    never reported as a single-link failure.
  - `METRIC_DEFINITIONS` exports the exact wording used by the UI.
- `spof.py`: `SpofReport` combining critical devices and critical links with
  the baseline component count.
- `findings.py`: `Finding` results with stable codes `spof_device` and
  `spof_link` (critical), plus `topology_disconnected` and `isolated_device`
  warnings.
- `redundancy.py`: node-disjoint paths on the direction-aware routing graph;
  edge-disjoint paths via a unit-capacity physical-link gadget so parallel
  links count separately and an undirected link carries at most one path.
- `report.py`: `analyze_topology` computes the full `AnalysisReport` in one
  pass; `tables.py` provides UI-agnostic rows.

## Phase 5c delivered - routing and analytics pages
- `ui/pages/routing_analysis.py`:
  - Source/destination selectors, k-alternative slider, failure selector for
    devices and links, shortest path with cost and hop count, ranked
    alternatives, routing table, and a directed reachability matrix.
  - With failures active, the page shows before/after reachability and a
    next-hop/cost comparison with `unchanged` / `rerouted` / `new` /
    `unreachable` status.
  - Plotly topology view highlights the current path, keeps the baseline path
    dashed when it changes, and marks failed entities in red.
  - Every table has a CSV download; the page derives results on each rerun and
    stores no engine output in session state beyond widget keys.
- `ui/pages/network_analytics.py`:
  - Summary metrics, degree and weighted-betweenness bar charts with tables,
    connected components, per-component diameters, critical devices/links,
    SPOF summary and findings, and per-pair path redundancy.
  - An expandable "Metric definitions" section renders `METRIC_DEFINITIONS`
    verbatim and states that values are structural, not measured.
  - CSV downloads for every table.
- `app.py` wires `Routing Analysis` and `Network Analytics` into navigation and
  updates the sidebar/dashboard availability text; no other placeholder page
  is changed.

## Phase 6a delivered - digital twin model
Location: `digital_twin/` (pure Python; no Streamlit, no LLM, no new
dependencies). The twin is a *software model* of a network design, not a live
copy of real equipment.

- `models.py`
  - Frozen `DigitalTwin` holding metadata (`name`, caller-supplied
    `created_at`, `schema_version`), `Topology`, optional `AddressingPlan`,
    optional VlanPlanResult, DHCP scopes, traffic demands, per-device and
    per-link operational state, and scenario assumptions.
  - Units documented on every field: link capacity and demand bandwidth in
    Mbps, cost is a unitless routing metric, DHCP lease in minutes.
  - Canonical state is `up`/`down`; a missing entry means `up`.
- `validation.py`
  - `validate_twin` returns the existing `ValidationReport`/`Finding` contract.
  - Reuses `validate_addressing`, `validate_dhcp_scope`, and
    `analyze_connectivity`; adds only cross-part checks (stale/duplicate state,
    demand endpoints and names, VLAN subnet presence, DHCP scope networks,
    schema version, demand limit).
  - Stale references are reported, never pruned, so a topology change cannot
    silently leave dependent plans inconsistent.
- `operations.py`
  - Immutable-style `set_topology`, `set_device_state`, `set_link_state`,
    `set_operational_states`, `apply_failure`, `restore_entities`,
    `set_link_capacity`, `set_link_cost`, `add_demand`, `remove_demand`,
    `set_demands`, plan setters, and assumption setters.
  - Every operation returns a new twin; the input is never mutated.
- `snapshots.py`
  - Frozen `Snapshot` containing a deep copy of the twin.
  - `SnapshotStore` enforces `MAX_SNAPSHOTS` and
    `MAX_TWIN_SNAPSHOT_BYTES`; `diff_twins` reports devices, links, state,
    capacity, cost, demands, and plan/assumption changes.
- `serialization.py`: `to_json`/`from_json` with exact round-trip and a
  `TwinSchemaVersionError` for missing/unknown/newer schema versions.
- `adapters.py`: `failed_entities`, `routing_arguments`, and
  `analysis_arguments` feed the existing engines without rewriting them; stale
  state is kept out of engine arguments.
- `config/limits.py`: `MAX_SNAPSHOTS = 20`, `MAX_DEMANDS = 100`,
  `MAX_TWIN_SNAPSHOT_BYTES = 2_000_000`.
- `core/exceptions/__init__.py`: `TwinSchemaVersionError(SchemaError)`.

## Phase 6b delivered - single session accessor and page migration
- `ui/state.py` is the only module that reads or writes the baseline twin. It
  owns `TWIN_KEY = "digital_twin"`, `SNAPSHOTS_KEY`, derived-result keys, and
  session helpers.
- A legacy bare `Topology` under `st.session_state["topology"]` is migrated
  once into a twin and the legacy key is deleted, so the model never exists
  twice.
- Migrated pages:
  - `topology_editor.py` writes through `replace_topology` and shows a
    "Digital twin consistency" panel with dependent-plan findings after a
    topology change.
  - `ip_addressing.py` keeps CIDR/VLSM/check results in the accessor and writes
    VLSM allocations into the twin's standalone subnets; a conflicting plan is
    reported and left unchanged.
  - `vlan_dhcp.py` stores the VLAN plan, DHCP scopes, and a matching
    `AddressingPlan` in the twin.
  - `routing_analysis.py` reads the twin, applies twin failures to the
    baseline, unions them with the scenario selection, and warns about stale
    state.
  - `network_analytics.py` analyzes the twin with twin failures excluded and
    warns about stale state.
- AppTest assertions moved from raw `"topology"` / `"vlan_plan_result"` keys to
  `ui.state.TWIN_KEY`; existing widget keys are unchanged.

## Phase 6c delivered - Digital Twin page
- `ui/pages/digital_twin.py` shows the twin summary, a devices/links state
  table with an explicit Apply action, validation findings, snapshot
  creation/list/download/delete, and a before/after comparison with CSV
  download.
- `app.py` routes `Digital Twin`; sidebar and dashboard availability text
  updated. No other placeholder page is changed.

## Phase 7a delivered - abstract flow evaluator
Location: `simulation/` (pure Python; no Streamlit, no LLM, no new
dependencies). Every function is stateless and the baseline twin is never
mutated. All values are modeled estimates from stated assumptions, not
packet-level or hardware-accurate measurements.

- `simulation/models.py`
  - Frozen `NetworkState`, `DemandEvaluation`, `UnservedDemand`, `LinkLoad`,
    `SimulationAssumptions`, `CongestionThresholds`, and `TwinReference`.
  - `MODEL_NOTE` is stored on every result: "Modeled estimates from stated
    assumptions; not packet-level or hardware-accurate."
  - Default bands: warning at or above 70 percent, critical at or above
    90 percent, overloaded strictly above 100 percent. Thresholds are
    configurable and must satisfy `0 < warning < critical < overload`.
  - Optional `link_delay_ms` map (milliseconds). Latency is estimated only when
    every hop has an assumption; a partial map produces `latency_ms=None` and a
    note naming the missing links instead of treating them as zero.
- `simulation/evaluator.py`
  - `evaluate(twin, assumptions=None, *, max_runtime_seconds=None)` routes each
    demand on the single lowest-cost path from the existing routing engine
    (deterministic lexicographic tie-break; no ECMP, no flow splitting).
  - Parallel links use the routing engine's chosen physical link, so only that
    link receives load.
  - An undirected link shares one capacity across both directions; the report
    keeps forward and reverse components separate but utilization uses their
    sum. A directed link records only its permitted direction.
  - Utilization is `load / capacity * 100` and is never clamped; values above
    100 percent are reported as overloaded.
  - Failed devices, links, and links attached to failed devices are excluded.
    Stale twin state is ignored and reported in `warnings`.
  - Unroutable demands are returned as unserved with the routing reason; a
    missing demand endpoint is also unserved with an explicit reason rather
    than crashing the evaluation.
  - Connectivity reports weak components, isolated devices, and devices outside
    the largest component. Largest-component ties resolve by the
    lexicographically first device id.
  - `twin_fingerprint` hashes canonical sorted-key JSON (SHA-256);
    `twin_reference` records the twin name, creation time, schema version, and
    fingerprint on every state.
  - Runtime is bounded by `MAX_SIMULATION_RUNTIME_SECONDS`. A smaller caller
    budget is accepted; a larger one raises `LimitsExceededError`; exceeding
    the budget raises `SimulationRuntimeExceeded`.
- `simulation/tables.py`: UI-agnostic rows for links, demands, unserved
  demands, before/after metrics, and path changes.
- `config/limits.py`: `MAX_SCENARIO_ELEMENTS = 50`.
- `core/exceptions`: `SimulationError`, `SimulationRuntimeExceeded`, and
  `ScenarioValidationError`.
- 20 unit tests in `tests/unit/simulation/`.

## Test evidence (Phase 7a)
- Commands and results:
  - `& ".venv\Scripts\python.exe" -m pytest -q`: `453 passed in 4.08s`
  - `& ".venv\Scripts\python.exe" -m ruff check .`: `All checks passed!`
- Public domain schemas were not changed. The core `ScenarioResult` model is
  untouched; the simulation layer has its own richer result models.

## Phase 7b delivered - scenario engine, history, and exports
- `simulation/scenarios.py`
  - `validate_scenario` translates a `Scenario` into an explicit `ScenarioPlan`
    and raises `ScenarioValidationError` with every accumulated issue. Nothing is
    applied until validation succeeds, and the baseline twin is never mutated.
  - Supports single/multiple link failure, node failure, bandwidth reduction,
    increased traffic demand, new department/network expansion, routing-cost
    change, and redundancy/recovery tests. Type-specific inputs live in the
    existing `Scenario.parameters` dict; the public `Scenario` schema is
    unchanged.
  - Rejects unknown or duplicate affected ids, unknown demand/link keys, and
    fields that do not apply to the selected type instead of ignoring them.
    Element counts are bounded by `MAX_SCENARIO_ELEMENTS`; expansion is also
    bounded by `MAX_NODES`, `MAX_EDGES`, and `MAX_DEMANDS`.
  - `run_scenario(baseline_twin, scenario, assumptions)` returns `ScenarioRun`
    with the validated inputs, assumptions, thresholds, baseline and scenario
    twin references (name, version, SHA-256 fingerprint), both `NetworkState`
    values, a deterministic `ScenarioComparison`, and non-fatal warnings.
    Both evaluations share one `MAX_SIMULATION_RUNTIME_SECONDS` budget.
  - No timestamp or elapsed time is stored; identical inputs produce identical
    results. `compare_runs(left, right)` compares the scenario states of two
    retained results with the right-hand run as the "after" side.
  - `recovery_available` means every demand served at baseline is still served;
    `recovery_note` either confirms that or names the newly unserved demands.
- `simulation/history.py`: `ScenarioHistory`, a bounded ordered store that
  raises `LimitsExceededError` at `MAX_SCENARIOS` instead of silently dropping
  results; supports `add`, `remove`, and `clear`.
- `simulation/export.py`: `run_to_json`, `run_to_json_bytes`, and `run_to_csv`.
  JSON uses sorted keys and CSV uses the standard library writer with `\n`;
  exporting the same run always produces identical bytes.
- `simulation/tables.py`: `link_comparison_rows` adds before/after utilization,
  congestion, and change labels for every link in either state.
- `ui/state.py`: `SIMULATION_HISTORY_KEY` is the single session key, with
  `get_simulation_history`, `get_simulation_runs`, `add_simulation_run`,
  `remove_simulation_run`, and `clear_simulation_history` as the only accessors.
- 33 new unit tests in `tests/unit/simulation/test_scenarios.py`.

## Test evidence (Phase 7b)
- Commands and results:
  - `& ".venv\Scripts\python.exe" -m pytest -q`: `486 passed in 4.03s`
  - `& ".venv\Scripts\python.exe" -m ruff check .`: `All checks passed!`
- Public domain schemas were not changed.

## Phase 7c delivered - Simulation Lab page
- `ui/pages/simulation_lab.py` provides:
  - A baseline traffic-demand editor that writes through `ui.state.set_demands`
    and rejects unknown endpoints, duplicate names, and invalid numbers.
  - Scenario fields for every `ScenarioType`, including link/device selectors,
    bandwidth-reduction mode, traffic factor and optional demand names,
    routing-cost mode, and an expansion JSON editor using the existing
    `parameters["expansion"]` contract.
  - Configurable warning/critical/overload thresholds and explicit per-link
    delay assumptions, validated into `SimulationAssumptions`.
  - Separate Validate and Run actions. Validation errors and typed engine
    errors are displayed inline; nothing is applied to the twin.
  - Before/after metric tiles, a colored link comparison table, a grouped
    utilization bar chart with threshold lines, changed-path and unserved-demand
    tables, and the full `metric_rows` table.
  - A deterministic Plotly topology (seed 42) that highlights failed devices,
    failed/unavailable links, and warning/critical/overloaded links with a
    legend.
  - The mandatory model-scope note at the top of the page and beside results.
  - Bounded session history with load, delete, and clear actions; a two-result
    comparison; and JSON, metrics CSV, link CSV, path CSV, unserved CSV, and
    comparison CSV downloads.
- `app.py` routes and advertises only the `Simulation Lab` page in addition to
  the existing pages; every other placeholder is unchanged.
- `simulation/tables.py`: absent utilization values in `link_comparison_rows`
  are now `None` rather than the string `"not present"`, keeping the numeric
  column Arrow-compatible. This is a presentation helper change, not a public
  schema change.
- 4 AppTest smoke tests in `tests/unit/ui/test_simulation_lab_page.py`:
  empty state, demand editing, scenario validation failure, and two retained
  runs with comparison and export controls.
- `tests/unit/simulation/test_tables.py` covers removed-link comparison rows
  and the `None` utilization value used by the page.

## Test evidence (Phase 7c)
- Commands and results:
  - `& ".venv\Scripts\python.exe" -m pytest -q`: `491 passed in 4.63s`
  - `& ".venv\Scripts\python.exe" -m ruff check .`: `All checks passed!`
- Public domain schemas were not changed.

## Phase 8a delivered - bounded design space, objectives, constraints, and greedy
Location: `optimization/` (pure Python plus NumPy; no Streamlit, no LLM, no new
dependency). Every value is a modeled estimate and every run is a heuristic
search over a stated design space, never a global-optimum claim.

- `optimization/models.py`
  - `Candidate` is a deterministic, serializable decision set over the baseline
    twin: selected links from the user's candidate pool, one capacity tier per
    link, and optional positive routing-cost multipliers. Its before-validator
    canonicalizes and de-duplicates decisions, and `candidate_hash` is a stable
    SHA-256 over canonical JSON.
  - `ObjectiveKind` covers infrastructure cost proxy, maximum utilization, mean
    path cost, SPOF count, minimum edge-disjoint paths, and link count.
    `OBJECTIVE_DEFINITIONS` stores each label, unit, direction, and definition.
  - `ObjectiveSpec` states fixed lower/upper normalization bounds and a weight;
    `OptimizationSettings` rejects non-finite values, duplicate objectives,
    weights that do not sum to 1 (tolerance `1e-9`), duplicate pool ids, and
    non-positive multiplier options.
  - `HardConstraints` covers connectivity, minimum served-demand ratio, maximum
    utilization, budget proxy, `MAX_NODES`/`MAX_EDGES`, and an optional
    minimum edge-disjoint path count.
  - `CandidateEvaluation` records metrics, raw/normalized objective values,
    weighted score, every constraint result (including skipped ones), a
    feasibility flag, and the violated-constraint names.
  - `OptimizationRun` records the algorithm, seed, full settings, explicit
    limits, evaluation/cache counts, typed `StopReason`, baseline, candidate
    records, Pareto front, best feasible record, and the model/cost/search
    notes.
  - Cost scope is documented as a proxy: selected links are charged their tier
    cost, baseline upgrades only their positive tier delta, and optional
    per-device cost is charged once per device. Routing cost is a path metric,
    not money.
- `optimization/space.py`: `build_candidate_twin` applies baseline tier
  upgrades, pool-link additions, and cost multipliers through
  `digital_twin` helpers. The baseline is never mutated.
  `candidate_changes` returns deterministic human-readable changes.
- `optimization/objectives.py`: min-max normalization clamps to the stated
  bounds and inverts maximize objectives; `infrastructure_cost_proxy` and
  `weighted_score` implement the documented arithmetic.
- `optimization/constraints.py`: every hard constraint is checked separately
  from objectives; infeasible candidates are recorded but never recommended.
- `optimization/evaluator.py`: `evaluate_candidate` builds a derived twin,
  reuses the existing simulation evaluator, caches by candidate hash per run,
  counts full evaluations separately from cache hits, and converts a simulation
  runtime stop into a typed optimization stop.
- `optimization/greedy.py`: deterministic hill-climb baseline over one-change
  neighbors (add a pool link, change a tier, adjust a multiplier) that accepts
  only strictly improving feasible moves.
- `config/limits.py`: `MAX_EVALUATIONS = 20_000`,
  `MAX_OPTIMIZATION_RUNTIME_SECONDS = 60`, `MAX_OPTIMIZATION_RUNS = 20`,
  `MAX_POPULATION = 200`, and `MAX_OPTIMIZATION_ITERATIONS = 1_000`.
- 44 unit tests in `tests/unit/optimization/`.

## Phase 8b delivered - seeded GA, NSGA-II, and comparison
- `optimization/algorithms/common.py`: canonical integer genome, random
  generation, crossover, bounded mutation, tournament selection, constrained
  domination, non-dominated sorting, crowding distance, and a brute-force
  enumerator for tiny spaces.
  - Presence genes are per pool link; tier genes are per pool and baseline link;
    multiplier genes are per link. Baseline tier genes encode "unchanged" when a
    tier matches the baseline capacity, and identity multipliers are omitted, so
    equivalent decisions share one hash.
  - `Non-dominated` comparison treats feasible candidates as dominating
    infeasible ones, then fewer violations, then objective Pareto dominance.
- `optimization/algorithms/genetic.py`: seeded Genetic Algorithm with tournament
  selection, uniform crossover, bounded mutation, and elitism. Feasibility is
  never folded into a numeric penalty; elitism/tournament order is by
  constrained domination and then weighted score. The recommendation is the
  best feasible weighted candidate or `None`.
- `optimization/algorithms/nsga2.py`: seeded NSGA-II with constrained
  non-dominated sorting, crowding distance, binary tournament on rank/crowding,
  and combined parent/offspring survival. Selection does not use weights. The
  reported front is the true rank-0 feasible front over every evaluated
  candidate (not only the final population), verified against exhaustive
  enumeration on a 12-candidate tiny space.
- `optimization/algorithms/budget.py`: baseline evaluation happens before the
  search clock starts; the search stops cleanly at `max_evaluations` or the
  runtime limit with a typed `StopReason`.
- `optimization/algorithms/dispatch.py`: one result shape for greedy, genetic,
  and NSGA-II. Particle Swarm Optimization is intentionally omitted: a
  continuous velocity has no sound mapping onto link-presence bits, per-link
  tier choices, and optional multipliers without an undocumented hybrid scheme.
- `optimization/compare.py`: `compare_runs` rejects runs with different settings
  or baselines, reports each algorithm's best feasible candidate, per-objective
  raw/relative change, trade-offs, and its Pareto set, and names a weighted best
  only together with the weights. It never claims a global optimum.
- Reproducibility: identical settings including `seed` produce identical
  `OptimizationRun` dumps. Tests cover brute-force Pareto equality, greedy
  feasibility, weighted recommendations, every hard constraint, limit stop
  reasons, baseline immutability, and dominance/crowding arithmetic.
- Performance spot check on a diamond twin, pool of 3 links, 2 objectives,
  population 50 / 100 iterations / 2,000 max evaluations: GA 719 evaluations in
  about 1.6 s and NSGA-II 592 evaluations in about 4.4 s, both stopping at
  `max_iterations`.

## Phase 8c delivered - Optimization Center page and exports
- `optimization/history.py`: bounded `OptimizationHistory` at
  `MAX_OPTIMIZATION_RUNS`; raises `LimitsExceededError` instead of silently
  dropping runs.
- `optimization/export.py`: deterministic sorted-key JSON and standard-library
  CSV exports. Both include seed, settings, limits, stop reason, baseline, and
  every evaluated candidate; exporting the same run produces identical bytes.
- `ui/state.py`: `OPTIMIZATION_HISTORY_KEY` is the only session key for run
  history, with `get_optimization_history`, `get_optimization_runs`,
  `add_optimization_run`, `remove_optimization_run`, and
  `clear_optimization_history`. `save_twin_snapshot(twin, label)` captures a
  derived design without replacing the baseline.
- `ui/pages/optimization_center.py` provides:
  - Twin/demand guards and the mandatory note: "Heuristic search over a modeled
    design space; no global optimum is claimed. Costs are proxies from stated
    assumptions."
  - Editable candidate-link pool, capacity tiers and proxy costs, optional
    routing-cost multipliers, per-objective selection with weights and fixed
    bounds, every hard constraint, algorithm, seed, population, iterations,
    evaluation cap, and runtime cap.
  - A status/progress indicator while the search runs.
  - Baseline-versus-optimized objective deltas, headline metrics, explicit
    trade-off warnings when an objective worsens, and a two-objective Plotly
    Pareto scatter with the baseline marked.
  - Candidate feasibility counts, a bounded candidate table with violations,
    a bounded inspector for objectives/constraint checks/changes, and explicit
    "save as snapshot" and "replace baseline" actions. Nothing is applied
    automatically.
  - Bounded session history with load/delete/clear, algorithm comparison with
    stated weights and per-objective trade-offs, and deterministic JSON/CSV
    downloads.
- `app.py` routes and advertises only the Optimization Center in addition to the
  existing pages; no other placeholder is changed.
- 7 unit tests for history/export and 6 AppTest smoke tests for the page.

## Phase 9a delivered - optional Groq provider layer
Location: `services/llm/` (pure Python; no Streamlit import and no new
dependency). Core deterministic engineering never imports this package.

- `services/llm/models.py`: frozen `LLMMessage`, `LLMUsage`, `LLMResponse`, and
  `ProviderStatus`. `LLMResponse.structured` exists only when a schema was
  supplied and holds the validated model dump.
- `services/llm/provider.py`: the provider-independent `LLMProvider.complete`
  interface with an optional Pydantic schema.
- `services/llm/groq.py`: `GroqProvider` calls the OpenAI-compatible Groq
  `/chat/completions` endpoint with `urllib.request` and maps every failure to a
  typed error: missing key, authentication, timeout, rate limit (429 with
  bounded `Retry-After`/backoff, capped), provider outage, malformed envelope,
  schema failure, and budget exhaustion. Model and base URL come from
  `config.settings` (`GROQ_MODEL`, `GROQ_BASE_URL`); the documented default model
  is configurable because providers retire models.
- Structured output requests `response_format=json_object`, extracts the first
  JSON value without evaluating code, validates it with the caller's Pydantic
  model, and repairs schema-invalid output at most
  `MAX_LLM_REPAIR_RETRIES` times before raising `LLMSchemaError`.
- `services/llm/budget.py`: `RequestBudget` counts every request (including
  retries and repairs) and provider-reported tokens against
  `MAX_LLM_CALLS_PER_SESSION` and `MAX_LLM_TOKENS_PER_SESSION`.
- `services/llm/testing.py`: clearly named `FakeProvider` test double with
  scripted text, malformed output, timeouts, and typed failures. It is not a
  user-facing demo mode.
- `config/settings.py`: `GROQ_MODEL` and `GROQ_BASE_URL` are configurable via
  environment variables or Streamlit secrets; the API key already follows that
  path.
- `config/limits.py`: LLM call, token, repair, rate-limit retry, backoff,
  timeout, and response-token limits.
- `core.exceptions`: typed LLM failures. Keys are never logged, traced,
  serialized, or placed in error messages; a test scans logs, errors, status,
  and JSON output for the secret.
- 15 unit tests; no test performs a real network request.

## Phase 9b delivered - bounded agent core and deterministic workflow
Location: `agents/` (pure Python; no Streamlit import, no LLM import, no new
dependency). The package never imports `services.llm`, so the deterministic
structured-form workflow works with no API key.

- `agents/models.py`: typed `WorkflowTask`, `WorkflowPlan`, `TaskState`,
  `TaskStatus`, `WorkflowStopReason` (`completed`, `failed`, `step_limit`,
  `runtime_limit`, `replan_limit`), and `ExecutionTrace` with an injectable
  `Clock`. Trace entries are ordered, serializable, and redact values under
  credential-looking keys. `WorkflowState` stores the plan, per-task status and
  attempts, results, and a derived working twin; the baseline twin is read
  through an injected accessor and never copied.
- `agents/tools.py`: `Tool` and `ToolRegistry` with a typed input model, typed
  output model, and pure implementation per tool. Built-ins wrap topology
  generation/connectivity, VLSM, VLAN, addressing validation/overlap, routing
  path/table, structural analysis, SPOF, twin validation, simulation,
  optimization, demand planning, and working-twin construction. Unknown,
  disallowed, invalid-input, invalid-output, and implementation failures raise
  typed `ToolError` subclasses. No tool runs a shell, `eval`, or `exec`.
- `agents/base.py`: `BaseAgent` with a name, responsibility, typed input/output
  models, and a frozen tool allowlist, plus `AgentContext` that resolves only
  allowed tools and traces both sides of every call.
- `agents/network_agents.py`: nine standard agents (requirements, topology,
  IP/VLAN, routing, validation, simulation, optimization, re-validation,
  report) returning typed result models. Validation combines addressing checks
  with complete-twin validation.
- `agents/planning.py`: the documented deterministic design policy (topology
  family thresholds, base network `10.0.0.0/16`, VLAN start 10, modeled demand
  at ten percent of reported users bounded to 1-1000 Mbps) and conversion of
  requirements into a derived working twin using the existing engines.
- `agents/orchestrator.py`: plan validation (duplicate ids, missing
  dependencies, cycles, unknown agents, unregistered tools), deterministic
  dependency order, bounded attempts (`MAX_AGENT_RETRIES`), workflow step and
  runtime caps, typed stop reasons, transitive dependent skipping on failure,
  selective re-planning bounded by `MAX_AGENT_REPLANS` (address conflicts reset
  only the IP/VLAN task and its dependents), and
  `build_standard_plan`/`run_structured_design` for the nine-step plan without
  any provider.
- `config/limits.py`: added `MAX_AGENT_REPLANS`; clarified that
  `MAX_AGENT_RETRIES` counts total attempts including the first.

## Test evidence (Phase 9b)
- Commands and results:
  - `.venv\Scripts\python.exe -m pytest -q`: `629 passed in 7.59s`
  - `.venv\Scripts\ruff.exe check .`: `All checks passed!`
- `tests/unit/agents/` (26 tests) covers tool-registry unknown/disallowed/
  malformed input and output, generator-parameter rejection, engine parity for
  VLSM and topology generation, plan shape/cycle/missing-dependency/duplicate/
  step-cap validation, dependency order, retry bounds, step and runtime stop
  reasons, failed-task dependent skipping, a seeded IP-overlap that triggers one
  selective re-plan (upstream tasks run once), the re-plan cap, end-to-end
  determinism against the direct engines with no provider, baseline-twin
  immutability through the accessor, trace ordering/serialization/redaction,
  and a source scan proving the package has no shell/eval/Streamlit/provider
  escape hatch.
- No real Groq request was made in this task.

## Phase 9c delivered - Settings page and structured design form
- `ui/pages/settings.py`: optional AI configuration and a deterministic design
  runner. Shows only whether a key is configured and where it came from (never
  the key), the configured model, the session request/token budget and
  remaining calls, and the read-only limits from `config/limits.py`. Explains
  which features need a key and which never do. A bounded connection test makes
  at most one request with a 15-second timeout, no rate-limit retries, and no
  repair retries; the builder is a module-level function so tests inject a fake
  provider and never contact the network. Includes secrets/environment
  documentation and session-only key entry with save/clear actions.
- `ui/components/requirements_form.py`: small structured form (organization,
  site, bounded department list, design goals, constraints) that builds a typed
  `NetworkRequirements`, runs `Orchestrator.run_structured` with no LLM, stores
  the typed `WorkflowState` in session state, and shows task statuses, step and
  re-plan counts, the report, and a downloadable execution trace. The baseline
  twin is read through `ui.state.get_twin` and never replaced; the derived
  working twin is reported separately.
- `ui/components.py` became the `ui/components/` package; existing
  `from ui.components import ...` imports are unchanged.
- `ui/state.py`: session accessors for the optional LLM session key and the
  per-session `RequestBudget`.
- `app.py`: the Settings page is now ready and routed; only that placeholder
  changed. Dashboard and sidebar copy updated to Phase 9 and the new page.
- `tests/unit/ui/test_settings_page.py` (8 AppTest tests): no-key and
  key-present states, the key never appearing in rendered output or other
  session values, saving/clearing a session key, budget display/reset, a
  provider-unavailable connection test that raises no exception, a successful
  fake connection test, an end-to-end deterministic form run with an untouched
  baseline twin, and a form validation error.

## Test evidence (Phase 9c)
- Commands and results:
  - `.venv\Scripts\python.exe -m pytest -q`: `637 passed in 8.88s`
  - `.venv\Scripts\ruff.exe check .`: `All checks passed!`
- No real Groq request was made in this task. The connection test was exercised
  only with injected fake providers (success and typed-failure cases).

## Phase 10a delivered - Requirements Understanding Agent
- `agents/requirements_agent.py`: `RequirementsUnderstandingAgent` converts
  bounded free text into validated `NetworkRequirements`. The optional model
  returns only a `RequirementsExtraction` draft; deterministic Python audits
  every number, rebuilds the typed facts, and keeps user-provided facts and
  system assumptions in separate fields.
- A number is promoted to a user fact only when it appears literally in the
  supplied text or comes from structured input. Invented department counts are
  dropped from the fact layer and recorded as assumptions with a clarification
  question.
- Deterministic checks include non-negative bounds, the per-subnet host limit,
  duplicate departments, missing user counts, missing total, missing
  organization/site/goals, and a stated-total versus department-sum
  contradiction.
- Merge policy: structured-form values are authoritative; verified extracted
  departments with new names are appended. The contradiction check compares the
  stated total against the fully merged department sum.
- No-provider behaviour: free text returns an `unavailable` status with the
  structured-form path offered; supplied structured requirements are validated
  and kept. No requirements are fabricated without a provider.
- Provider failures and exhausted bounded repairs return a typed `failed`
  result. Malformed output is retried only within `MAX_LLM_REPAIR_RETRIES`.
- New bounded constants in `config/limits.py`:
  `MAX_REQUIREMENTS_TEXT_CHARS`, `MAX_REQUIREMENTS_DEPARTMENTS`,
  `MAX_REQUIREMENTS_LIST_ITEMS`, and `MAX_CLARIFICATION_QUESTIONS`.
- Tool allowlist is exactly `requirements_validate`; the agent imports the LLM
  provider interfaces but performs no network, shell, Streamlit, or code
  execution.
- `tests/unit/agents/test_requirements_agent.py` (16 tests): valid extraction,
  facts versus assumptions, ungrounded goal removal, invented number rejection,
  missing information/questions, contradiction detection, oversized counts,
  provider failure, malformed-output repair and exhaustion, unavailable paths,
  structured-only path, structured merge, input bounds, and tool allowlist.
- The agent package escape-hatch test now also rejects `urllib` and
  `http.client` imports.

## Test evidence (Phase 10a)
- Commands and results:
  - `.venv\Scripts\python.exe -m pytest -q tests/unit/agents`: `42 passed in 0.76s`
  - `.venv\Scripts\python.exe -m pytest -q`: `653 passed in 11.14s`
  - `.venv\Scripts\ruff.exe check .`: `All checks passed!`
- No live provider request was made. All model paths use the scripted
  `FakeProvider`; the no-provider path uses no provider at all.
- Public domain schemas were not changed by 10a.

## Phase 10b delivered - Validation and Critic Agent
- `agents/critic.py`: `CriticAgent` independently calls deterministic tools for
  topology connectivity, addressing overlap/duplicates, twin validation, routing
  reachability, modeled load/unserved demands, and SPOF analysis. It never reads
  the validation or revalidation tasks and cannot be told a design is valid.
- The verdict is computed deterministically: any error/critical finding is
  `REJECTED`, warnings alone produce `APPROVED_WITH_WARNINGS`, and no findings
  produce `APPROVED`. Findings are deduplicated by code and sorted entities.
- Every blocking finding records the responsible workflow step. Mapping:
  IP/VLAN issues -> `ip_vlan`; topology, routing, and redundancy issues ->
  `topology`; overloaded/critical links -> `optimization`; unknown codes ->
  `revalidation`. An explicit `replan_target` takes priority.
- The optional model note is separate from the verdict, bounded by
  `MAX_CRITIC_SUMMARY_CHARS`, and ignored on any provider failure.
- `agents/tools.py`: added `twin_load_state`, backed by `simulation.evaluate`.
- `agents/orchestrator.py`: standard plan is now ten tasks with `critic` before
  `report`; critic-origin re-plans reset only the target and its dependents.
  Missing/unmapped/declined/over-limit critic re-plans stop with the typed
  `WorkflowStopReason.critic_rejected`.
- `agents/network_agents.py`: registered `CriticAgent` and added a deterministic
  "Critic review" report section.
- `tests/unit/agents/test_critic.py` (16 tests): clean approval, disconnected
  topology, overloaded link, missing redundancy, IP overlap, missing twin,
  verdict immunity to model text in both directions, provider failure, ignored
  prior validity, deduplication, tool allowlist, step mapping, and a full
  workflow with a scripted provider.
- Orchestrator tests cover a validation-free selective critic re-plan (only
  `ip_vlan` and dependents re-run), a typed critic-rejected stop when the target
  declines, and a critic re-plan-limit stop.

## Test evidence (Phase 10b)
- Commands and results:
  - `.venv\Scripts\python.exe -m pytest -q tests/unit/agents`: `61 passed in 1.22s`
  - `.venv\Scripts\python.exe -m pytest -q`: `672 passed in 11.91s`
  - `.venv\Scripts\ruff.exe check .`: `All checks passed!`
- No live provider request was made. Model notes use the scripted
  `FakeProvider`; the deterministic workflow runs without any provider.
- Public domain schemas were not changed by 10b.

## Phase 10c delivered - Documentation Agent
- `agents/documentation.py`: `DocumentationAgent` collects only validated task
  results. It never recalculates a design value; every printed number is copied
  from a deterministic result and tagged with its `step` and `tool`.
- The report contains a summary, topology choice with a deterministic rationale,
  addressing/VLAN and DHCP tables, routing summary, critic findings, simulation
  comparison, optimization comparison against the baseline, assumptions,
  limitations, and the full execution trace.
- Assumptions come only from `NetworkRequirements.assumptions` and the demand
  planning note; limitations explicitly label modeled estimates, bounded
  search, optional free-text interpretation, and the absence of PDF export.
- Optional AI explanation: the model receives the computed report and may only
  add prose. Any numeric token that does not match a computed value causes the
  text to be rejected and replaced with the deterministic summary, with
  `ai_rejected=True` and a visible note. Provider failures never fail the task.
- Exports: `export_json` (sorted, round-trips through the model),
  `export_csv` (one provenance-tagged row per table cell), and
  `export_markdown` (sections, tables, sources, assumptions, limitations,
  trace). No PDF is produced.
- `agents/orchestrator.py`: standard plan is now eleven tasks with
  `documentation` between `critic` and `report`.
- `agents/network_agents.py`: registered `DocumentationAgent` and added a
  deterministic "Documentation" report section.
- `config/limits.py`: added `MAX_DOCUMENTATION_EXPLANATION_CHARS`.
- `tests/unit/agents/test_documentation.py` (14 tests): complete plan without a
  provider, engine-matching addressing/routing/topology values, provenance on
  every number, critic findings copied, separated assumptions/limitations,
  hostile model number rejection, accepted model text, provider failure,
  export round-trip, rejected-explanation labelling, trace coverage, empty tool
  allowlist, and the no-execution/no-network import guard.

## Test evidence (Phase 10c)
- Commands and results:
  - `.venv\Scripts\python.exe -m pytest -q tests/unit/agents`: `75 passed in 0.99s`
  - `.venv\Scripts\python.exe -m pytest -q`: `686 passed in 11.23s`
  - `.venv\Scripts\ruff.exe check .`: `All checks passed!`
- No live provider request was made. The optional explanation is exercised with
  the scripted `FakeProvider`; the deterministic path needs no provider.
- Public domain schemas were not changed by 10c.

## Phase 10d delivered - AI Network Designer and Agent Control Center
- `ui/pages/ai_designer.py`: free-text interpretation and the structured form
  side by side when a key is configured. Without a key the page shows the form
  alone with a note; the form runs the full deterministic workflow.
- Free text is optional and bounded by `MAX_REQUIREMENTS_TEXT_CHARS`. Structured
  form values are merged into the interpretation only when the user enables the
  explicit merge checkbox; otherwise free text is interpreted alone.
- `agents/requirements_agent.py`: added `understand_requirements`, a
  single-task helper used by the UI. It builds the same bounded `AgentContext`
  as the orchestrator and writes no workflow or baseline state.
- Results show the requirements summary, user-provided facts and system
  assumptions in separate tables, missing/contradictory items, and clarification
  questions. The workflow result shows the summary, critic verdict and findings,
  documentation preview, assumptions, limitations, and labelled AI text.
- Applying a design always saves a new snapshot through
  `ui.state.save_twin_snapshot`; the page never replaces the baseline twin.
- `ui/pages/agent_control_center.py`: read-only task DAG table with dependencies,
  status, attempts, re-plans, summed duration, skipped reason, and error; typed
  stop reason and workflow error; critic verdict and findings; full trace table
  with a JSON download. A source selector appears when more than one workflow
  has run in the session.
- `app.py`: both pages are wired into navigation and `READY_PAGES`; the
  dashboard text and navigation caption now describe Phase 10.
- `tests/unit/ui/test_ai_designer_page.py` (7 tests) and
  `tests/unit/ui/test_agent_control_center_page.py` (5 tests): no-key form-only
  state, deterministic run with baseline immutability, fact/assumption
  separation, provider failure, interpreted requirements driving the workflow,
  new-snapshot apply, typed failure display, read-only DAG/trace/critic,
  multi-source selection, and no session-key leakage into rendered text or
  trace JSON.

## Test evidence (Phase 10d)
- Commands and results:
  - `.venv\Scripts\python.exe -m pytest -q tests/unit/ui/test_ai_designer_page.py tests/unit/ui/test_agent_control_center_page.py`: `12 passed in 3.46s`
  - `.venv\Scripts\python.exe -m pytest -q`: `698 passed in 11.54s`
  - `.venv\Scripts\ruff.exe check .`: `All checks passed!`
- No live provider request was made. Free-text tests use the scripted
  `FakeProvider` through an injected `_build_provider`; the no-key path uses no
  provider at all.
- Public domain schemas were not changed by 10d.

## Phase 11a delivered - report document, provenance, and consistency
Location: `services/reporting/` (pure Python; no Streamlit, ReportLab, or
network import).

- `models.py`: `ReportDocument` with ordered typed sections, discriminated
  content blocks (`paragraph`, `key_value`, `table`, `note`), `Provenance`
  (`step`, `tool`, `twin_version`), the `ValueRecord` audit appendix, and
  disclosure labels. A section with no input is stored as `status="not_run"`
  with both a reason and the page that produces the missing data.
- `builder.py`: builds eleven sections from the digital twin and the optional
  scenario, optimization, and workflow objects: architecture summary, topology
  and selection rationale, addressing, VLAN/DHCP, routing/reachability, graph
  analysis, simulation before/after, optimization versus baseline,
  assumptions, limitations, and agent execution trace. Every number is copied
  from an engine, formatted through `format_number`, and recorded with
  provenance. Engine prose that is reproduced verbatim (findings, notes,
  paths, errors) is scanned so its numeric tokens stay traceable. Tables are
  bounded by `MAX_REPORT_TABLE_ROWS` and keep the source row count for a
  visible truncation note.
- `templates.py`: deterministic explanation prose built only from caller-
  supplied values, plus the fixed limitation statements and disclosure text.
- `consistency.py`: `check_consistency` treats the `ValueRecord` appendix as
  the authoritative number set and reports `orphan_number`, `missing_label`,
  `missing_provenance`, and `empty_section` findings. IP addresses, CIDR
  prefixes, and identifier-embedded digits are masked before token extraction.
- `explain.py`: optional AI prose using the Phase 10 numeric-token rule.
  Unavailable providers and unsourced numbers leave the deterministic report
  unchanged; accepted text is always labelled as AI-generated.
- `config/limits.py`: added `MAX_REPORT_TABLE_ROWS` and `MAX_REPORT_BYTES`.
  `core/exceptions/__init__.py`: added `ReportError`, `ReportBuildError`,
  `ReportExportError`, and `ReportLimitError`.
- `tests/unit/services/test_reporting.py` (24 tests): engine-matching values,
  not-run reasons and producer pages, injected clock, deterministic rebuild,
  clean consistency, tampered-number and missing-label detection, provenance
  completeness, table truncation, section filtering, simulation/optimization/
  workflow values, AI accept/reject/absent/provider-error paths, and token
  masking.

## Test evidence (Phase 11a)
- Commands and results:
  - `.\.venv\Scripts\python.exe -m pytest -q`: `722 passed in 14.01s`
  - `.\.venv\Scripts\ruff.exe check .`: `All checks passed!`
- No live provider request was made; the explanation tests use
  `services.llm.testing.FakeProvider`.
- No report export existed at 11a; Markdown, JSON, CSV, PDF, and configuration
  templates were delivered in 11b.

## Phase 11b delivered - Markdown, JSON, CSV, PDF, and configuration templates
Location: `services/export/` (pure Python plus ReportLab; no Streamlit, no
network access, no disk writes).

- Every function is a pure in-memory export: `to_markdown`, `to_json`,
  `from_json`, `to_csv_bundle`, `to_pdf`, `config_templates`, and
  `to_config_bundle` all return `bytes` (or immutable models) and never touch
  the filesystem or a device.
- `common.py`: fixed ZIP member timestamp and permissions make archives
  byte-identical for the same input; every exporter enforces
  `MAX_REPORT_BYTES` through `ReportLimitError`.
- `markdown.py`: readable rendering of the same typed document (title block,
  labels, contents, every section, AI appendix, value-provenance appendix,
  model note). Table cells are escaped, truncated tables keep their visible
  note, and the value appendix is bounded by `MAX_REPORT_TABLE_ROWS` with a
  "showing first N of M" line.
- `json_export.py`: deterministic UTF-8 JSON (sorted keys, two-space indent)
  of the document's own model dump. `from_json` validates schema version and
  document structure back into `ReportDocument`; the round trip is exact.
- `csv_export.py`: exports the IP plan, VLAN assignments, DHCP scopes, routing
  table, link utilization, findings, and optimization-candidate tables that
  exist in the document. UTF-8 with CRLF terminators; an optional UTF-8 BOM is
  documented in `CSV_ENCODING_NOTE` and written only on request. The ZIP
  bundle includes a README naming the report, twin fingerprint, encoding and
  BOM state, each table's row count, and any truncation note.
- `config_templates.py`: five design-intent templates (devices, interfaces,
  subnets, VLANs, DHCP scopes) built only from validated twin data. The first
  line of every file is exactly `TEMPLATE - not applied to any device`; every
  value is traceable to the twin, and no static-route or device-derived
  content is invented.
- `pdf.py`: ReportLab rendering with a title block, disclosure labels,
  contents, section list, wrapping and paginating tables (repeating header
  rows), source captions, page numbers, a header/footer stamped from the
  injected clock, the exact disclosure footer, and a bounded value appendix.
  Metadata dates and body text are pinned to the injected clock, and
  `pageCompression=0` with `invariant=1` makes repeat builds byte-identical.
  Texts longer than `MAX_PDF_CELL_CHARS` are visibly truncated. Non-Latin
  characters are replaced with `?` and a visible notice points to the
  Markdown/JSON exports; Arabic shaping and right-to-left layout are not
  attempted.
- `tests/unit/services/test_export.py` (18 tests): JSON round-trip and
  malformed/unsupported payloads, Markdown content and determinism, truncation
  notes, CSV content/BOM/ZIP stability and README truncation reporting,
  configuration-template header and twin-only values, ZIP stability, PDF
  structure/footer/injected clock, byte-identical repeats, long-table
  pagination, visible row and cell truncation, non-Latin fallback (with UTF-8
  exports preserving the original text), and the size bound on all four
  exports.

## Test evidence (Phase 11b)
- Commands and results:
  - `.\.venv\Scripts\python.exe -m pytest tests/unit/services/test_export.py -q`: `18 passed in 1.44s`
  - `.\.venv\Scripts\python.exe -m pytest -q`: `746 passed in 13.70s`
  - `.\.venv\Scripts\ruff.exe check .`: `All checks passed!`
- PDF assertions inspect the uncompressed Latin-1 byte stream for literal text
  and count `/Type /Page` objects. A visual render pass (glyph positioning,
  column widths, page-break quality, non-Latin squares) was not performed.
- No dependency was added; ReportLab was already in `requirements.txt`. No
  public domain schema changed.

## Phase 11c delivered - Reports & Documentation page
Location: `ui/pages/reports.py`, wired into `app.py`.

- The page builds one report document from the current twin plus any retained
  workflow, scenario run, or optimization run the user selects. Sources are
  chosen explicitly; the latest retained run is preselected. The report body
  never contains raw model output.
- Section selection uses a multiselect over the ordered section ids, with
  available sections preselected. A section table lists every section that was
  not run, its reason, and the page that produces the missing data
  (`Simulation Lab`, `Optimization Center`, `AI Network Designer`).
- The consistency panel runs `check_consistency` on the selected document and
  shows the summary plus a finding table (code, severity, section, token,
  message) when anything fails.
- The preview renders typed blocks directly: paragraphs, notes, key/value
  tables, and paginated data tables with their source line and truncation note.
  A collapsed appendix lists the source-value registry, bounded to
  `MAX_REPORT_TABLE_ROWS`.
- Downloads offer PDF, Markdown, JSON, a CSV-table ZIP, and a configuration
  template ZIP. All five are generated in memory for the current selection. A
  non-Latin document shows the PDF font-coverage warning before the buttons,
  and the template note states that no template is device-applied.
- The empty state explains that a twin with a topology is required and points
  to the Topology Editor. Selecting no sections shows a warning and suppresses
  the downloads.
- `tests/unit/ui/test_reports_page.py` (6 tests): empty state, populated page
  with every download, section-limited preview, no-selection guard, a retained
  workflow filling the agent-trace section, and a retained scenario run filling
  the simulation section.

## Test evidence (Phase 11c)
- Commands and results:
  - `.\.venv\Scripts\python.exe -m pytest tests/unit/ui/test_reports_page.py -q`: `6 passed in 3.48s`
  - `.\.venv\Scripts\python.exe -m pytest -q`: `746 passed in 13.70s`
  - `.\.venv\Scripts\ruff.exe check .`: `All checks passed!`
- AppTest exercises the page in-process; no real browser, screenshot, or
  download-file inspection was performed. Export bytes are covered by the 11b
  service tests.

## Phase 12a delivered - unified design health
Location: `services/validation/`, `ui/components/health.py`, wired into the
Digital Twin, Dashboard, and Topology Editor.

- One deterministic `build_design_health` entry point reuses the existing
  twin, addressing, DHCP, routing, capacity, and redundancy engines. Every
  `Finding` records category, severity, affected entities, remediation, and
  whether its check is expensive. Findings are sorted by severity.
- Basic checks always run. All-pairs reachability and redundancy/SPOF checks
  are opt-in through `include_expensive=True` and carry a visible cost note.
- Free-form constraints remain informational. Only `max utilization N%`,
  `served demand ratio N`, and `no single point of failure` are machine-checked.
- `tests/unit/services/test_design_health.py`: crafted twin per category, clean
  twin, severity ordering, and opt-in expensive checks.
- Commit: `e8e5d54`.

## Phase 12b delivered - profiling and bounded derived results
- `scripts/profile_phase12.py` measures real wall-clock time and tracemalloc
  peak for eight worst-case operations. Both variants are reproducible with
  `--no-memory` and the default tracemalloc mode.
- Batched `replace_links` plus one `set_topology` removed 661 sequential
  deep-copying link edits per candidate. GA and NSGA-II now stop at the
  configured `MAX_OPTIMIZATION_RUNTIME_SECONDS=60` budget.
- `ui/cache.py` adds content-keyed caches for design health, report documents,
  and each export. Reports no longer rebuild exports on every rerun. Workflow
  reports build directly from the live workflow; exports remain cached.
- Report `generated_at` is stable per twin fingerprint through a session map
  capped at 4 entries. `tests/unit/ui/test_cache.py` and new report assertions
  cover reuse and invalidation when the twin changes.
- `config/limits.py` documents the measured session payload sizes behind the
  retained-history bounds.

### Session-key audit (measured)
| payload | measured size | bound |
| --- | ---: | --- |
| max twin JSON | 257,236 bytes | one active twin |
| snapshot JSON | 257,301 bytes | 20 snapshots / 2 MB total |
| scenario run JSON | 766,147 bytes | 50 runs, about 37 MiB worst case |
| 5 s optimization run | 203,574 bytes | 20 runs |
| 60 s GA run | about 2.38 MiB / 77 candidates | counted in the 20-run bound |
| 60 s NSGA-II run | about 2.35 MiB / 76 candidates | counted in the 20-run bound |
| optimization history worst case | about 48 MiB | 20 retained runs |

- Cache keys are canonical twin JSON plus `twin_fingerprint`. The
  `WorkflowState` accessor is live and deliberately not cacheable.
- Commit: `642db31`.

## Phase 12c delivered - UI consistency and navigation
- `ui/components` now provides `page_header`, `empty_state`,
  `model_estimate_note`, and `render_findings`, plus versioned editor keys and
  one-shot notices. A rejected `st.data_editor` submission advances the widget
  version, queues the error, and reruns; the rejected rows no longer linger.
- All 14 sidebar entries route to working pages. `render_placeholder` and all
  "coming soon"/"later phase" wording were removed.
- Page titles, descriptions, empty states, error wording, units, number
  formats, table column labels, and download placement were normalized. Model
  outputs are consistently labeled as estimates.
- The Dashboard is real-data only: twin metrics, retained-run counts, latest
  scenario and optimization summaries, and one design-health panel. Read-only
  `peek_*` accessors in `ui/state.py` prevent a Dashboard view from creating
  empty history stores.
- `ui/pages/capacity_planning.py` is a read-only inventory from existing twin
  and scenario data. It does not forecast growth or recommend capacity changes.
- New AppTest coverage: editor rejection reset, Dashboard empty and populated,
  Capacity Planning empty and populated, and all 14 nav entries with and
  without a twin. All existing assertions were kept; new tests were added.

## Test evidence (Phase 12)
- Commands and verbatim results:
  - `.\.venv\Scripts\python.exe -m pytest -q`: `803 passed in 19.89s`
  - `.\.venv\Scripts\ruff.exe check .`: `All checks passed!`
- No existing test assertion was changed in Phase 12. New assertions were
  added in `tests/unit/services/test_design_health.py`,
  `tests/unit/topology/test_operations.py`,
  `tests/unit/optimization/test_models.py`, `tests/unit/ui/test_cache.py`,
  `tests/unit/ui/test_reports_page.py`,
  `tests/unit/ui/test_digital_twin_page.py`,
  `tests/unit/ui/test_navigation.py`,
  `tests/unit/ui/test_dashboard_page.py`,
  `tests/unit/ui/test_capacity_planning_page.py`, and
  `tests/unit/ui/test_simulation_lab_page.py`.
- Profiler output, wall clock (`--no-memory`):

  | operation | seconds | peak MiB | over budget | note |
  | --- | ---: | ---: | :---: | --- |
  | generate max-size topology | 0.004 | 0.0 | no |  |
  | build max twin | 0.088 | 0.0 | no |  |
  | all-pairs routing | 0.935 | 0.0 | no |  |
  | evaluate with MAX_DEMANDS | 0.761 | 0.0 | no |  |
  | genetic at configured maxima | 60.872 | 0.0 | yes | user-triggered search; wall clock is bounded by MAX_OPTIMIZATION_RUNTIME_SECONDS=60 |
  | nsga2 at configured maxima | 60.860 | 0.0 | yes | user-triggered search; wall clock is bounded by MAX_OPTIMIZATION_RUNTIME_SECONDS=60 |
  | report build | 2.010 | 0.0 | no |  |
  | PDF build | 1.158 | 0.0 | no |  |

- Profiler output, tracemalloc:

  | operation | seconds | peak MiB | over budget | note |
  | --- | ---: | ---: | :---: | --- |
  | generate max-size topology | 0.062 | 1.4 | no | timing includes tracemalloc overhead |
  | build max twin | 0.212 | 0.8 | no | timing includes tracemalloc overhead |
  | all-pairs routing | 3.768 | 4.8 | no | timing includes tracemalloc overhead |
  | evaluate with MAX_DEMANDS | 4.778 | 4.6 | no | timing includes tracemalloc overhead |
  | genetic at configured maxima | 65.271 | 7.3 | no | user-triggered search; wall clock is bounded by MAX_OPTIMIZATION_RUNTIME_SECONDS=60; timing includes tracemalloc overhead |
  | nsga2 at configured maxima | 64.816 | 6.7 | no | user-triggered search; wall clock is bounded by MAX_OPTIMIZATION_RUNTIME_SECONDS=60; timing includes tracemalloc overhead |
  | report build | 9.367 | 6.2 | no | timing includes tracemalloc overhead |
  | PDF build | 6.954 | 8.7 | no | timing includes tracemalloc overhead |

- Footer printed by both profiler runs: "Budget threshold: >5 s in a
  `--no-memory` run, or >300 MiB in a tracemalloc run, is flagged. Tracemalloc
  adds time overhead and records Python allocations, not total process RSS. Run
  with `--no-memory` for wall-clock numbers."
- The two marked search results are deliberate user-triggered bounded searches,
  not unbounded page operations. All measured tracemalloc peaks are below
  300 MiB.
- Not verified: real-browser rendering, responsive layout at narrow widths,
  visual PDF viewer behavior, and live LLM/provider responses. Verification
  was AppTest plus service/unit tests and the reproducible profiler.

## Test evidence (Phase 8)
- Commands and results:
  - `& ".venv\Scripts\python.exe" -m pytest -q`: `588 passed in 7.81s`
  - `& ".venv\Scripts\python.exe" -m ruff check .`: `All checks passed!`
- `tests/unit/optimization/` covers cost arithmetic, normalization and weights,
  every hard constraint, infeasible-candidate exclusion, greedy feasibility,
  deterministic JSON/CSV exports, bounded history, dominance and crowding
  units, reproducibility, limit stop reasons, baseline immutability, and the
  brute-force Pareto front versus NSGA-II on a tiny topology.
- `tests/unit/ui/test_optimization_center_page.py` covers the no-twin and
  no-demand guards, a full greedy run with results and downloads, candidate-pool
  parsing, the no-feasible-candidate warning, and explicit snapshot creation.
- Public domain schemas were not changed. Optimization-specific inputs and
  results live in `optimization/models.py`.
- Phase 8 deliberately omits PSO: a continuous velocity has no sound mapping
  onto discrete link-presence/tier/multiplier decisions without an undocumented
  hybrid scheme.

## Test evidence (Phase 6)
- `tests/unit/digital_twin/` (53 tests): frozen models and effective state,
  stale/duplicate validation, addressing/DHCP validator reuse, immutable
  operations, baseline equality after failures and scenarios, deep-copied
  snapshots, diffs, store bounds, exact JSON round-trip, schema-version errors,
  and the engine adapters.
- `tests/unit/ui/test_digital_twin_page.py` (3 tests): empty state, summary +
  snapshot creation/comparison, and twin failures reaching the routing page.
- Existing AppTest suites now assert `ui.state.TWIN_KEY` instead of the removed
  raw topology/VLAN keys; all widget keys are unchanged.
- Commands and results:
  - `& ".venv\Scripts\python.exe" -m pytest -q`: `433 passed in 4.33s`
  - `& ".venv\Scripts\python.exe" -m ruff check .`: `All checks passed!`
- Public domain schemas were not changed in Phase 6.

## Test evidence (Phase 5)
- Unit tests:
  - `tests/unit/routing/` (50 tests): hand-computed weighted triangle (a-b-c
    costs 3 vs direct 4), equal-cost diamond tie-break (`a-b-d` before
    `a-c-d`), line, ring, star, disconnected, and directed-asymmetry cases;
    failure cases; generated star/ring/campus/spine-leaf topologies; every
    returned path re-walked against the graph so cost equals the summed link
    costs; limit enforcement.
  - `tests/unit/analysis/` (41 tests): hand-computed degree/betweenness on a
    line, cost-weighted betweenness on the triangle, component and diameter
    behaviour including disconnected topologies, articulation points,
    bridges, parallel-link handling, node-/edge-disjoint counts (including a
    directed asymmetry and parallel-link edge redundancy), SPOF findings, and
    the `MAX_NODES` bound.
  - `tests/unit/ui/test_analysis_pages.py` (4 tests): AppTest smoke tests for
    both pages, including the empty state and a failure scenario on the
    routing page.
- Commands and results:
  - `& ".venv\Scripts\python.exe" -m pytest -q`: `377 passed in 3.54s`
  - `& ".venv\Scripts\python.exe" -m ruff check .`: `All checks passed!`
- Public domain schemas were not changed in Phase 5.
- Headless app verification (port 8554, `--server.address 127.0.0.1`,
  `--server.enableAgentApi true`):
  - `/_stcore/health`: HTTP 200 (`ok`); root page: HTTP 200.
  - Generated a star in the Topology Editor (Devices 7, Links 6, Components 1,
    Isolated devices 0), then opened Routing Analysis: Cost 1.00, Hops 1,
    Baseline cost 1.00, Status reachable, with path table, alternatives,
    routing table, reachability matrix, downloads, and a Plotly chart.
  - Failed `star-hub` with destination `star-spoke-01`: Cost `unreachable`,
    Hops `-`, Baseline cost 1.00, Status `unreachable`, no app exception.
  - Network Analytics: Devices 7, Links 6, Components 1, Diameter (hops) 2,
    SPOF entities 7, Node-disjoint paths 1, Edge-disjoint paths 1; centrality
    bar charts, tables, findings, and downloads rendered without exception.

## Test evidence (Phase 4)
- Unit tests: `tests/unit/addressing/` (39 tests) and `tests/unit/vlan/`
  (36 tests) cover known-answer CIDR cases (`/24`, `/26`, `/30`, `/31`,
  `/32`, class-A splits, IPv6 `/64`, `/127`, `/128`), the classic
  192.168.1.0/24 VLSM example with hand-computed prefixes and host ranges,
  insufficient space, reserved-address edges, duplicate names/IPs, overlap,
  utilization, DHCP pool boundary violations, and the property that allocated
  subnets never overlap and stay inside the parent.
- UI smoke tests: `tests/unit/ui/test_planning_pages.py` uses AppTest to
  navigate to both pages, run CIDR/VLSM/overlap checks, build a VLAN and DHCP
  plan, and confirm a malformed parent surfaces an error without writing state.
- Full suite and lint results are recorded below.

## Test evidence (Phase 4c)
- Commands:
  - `& ".venv\Scripts\python.exe" -m pytest -q`
  - `& ".venv\Scripts\python.exe" -m ruff check .`
- Results:
  - `282 passed in 2.39s`
  - `All checks passed!`
- Headless app verification (port 8552, `--server.address 127.0.0.1`,
  `--server.enableAgentApi true`):
  - `/_stcore/health`: HTTP 200 (`ok`); root page: HTTP 200.
  - Agent API: navigated to both Phase 4 pages and drove them with no app
    exceptions. IP page metrics included prefix `/24`, 256 total addresses,
    254 usable hosts; VLSM produced 5 subnets, 248 addresses allocated, 8
    remaining; the overlap checker reported 1 finding. VLAN page reported
    `Planned 5 VLANs and 5 DHCP scopes`, 305 pool addresses, and no overlap or
    DHCP violations.
  - Visual appearance was not inspected in a browser; see Known issues.

## Test evidence (Phase 3b)
- Commands:
  - `& ".venv\Scripts\python.exe" -m pytest -q`
  - `& ".venv\Scripts\python.exe" -m ruff check .`
- Results:
  - `204 passed in 1.83s` (188 from Phase 3a + 16 new)
  - `All checks passed!`
- Headless app verification (port 8552, `--server.enableAgentApi true`):
  - `/_stcore/health`: HTTP 200; root page: HTTP 200.
  - Agent API: navigated to Topology Editor and generated a star with 0
    exceptions; metrics `Devices 7`, `Links 6`, `Components 1`,
    `Isolated devices 0`.
  - Server log contained no warnings beyond PowerShell's stderr formatting of
    Streamlit's startup line.

## Test evidence (Phase 3a)
- Commands:
  - `& ".venv\Scripts\python.exe" -m pytest tests/ -q`
  - `& ".venv\Scripts\python.exe" -m ruff check .`
- Results:
  - `188 passed in 1.28s` (114 existing + 74 new topology tests)
  - `All checks passed!`
- Known failures: none.

## Known issues
- Environment uses Python 3.11.15; the blueprint targets Python 3.12. All
  checks pass on 3.11.15. Non-blocking; revisit if a 3.12-only feature is
  required.
- `MAX_EDGES=2000` bounds a full mesh at 63 nodes (2016 links would exceed
  the limit); oversized mesh requests fail cleanly by design. A full
  spine-leaf mesh is bounded similarly (for example 50 spines x 41 leaves).
- Name collisions are only detected for ids; generator-supplied custom
  prefixes/hub ids that collide with generated ids fail through `Topology`
  validation, not a generator-specific error.
- Visual appearance of the editor (colors, legend placement, Plotly rendering
  in a browser) was not inspected manually. Verified only through AppTest, the
  Streamlit agent API, and HTTP status checks; no browser screenshot was
  taken.
- The table editors use a form plus an Apply button. A rejected edit advances
  the widget key version and reruns, so the rejected rows disappear; the model
  itself is never changed. An error notice is queued and shown after the rerun.
- Phase 4 pages were verified through AppTest, the Streamlit agent API, and
  HTTP status checks only. Colors, spacing, progress-bar rendering, table
  sizing, and CSV download behaviour were not inspected in a real browser; no
  screenshots were taken.
- The VLSM allocator deliberately never produces point-to-point prefixes
  (`/31`, `/32`, `/127`, `/128`); use the CIDR calculator or DHCP planner for
  those. This avoids allocating a block with no assignable host address.
- The VLAN/DHCP page's "Reserved addresses per subnet" input accepts values
  below the engine minimum (IPv4 needs at least 2); such a submission is
  rejected by the engine with an inline error rather than clamped silently.
- DHCP planning requires at least one assignable address after reserved
  addresses, so `/32` (IPv4) and `/128` (IPv6) subnets raise a clear error
  instead of producing an empty scope.
- Phase 5 routing and analytics pages were verified through AppTest, the
  Streamlit agent API, and HTTP status checks only. A real-browser pass
  (Plotly path highlighting, horizontal bar-chart rendering, table sizing,
  CSV download behaviour) was not performed; no screenshots were taken.
- Structural analysis ignores link direction and collapses parallel links by
  design. Directed reachability questions belong to the routing page; the
  analytics page intentionally reports physical connectivity.
- Edge-disjoint path counts model each physical link as one capacity unit, so
  they indicate path-count redundancy, not available bandwidth or failure
  independence beyond single-link removal.
- Betweenness centrality uses `Link.cost`, while degree and diameter are
  hop-based. The definitions expander states this, but mixed-weight topologies
  can make centrality rankings differ from hop-count intuition.
- The digital twin is a software model only. It is never connected to real
  equipment, so operational state is user-modeled and can drift from reality.
- Twin snapshots live in Streamlit session state, bounded by `MAX_SNAPSHOTS`
  and `MAX_TWIN_SNAPSHOT_BYTES`; they are not persisted across sessions.
- A topology change preserves addressing/VLAN/DHCP/demand/state references.
  Stale references are surfaced as findings (Topology Editor and Digital Twin
  pages), not pruned automatically; routing and analytics ignore stale state
  but warn about it.
- VLSM allocations are stored as standalone subnets in the twin only when they
  do not overlap existing VLAN subnets; a conflict is reported and the existing
  plan is left unchanged.
- The Digital Twin page was verified through AppTest only; the state data
  editors, snapshot selectors, and comparison tables were not inspected in a
  real browser.
- Simulation v1 is an abstract flow model: single lowest-cost path per demand,
  no ECMP, no queueing, and no packet-level effects. Capacity affects reported
  utilization but never path selection, so overloaded links stay selected.
  Latency exists only as an explicit per-link delay assumption.
- The Simulation Lab page was verified through AppTest only. The Plotly
  topology, colored link table, threshold lines, and browser download behavior
  were not inspected in a real browser; no screenshots were taken.
- Scenario history is session-only, bounded by `MAX_SCENARIOS`, and deliberately
  stores no timestamp or elapsed time. Clearing the session loses the history.
- Expansion scenarios are entered as validated JSON rather than a guided table;
  malformed or oversized expansion data is rejected by the scenario engine.
- The Settings page and structured form were verified through AppTest only; the
  page layout, password-field behaviour, progress bars, and trace download were
  not inspected in a real browser.
- No live Groq request has been made. The connection test is covered only with
  injected fake providers, so real endpoint reachability, model availability,
  and provider-reported token usage remain unverified against the live service.
- A session-entered API key lives in Streamlit session state for the browser
  tab. It is never persisted by the application, but it is visible to the
  running Streamlit process and to browser session state; configure
  environment variables or Streamlit secrets for shared deployments.
- The structured form models one organization with one site and a bounded
  department list. Multi-site entry, device/link requirements, and explicitly
  requested topologies are not exposed by the form yet; the deterministic
  policy derives those from the modeled assumptions.
- Report consistency masks IPv4/IPv6 addresses and identifier-embedded digits
  before matching numeric tokens. A fabricated quantity disguised as part of
  an identifier (for example `link999`) is therefore not flagged as an orphan
  number. Standalone quantities in prose, key/value items, tables, notes, and
  AI text are checked.
- The report builder recomputes routing and structural analysis from the
  stored twin at build time; it does not reuse a page's cached result. Values
  therefore match the current twin revision, but a page showing an older
  snapshot can display different numbers until it is rerun.
- PDF rendering uses ReportLab's built-in Latin fonts. Characters outside
  Latin are replaced with `?` and a visible notice points to the Markdown or
  JSON export. Arabic shaping, bidirectional text, and embedded Unicode fonts
  are not implemented, so an Arabic PDF is legible only as a placeholder
  layout.
- PDF verification is structural, not visual: tests search the uncompressed
  byte stream for text and count page objects. Glyph overlap, row widths,
  table page-break quality, and rendered Arabic placeholders were not inspected
  in a viewer.
- CSV exports contain bounded table rows only; a truncated source table keeps
  the "showing first N of M" note in the bundle README rather than adding a
  synthetic row to the CSV. Values are strings exactly as rendered in the
  report, so downstream numeric parsing depends on the displayed precision.
- Configuration templates are vendor-neutral design intent. They are not
  device-applied, not vendor-complete, and not syntax-checked against any
  device operating system.
- The Reports page does not request optional AI-written prose. The explanation
  service exists and is tested, but the page deliberately keeps every section
  engine-derived and never calls a provider.
- Source selection preselects the latest retained workflow, scenario run, and
  optimization run. The report uses exactly the selected run objects; a run
  created against an older twin revision is still offered, and its recorded
  twin versions make that visible in the provenance columns.
- Section selection filters the report body and section list. The source-value
  appendix and the JSON registry still contain every value computed for the
  build, so provenance remains complete for the whole document even when some
  sections are hidden.
- Export bytes are cached by canonical twin content, selected section ids, and
  source fingerprints, so a rerun no longer rebuilds the PDF or other bundles.
  A changed twin or source selection invalidates the cache.
- Page verification is AppTest-only. Widget placement, table widths, the
  collapsed appendix, and real browser download behaviour were not inspected
  visually.
- Phase 12 verification is AppTest- and service-test-only. Browser rendering,
  responsive behavior at narrow widths, and the PDF viewer were not inspected
  manually; no screenshots were taken.
- The Phase 12 read-only Capacity Planning inventory was replaced in Phase 13c
  by the four-tab forecasting and capacity workflow. Browser rendering and real
  CSV upload were not verified outside AppTest.
- The profiler's flagged search rows are user-triggered searches bounded by
  `MAX_OPTIMIZATION_RUNTIME_SECONDS=60`, not page-background work. Tracemalloc
  measures Python allocations, not total process RSS, and adds time overhead.
- Cached reports keep one prepared timestamp per twin fingerprint (at most four
  fingerprints in the session map). A later twin revision changes the cache key
  and therefore the timestamp.

## Phase 13a delivered - forecasting engine
Location: `forecasting/` (NumPy only; no ML, no new dependencies, no network I/O).

- `models.py`: frozen typed schemas for `Observation`, `TimeSeries`,
  `ParseResult`, `Finding`, `FillReport`, `HistorySummary`, `ModelEvaluation`,
  `ForecastPoint`, `ForecastResult`, and `ForecastRun`; provenance is either
  `user_supplied` or `synthetic` and is carried into every result.
- `parsing.py`: strict `timestamp,series_id,value,unit` CSV reader. Unsorted rows,
  duplicate timestamps within a series, non-numeric/negative values, bad units,
  mixed units within a series, missing/unknown columns, empty input, and too-short
  series produce typed `Finding` records (no exceptions on bad input). Gap policies
  are `reject`, `linear interpolate`, and `carry forward`; leading/trailing gaps
  remain unfilled and every fill is reported, never silent.
- `synthetic.py`: deterministic NumPy PCG64 generator seeded by the caller. The
  formula (base × (1+growth)^step + seasonality·sin + normal noise, clamped at
  zero, rounded to 6 decimals) is documented in the docstring and surfaced in
  `SyntheticSpec.assumptions()`. Every generated series is labeled `SYNTHETIC`.
- `forecast.py`: naive, moving average, OLS linear trend, Holt additive with a
  documented `{0.05..0.95}` grid, and seasonal naive (requires at least two full
  periods). One chronological holdout (last 20%, minimum 2 points) is used for all
  models; MAE is primary, the naive baseline is always computed and reported, and
  a non-naive model wins only on strictly lower MAE with a documented simpler-model
  tie-break. Approximate residual intervals are `±1.96·σ·√h`, lower-clamped at zero.
  Horizons are refused above `MAX_FORECAST_HORIZON_RATIO` (0.5) or
  `MAX_FORECAST_HORIZON_STEPS` (24), and forecasts under `MIN_FORECAST_POINTS` (8)
  are refused with typed `ForecastLimitError`/`ForecastValidationError`.
- `export.py`: byte-stable CSV/JSON export of results, including provenance,
  assumptions, interval caveat, and naive baseline note.
- `config/limits.py`: added bounded forecast limits (`MIN_FORECAST_POINTS`,
  `MAX_FORECAST_POINTS`, `MAX_FORECAST_SERIES`, `MAX_FORECAST_HORIZON_RATIO`,
  `MAX_FORECAST_HORIZON_STEPS`) plus reserved Phase 13 capacity limits.
- `core/exceptions`: added `ForecastError`, `ForecastValidationError`,
  `ForecastLimitError`, `CapacityError`, `CapacityValidationError`,
  `CapacityLimitError`.
- Tests: `tests/unit/forecasting` (18 tests) cover hand-computed naive/linear/Holt
  and sMAPE values, chronological selection with naive retained, strict parsing
  findings and gap policies, synthetic determinism/labels, horizon refusal, and
  deterministic exports.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q tests/unit/forecasting`
  -> `18 passed in 0.71s`;
  `& ".venv\Scripts\python.exe" -m ruff check forecasting tests/unit/forecasting
  config/limits.py core/exceptions/__init__.py` -> `All checks passed!`.

## Phase 13b delivered - capacity projection and evaluation
Location: `capacity/` (reuses `forecasting`, `simulation.evaluator`, and
`optimization.models.CostModel`; no new dependencies).

- `models.py`: typed `DemandMapping`, projected-demand points, `Crossing`,
  `Bottleneck`, `UpgradeRecommendation`, `CapacityGap`, `CapacityBounds`,
  `CapacityStopReason`, and `CapacityRun`. Provenance and the modeling caveat
  travel into every run.
- `demand.py`: maps `series_id` to an existing twin demand name. User-count
  series require a user-supplied `per_user_mbps`; Mbps series use the forecast
  value directly. Unmapped series, unknown demand names, missing assumptions,
  short forecasts, and unused assumptions are reported as typed findings. No
  demand, endpoint, or historical measurement is invented.
- `engine.py`: builds one scenario twin per projected step by copying the
  baseline and replacing only mapped demand bandwidths; evaluates each copy with
  `simulation.evaluator.evaluate`. The baseline twin is never mutated and is
  verified by fingerprint in tests. Produces first-step crossings for warning,
  critical, and overloaded bands, ranks bottlenecks by peak utilization, reports
  signed horizon-end headroom, and selects the smallest configured tier whose
  horizon-end utilization is strictly below the warning threshold. Cost deltas
  are proxies from `CostModel`; links with no sufficient tier are reported as
  gaps for the Optimization Center.
- Bounds: at most `MAX_CAPACITY_EVALUATIONS=240` evaluations,
  `MAX_CAPACITY_HORIZON_STEPS=12` projected steps, and
  `MAX_CAPACITY_RUNTIME_SECONDS=30.0`. Runs record `completed`,
  `runtime_limit`, `evaluation_limit`, `no_projection`, or
  `incomplete_projection` as a typed stop reason; oversized requests raise
  `CapacityLimitError`.
- Tests: `tests/unit/capacity` (12 tests) cover hand-computed 50% baseline to
  150% projected utilization, crossing bands, unchanged twin fingerprint,
  tier/cost delta hand values, insufficient-tier gaps, evaluation and runtime
  stop reasons, horizon clipping, mapping findings, synthetic labels, and JSON
  provenance.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q tests/unit/capacity`
  -> `12 passed in 0.52s`;
  `& ".venv\Scripts\python.exe" -m ruff check capacity tests/unit/capacity`
  -> `All checks passed!`.

## Phase 13c delivered - UI and report integration
Location: `ui/pages/capacity_planning.py`, `ui/pages/reports.py`, `ui/cache.py`,
`ui/state.py`, `services/reporting/builder.py`, and `capacity/history.py`.

- The Capacity Planning page now has four tabs: Data, Forecast, Capacity, and
  Downloads. Data accepts strict `timestamp,series_id,value,unit` CSV rows or a
  deterministic `SYNTHETIC` generator; Forecast runs the NumPy-only baselines;
  Capacity maps forecast series to existing twin demands, applies a stated
  `per_user_mbps` assumption where needed, and evaluates bounded projected
  copies of the baseline twin; Downloads exports series, forecast points, run,
  bottlenecks, and upgrades in memory.
- The visible model-scope note is exactly: "Modeled projections from supplied or
  synthetic data; not measurements or guarantees." Forecast provenance is shown
  in tables and carried into the capacity run and report.
- `services/reporting/builder.py` adds an optional `capacity` section between
  `simulation` and `optimization`. It records the source twin fingerprint, data
  label, selected models, stop reason, projected steps, mapped demands,
  congestion crossings, bottlenecks, tier upgrades, and proxy cost deltas. All
  numbers are registered in the sourced-value appendix with step, tool, and twin
  version. No capacity input means the section stays `not_run` and points to the
  Capacity Planning page.
- `ui/state.py` adds bounded session storage for capacity series, the last
  forecast run, and `CapacityHistory` (`MAX_CAPACITY_RUNS=20`). `ui/cache.py`
  adds content-keyed `cached_forecast_run`, `cached_capacity_run`,
  `capacity_series_payload`, and `capacity_source_payload`, and extends
  `cached_report` with an optional `capacity_payload`. The baseline twin is not
  mutated by any of these paths.
- Additive schema/API changes: `ReportSources.capacity_run`, section id
  `capacity`, `ProjectedDemand.model`, `CapacityHistory`, the capacity state
  keys, and the new cache function parameters. No existing field was removed or
  renamed.
- Tests: AppTest coverage for the four-tab workflow, synthetic labeling,
  forecast/capacity execution, download keys, and report source selection;
  service tests for capacity provenance, consistency, and tampered-number
  detection; cache tests for forecast/capacity reuse and capacity-backed
  reports; bounded history tests.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `843 passed in
  22.16s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering, real-network CSV upload, and live device
  verification were not performed.

## Phase 14.0 delivered - housekeeping and report source freshness
Location: root blueprint, `AI_INSTRUCTIONS.md`, `docs/CHANGELOG.md`,
`config/limits.py`, `services/reporting/builder.py`, `ui/state.py`,
`ui/cache.py`, `ui/pages/reports.py`, `ui/pages/optimization_center.py`,
`optimization/models.py`, and new/updated tests.

- The owner decision is recorded: 15 phases; Phase 14 is design-time security
  analysis only; design-time security is in scope while live scanning, probing,
  pentesting, SOC operations, vulnerability database lookups, exploit content,
  attack steps, and device access remain excluded. The owner explicitly approved
  the 14a security models and optional twin field.
- Blueprint section 2 now includes design-time security analysis, module 3.11,
  the Security Agent in section 4, the Security Analysis page in section 7, and
  the 13/14/15 roadmap. `AI_INSTRUCTIONS.md` mirrors the scope and roadmap.
- Reports now show a warning note when the selected simulation or capacity run's
  source fingerprint differs from the current twin. Optimization runs have no
  persisted fingerprint, so the Optimization Center records the source twin
  fingerprint in a bounded session map when the run is created; reports pass it
  through `ReportSources.optimization_source_fingerprint`. No run schema changed.
- Free-tier defaults: `MAX_SCENARIOS` is 20; optimization default runtime is 20
  seconds; the hard runtime cap remains 60 seconds so users can raise it.
- Changed existing assertions: none. No existing test pinned 50 scenarios or a
  30/60 default. The test helper literal 30 was replaced with the new default
  constant, and new assertions pin 20 scenarios, 20-second default, and 60-second
  cap.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `847 passed in
  20.74s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering and live LLM behavior were not verified.

## Phase 14a delivered - security models and backward-compatible twin field
Location: `security/`, `digital_twin/models.py`, `digital_twin/serialization.py`,
`digital_twin/validation.py`, `digital_twin/__init__.py`,
`simulation/evaluator.py`, `config/limits.py`, `tests/unit/security/`, and
updated twin/serialization/validation/design-health tests.

- Pure models: frozen `Zone`, `Service`, `FirewallRule`, and `SecurityModel`
  with duplicate/order/range validation and bounds `MAX_ZONES=32`,
  `MAX_FIREWALL_RULES=128`, `MAX_SERVICES=32`, and
  `MAX_SECURITY_ASSUMPTIONS=50`. Every operation output must carry
  `SECURITY_DISCLAIMER`.
- Default derivation is deterministic over VLAN text and device type/role.
  Keyword priority is fixed; unmatched members remain unassigned; the default
  action is deny; guest/IoT boundary deny rules are emitted only where both
  source and destination zones exist.
- All security operations return a NEW twin, revalidate after `model_copy`, and
  reject removal of a zone or service still referenced by a rule. There is no
  network I/O, device access, vulnerability lookup, or dynamic execution.
- Compatibility: `TWIN_SCHEMA_VERSION=2`, supported versions `(1, 2)`, optional
  `security=None`, and `canonical_payload()` omission of absent security. Legacy
  JSON and fingerprint `4212909d2624a026229027d4266267906ae6a040df00678bf200d0430c2d802c`
  remain unchanged; schema 3 is rejected.
- Changed existing assertions (disclosed): the digital-twin validation test that
  used literal schema 2 as an unsupported future version was renamed and now
  checks schema 1 as supported and `TWIN_SCHEMA_VERSION + 1` as unsupported. The
  design-health `_schema_twin()` fixture was changed from literal 2 to
  `TWIN_SCHEMA_VERSION + 1`. Both still assert the same finding behavior.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `866 passed in
  20.29s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering and live LLM behavior were not verified.

## Phase 14b delivered - deterministic security engine
Location: `security/models.py`, `security/policy.py`, `security/catalog.py`,
`security/risk.py`, `security/remediation.py`, `security/templates.py`,
`security/engine.py`, `security/__init__.py`, and `tests/unit/security/`.

- Policy is stateless first-match with an explicit default. Flow checks combine
  deterministic routing and policy; no-route and policy-denied are distinct,
  typed outcomes. Intra-zone traffic bypasses inter-zone rules, and disabled
  rules are ignored.
- The fixed catalog has nine rules: `SEC-DW-001` flat network (error),
  `SEC-DW-002` no management zone (warning), `SEC-DW-003` public server outside
  DMZ (error), `SEC-DW-004` user reaches management/server without rule (error),
  `SEC-DW-005` guest/IoT reaches internal zones (critical), `SEC-DW-006` single
  security boundary/SPOF (warning), `SEC-DW-007` oversized subnet (warning),
  `SEC-DW-008` devices without a zone (warning), and `SEC-DW-009` missing
  inter-department segmentation for criticality >= 4 (error).
- Risk is hand-checkable: `severity count x weight` plus a 2-point bonus when
  the default action is allow. Weights are info 0, warning 1, error 4, critical
  8; score bands are 0 low, 1-3 moderate, 4-7 elevated, 8+ high.
- Proposals are inert deny rules until explicit ids are accepted into a NEW twin.
  Templates are vendor-neutral data records beginning with
  `TEMPLATE - not applied to any device`; no commands or device syntax are
  generated. All outputs carry the exact disclaimer.
- Changed existing assertions: none. 14b added new tests and design fixtures.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `904 passed in
  23.74s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering and live LLM behavior were not verified. The
  catalog is a modeling aid, not an audit standard.

## Phase 14c delivered - Security Agent and integration
Location: `agents/security_agent.py`, `agents/tools.py`, `agents/critic.py`,
`agents/orchestrator.py`, `agents/network_agents.py`, `agents/documentation.py`,
`agents/__init__.py`, `config/limits.py`, `services/reporting/builder.py`,
`services/validation/`, and new agent/service tests.

- The Security Agent has exactly one allowlisted tool, `security_analysis`.
  Verdict, risk, findings, and posture come from the deterministic engine. An
  optional LLM explanation is labelled as non-authoritative; numeric tokens that
  are absent from the assessment, out-of-scope terms, overlong text, and provider
  failures cannot change any engineering result. The agent has no network I/O
  and declines automatic re-plans.
- The default workflow remains 11 steps and has no security result. Passing
  `include_security=True` inserts one offline security step after re-validation
  and before the critic, making 12 steps. The critic re-runs the security tool,
  maps `SEC-*`/`POLICY-*` codes to `security`, emits a nonblocking
  `security_high_risk` warning in the high band, and rejects blocking security
  findings. The Security Agent's `replan()` returns `None`, so a security
  rejection stops the workflow instead of silently applying a proposed rule.
- Reports include a `security` section between `optimization` and `assumptions`
  with the exact disclaimer, provenance, finding and flow tables, and explicit
  inert-proposal/vendor-neutral-template notes. Documentation and workflow
  reports include the same section when the optional step runs. Design health
  gained a basic `security` category for supplied findings; expensive checks
  remain opt-in.
- Changed existing assertions (disclosed): the critic allowlist test now includes
  `security_analysis`; the registry-name test asserts the new tool; report
  `SECTION_IDS` includes `security`; and the not-run pointer table includes
  `("security", "Security Analysis")`. No assertion was weakened.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `925 passed in
  22.03s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering and live LLM behavior were not verified. The
  catalog is a modeling aid, not an audit standard.

## Phase 14d delivered - Security Analysis UI
Location: `ui/pages/security_analysis.py`, `app.py`, `ui/state.py`, `ui/cache.py`,
and new/updated UI tests.

- Security Analysis is the 15th sidebar page, placed immediately after Capacity
  Planning. With no twin it shows the standard twin-required empty state; the
  exact disclaimer is shown before the empty state and on every page load.
- The five tabs are Zones, Policy, Flow check, Findings, and Templates. Zones and
  Policy use shared UI components and versioned `st.data_editor` keys. Rejected
  edits bump the relevant key, queue a notice, and rerun from the stored model;
  zone ids, service names, and rule ids are immutable, and every rule reference
  is validated before storage.
- Flow checks are kept behind bounded, typed session accessors capped at
  `MAX_SECURITY_FLOW_CHECKS`. `cached_security_analysis` is content-keyed by the
  canonical twin, security model, and flow payloads, so identical reruns reuse
  the assessment and any edit invalidates it.
- Findings display visible risk arithmetic, typed design/policy findings, the
  fixed catalog, and inert proposals. A proposal changes the twin only after the
  user selects its id and confirms explicit acceptance. Templates are
  vendor-neutral, data-only downloads and contain no device syntax or commands.
- Changed existing assertions (disclosed): navigation now asserts 15 pages and
  the Security Analysis position; the UI cache test file adds the security
  cache helper imports and one cache test. No assertion was weakened.
- Evidence: `& ".venv\Scripts\python.exe" -m pytest -q` -> `938 passed in
  22.97s`; `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks
  passed!`. Browser rendering and live LLM behavior were not verified. The
  catalog is a modeling aid, not an audit standard.

## Phase 15a delivered - release acceptance verification and gap-closing tests
Commit: `7cb4995`

- Added 18 acceptance tests in `tests/unit/release/test_phase15_acceptance.py`.
  They verify IP plan overlap/duplicate checks, valid graph walks across four
  topology generators, failure exclusion, reproducible simulation and
  optimization, hard-constraint behavior, invalid LLM rejection, report values
  against computed engines, all 15 pages with no API key, and the security
  criticality decision.
- Added the optional `smoke` marker in `pytest.ini`.
- Decision recorded: asset/zone criticality is a gate for `SEC-DW-009`, not a
  numeric risk-formula term. Implemented in `security/risk.py`.
- Evidence: baseline before Phase 15 `938 passed in 26.66s`; after 15a
  `& ".venv\Scripts\python.exe" -m pytest -q` -> `955 passed in 25.65s`;
  `& ".venv\Scripts\python.exe" -m pytest -q -m smoke` -> `11 passed, 944 deselected in 4.49s`;
  `& ".venv\Scripts\python.exe" -m ruff check .` -> `All checks passed!`.

## Phase 15b delivered - adversarial hardening and dependency audit
Commit: `bf4c220`

- Added guarded JSON/CSV/text/identifier parsing (`core/inputs.py`) and
  spreadsheet-formula neutralization (`core/csv_safe.py`), wired through all
  untrusted import/export paths.
- Added typed errors and compiled caps; see `docs/RUNTIME_LIMITS.md`.
- Added 14 hardening tests: payload/depth/width/identifier bounds, malformed and
  non-finite values, duplicate keys, hidden controls, CSV findings, formula
  neutralization, prompt-injection tool allowlisting, secret containment in
  logs/traces/reports/exports/session dumps, no runtime dynamic execution or
  disk writes, gitignore/secrets safety, and exact dependency pins.
- At the release tag, pinned ten direct packages in `requirements.txt` and the
  transitive `pyarrow==23.0.1` wheel in `constraints.txt`. No direct runtime
  dependency was added. The vulnerable `17.0.0` pin and the locally blocked
  `26.0.1` wheel were replaced after auditing and clean-install checks. This
  layout was later changed to inline pins; see the post-release section below.
- Secret scan: tree and full history contain no live secret patterns; no
  tracked `.env`, `.streamlit/secrets.toml`, or key/certificate files.
- Evidence: clean Python 3.11 venv -> `970 passed in 30.23s` and
  `All checks passed!`; `pip-audit -r requirements.txt --progress-spinner off`
  -> `No known vulnerabilities found`.

## Phase 15c delivered - deployment artifacts and headless evidence
Commit: `50008ab`

- `.streamlit/config.toml` sets `headless = true`, `maxUploadSize = 2`, and
  `gatherUsageStats = false`. The 2 MB widget is an outer guard; guarded parsers
  still enforce smaller per-format caps.
- Added `.github/workflows/ci.yml` with a Python 3.11/3.12 matrix for install,
  lint, full suite, smoke subset, and deployment-config assertion. Remote GitHub
  Actions execution was not performed.
- Added Settings > Release limitations and About-menu scope text identifying
  `v1.0.0-rc1`.
- Added 5 deployment tests in `tests/unit/release/test_phase15_deployment.py`.
- Headless evidence from the clean Python 3.11 venv with all `GROQ_*` variables
  removed: `health: ok`, `agent status: ready`, root title `Dashboard`,
  `exceptions: 0`, `actions: 1`; Streamlit log showed only startup lines.
- Profile rerun: peak traced allocation 8.7 MiB; no-memory maximum optimization
  searches are bounded by the 60 s hard cap and flagged by the script's 5 s
  threshold.
- Final local evidence: `pytest -q` -> `975 passed in 33.79s`;
  `pytest -q -m smoke` -> `12 passed, 963 deselected in 8.55s`;
  `ruff check .` -> `All checks passed!`; clean Python 3.11 -> `975 passed in 38.79s`;
  clean Python 3.12 -> `975 passed in 44.79s`, both with `All checks passed!`.

## Phase 15d delivered - documentation, audit, and release tag
- Added the full release documentation set: `README.md`, `docs/ARCHITECTURE.md`,
  `docs/API_CONTRACTS.md`, `docs/AGENT_SPECIFICATIONS.md`,
  `docs/TEST_STRATEGY.md`, `docs/DEPLOYMENT.md`, `docs/RELEASE_AUDIT.md`,
  `docs/ROADMAP.md`, and `KNOWN_LIMITATIONS.md`; updated `docs/CHANGELOG.md`.
- `docs/RELEASE_AUDIT.md` contains the criterion-by-criterion
  `criterion | evidence | status` table for Blueprint §11 and §16, plus §15 exit
  criteria and §10 supporting constraints. Deployment criteria are marked
  `UNVERIFIED (remote)` rather than assumed.
- Corrected the 15c upload-comment wording without changing the tested value:
  the 2 MB widget is an outer guard, not a claim of being below the 1 MB CSV
  parser cap.
- Created annotated tag `v1.0.0-rc1` pointing at this release commit.
- No new feature, public schema change, runtime dependency, security-scanning
  functionality, or license decision was added in Phase 15.

## Post-release dependency layout change
- `requirements.txt` now contains eleven inline pins, including
  `pyarrow==23.0.1`; `constraints.txt` was removed. This is a deployment-packaging
  change only. `pyarrow` is already required by Streamlit, so no new runtime
  dependency was introduced.
- The release hardening test was updated from ten packages plus a constraints
  file to eleven inline packages and asserts that no constraints file exists.
- `README.md`, `docs/DEPLOYMENT.md`, `docs/TEST_STRATEGY.md`,
  `KNOWN_LIMITATIONS.md`, and `docs/CHANGELOG.md` were updated to match.
- The annotated tags `v1.0.0-rc1` and `v1.0.0` still point to the release commit
  `b1507f9`; this packaging change is a subsequent commit on `main`.
- Evidence: `pytest -q -m smoke` and full `pytest -q` passed after the change;
  `ruff check .` -> `All checks passed!`.

## Next task
- Owner action: follow `docs/DEPLOYMENT.md` to deploy from `main` on Streamlit
  Community Cloud Free with Python 3.12 and no secrets.
- Owner action: verify the deployed app's 15 pages, no-key state, in-app
  limitations, and clean logs; optionally add a Groq secret through Community
  Cloud App settings.
- Remaining unverified items: real browser, deployed free tier, live Groq,
  PDF visual layout, and remote GitHub Actions execution.
