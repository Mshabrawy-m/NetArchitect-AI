# Roadmap

This roadmap records the state of `v1.0.0-rc1` and candidate follow-up work. Nothing below changes the release scope, and no dates or commitments are implied.

## Current state

- Phase 15 release preparation is complete locally as `v1.0.0-rc1`.
- Full suite, lint, smoke subset, clean Python 3.11/3.12 installs, dependency audit, local headless startup, and profile rerun all passed.
- The annotated tag is created locally. Pushing the branch/tag and deploying to Streamlit Community Cloud remain owner actions.
- No new features, public schema changes, runtime dependencies, or license decision were added in Phase 15.

## Immediate owner verification

1. Push `feature/phase15-release` and `v1.0.0-rc1` if they should be available on GitHub.
2. Follow `docs/DEPLOYMENT.md` to deploy from `feature/phase15-release` (or `main` after merge) with Python 3.12 and no secrets.
3. Confirm the 15-page navigation, no-key state, in-app limitations, and clean logs.
4. Optionally add a Groq secret through Community Cloud App settings and repeat the no-leak checks.
5. Merge to `main` when the deployed RC is accepted.

## Post-RC verification candidates

- Real-browser smoke pass (Chromium/Firefox) with screenshots of all 15 pages and responsive layouts.
- Deployed Community Cloud Free measurement of cold start, memory, and maximum-size topology/optimization behavior.
- One live Groq request with a disposable key to verify current model names and provider availability.
- Visual PDF inspection, including fonts and non-Latin text, if those exports are used in evaluation.
- Remote GitHub Actions run on both Python 3.11 and 3.12 to confirm `.github/workflows/ci.yml` behaves as specified.

## Future product candidates (not in this release)

- Optional persistence layer with explicit user consent and privacy design.
- Expanded what-if models such as queueing, ECMP, and packet-level behavior, clearly labeled if added.
- More optimization algorithms with baseline comparison and the same hard-constraint contract.
- Additional security catalogs and provider-neutral templates, still offline and design-time only.
- Accessibility and theme refinements based on real-browser findings.
- Owner decision on a license before public distribution.

## Explicitly out of scope

- Device SSH/API access, live scanning, probing, or penetration testing.
- Application deployment to servers, containers, or always-on workers for this release.
- Mandatory paid APIs or databases.
- Unbounded simulations, searches, or session history.
- Changing computed engineering values from LLM prose.
