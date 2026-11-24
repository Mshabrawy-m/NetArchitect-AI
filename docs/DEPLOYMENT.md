# Deployment - Streamlit Community Cloud Free

This document contains the exact manual steps for the repository owner. The release candidate was prepared and verified locally; **no Community Cloud deployment was performed by the agent**.

## Preconditions

1. The GitHub account used for deployment must have administrator permission for the repository. Streamlit's GitHub OAuth scope requires this even for read-only app access.
2. Push the release ref you want to deploy. Streamlit selects a **branch**, not a tag:

   ```powershell
   git push origin feature/phase15-release
   git push origin v1.0.0-rc1
   ```

   If you merge the release into `main` first, deploy from `main` instead and push `main`.

3. Repository coordinates used below:

   - Owner: `Mshabrawy-m`
   - Repository: `NetArchitect-AI`
   - Branch: `feature/phase15-release` (or `main` after merge)
   - Entrypoint: `app.py`

4. Required files are already at the repository root:

   - `app.py`
   - `requirements.txt` (nine inline pins, including `pyarrow==23.0.1`; Cloud does not install `requirements-dev.txt`)
   - `.streamlit/config.toml`

   No `packages.txt` is needed. `.streamlit/secrets.toml` must **not** be committed.

## Exact manual steps

1. Sign in at <https://share.streamlit.io> with GitHub.
2. In the upper-right corner, click **Create app**.
3. When asked **Do you already have an app?**, click **Yup, I have an app**.
4. Fill in the app coordinates:
   - **Repository**: `Mshabrawy-m/NetArchitect-AI`
   - **Branch**: `feature/phase15-release` (or `main` after merge)
   - **Main file path**: `app.py`
5. Optional: set **App URL** to a unique subdomain. Leave blank to accept the generated `*.streamlit.app` URL.
   - Because the branch is not `main`, the generated URL includes the branch name.
6. Click **Advanced settings**.
7. Set **Python version** to `3.12`. Version 3.11 was also verified locally. Choose this now: Community Cloud does not allow changing Python version after deployment without deleting and redeploying the app.
8. Leave the **Secrets** field empty for the no-key release. Core engineering, the structured workflow, and all 15 pages work without a provider key.
9. Click **Save**.
10. Click **Deploy**.
11. Wait for the build and launch. A first install can take several minutes because the pinned scientific packages are large.
12. When the app opens, verify:
   - The root page title is **Dashboard**.
   - The sidebar says **All 15 pages are available.**
   - **Settings** shows `API key configured No` and the **Release limitations** section.
   - The **About** menu identifies `v1.0.0-rc1` and the design-time scope.
   - No exception banner appears and the Cloud logs show no traceback.

## Optional Groq secret

Add this only after the no-key deployment is healthy.

1. In your Streamlit workspace, open the deployed app's **settings**.
2. Open the **Secrets** editor.
3. Paste top-level keys, for example:

   ```toml
   GROQ_API_KEY = "replace-with-your-key"
   GROQ_MODEL = "your-current-groq-model"
   GROQ_BASE_URL = "https://api.groq.com/openai/v1"
   ```

4. Click **Save**. Streamlit restarts the app.
5. Confirm Settings now reports that a key is configured. Do not print, log, export, or commit the key.

`config/settings.py` reads these exact top-level names from `st.secrets` or environment variables. Secrets take precedence over environment variables. The app has no key input; the key is never entered in the UI. Model names are configurable because providers retire models; no specific model is guaranteed by this release.

## Configuration applied by the repository

`.streamlit/config.toml` sets:

- `server.headless = true`
- `server.maxUploadSize = 2` (2 MB outer upload guard)
- `browser.gatherUsageStats = false`
- light theme colors

In-app parsers still enforce the smaller per-format caps, including 1,000,000 bytes for CSV and 2,000,000 bytes for JSON. See `docs/RUNTIME_LIMITS.md`.

## Development verification (not part of Cloud install)

CI and developers install `requirements-dev.txt`; Cloud installs only
`requirements.txt`. To prove the runtime file is sufficient without pytest:

```bash
python -m venv .verify-runtime
. .verify-runtime/bin/activate
python -m pip install -r requirements.txt
python scripts/verify_runtime_only.py
```

The script starts a headless Streamlit server, checks `/_stcore/health` and the
root page, renders all 15 pages with `AppTest`, and refuses to run if pytest is
installed. It uses stdlib HTTP only and needs no test dependencies.

## First CI push on Linux - owner checks

GitHub Actions was **not run remotely** from this workspace. After pushing
`feature/v2-tech`, the owner must check:

1. `Tests and lint - Python 3.11` and `3.12` are green (dev requirements, ruff,
   full tests, smoke tests, config assertion).
2. `Runtime-only install and Linux memory gate` is green; its log shows health
   `ok`, 15 pages rendered, and VmRSS below 450 MB.
3. `Dependency audit (throwaway venv)` reports no known vulnerabilities.
4. The Dependabot configuration is accepted with weekly pip and github-actions
   updates, and no workflow step refers to a secret.

## Verification matrix

| Check | Expected result |
|---|---|
| Root page | `Dashboard` title, no exception |
| Navigation | 15 entries ending with `Reports & Documentation`, `Settings` |
| No-key state | `API key configured No`, structured requirements form in AI Designer |
| Optional-key state | `API key configured Yes`; no key characters visible anywhere |
| Imports | CSV/JSON imports at limits succeed; oversized or adversarial files show typed errors |
| Reports | Downloads are produced in memory; no local file requirement |
| Logs | No traceback and no secret material |

## Update and rollback

- Code changes on the selected branch are picked up automatically by Community Cloud. Dependency changes may take a few minutes to install.
- To roll back, point the app at a previously verified branch/commit in its GitHub coordinates, or redeploy from `main` after restoring the known-good commit.
- To change the Python version, note the current subdomain, branch, entrypoint, and secrets; delete the app; redeploy with the desired version and reuse those settings.

## Deployment status

| Item | Status |
|---|---|
| Local headless startup from clean venv | Verified: `health: ok`, root title `Dashboard`, `exceptions: 0` |
| Clean installs on Python 3.11 and 3.12 | Verified locally |
| Dependency audit | Verified locally: no known vulnerabilities |
| Streamlit Community Cloud build and live app | **Not performed; owner action remains** |
| Live provider request | **Not performed** |
| Real browser rendering | **Not performed** |
