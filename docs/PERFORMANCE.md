# Performance evidence (V2)

All numbers in this file are measured, not estimated. Timings were produced on
the local Windows host with Python 3.11.15 unless a Linux CI number is named.
The reproducible profile command is:

```bash
python scripts/profile_phase12.py --no-memory
```

It is intentionally run once before the V2 hot-path change and once after; it
is not part of a normal test run. `tracemalloc` is disabled in these wall-clock
runs.

## Linux RSS gate

`.github/workflows/ci.yml` runs `scripts/check_linux_memory.py` on
`ubuntu-latest` after importing `app` and rendering the Dashboard with
`AppTest`. The gate reads `VmRSS` from `/proc/self/status` and fails above
**450 MB**.

Why 450 MB: Community Cloud Free provides roughly 1 GB RAM. The OS, Streamlit
server, cold-start imports, and one interactive session need the remainder;
450 MB leaves headroom for those while still catching an accidental import or
unbounded cache regression. This is process RSS, not a `tracemalloc` peak. The
check has **not** been executed remotely; the first CI push must confirm it.

## Measured tables

See the baseline and after-change tables appended below by T3.
