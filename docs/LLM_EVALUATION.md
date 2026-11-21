# LLM evaluation (local golden set)

The optional copilot language features are evaluated offline with a scripted
provider. No API key, network call, or recorded response is needed to run the
suite.

```powershell
& ".venv\Scripts\python.exe" -m pytest -q tests/eval
```

`tests/eval/golden_cases.json` holds 24 cases (12 English, 12 Arabic) covering
deterministic link/device/traffic parsing, audited AI drafts, clarifications,
out-of-scope replies, and rejected invented numbers. `test_golden_copilot.py`
runs each case through `FakeProvider`, checks the typed result against the
golden expectation, and verifies that a repeat request is served from the
bounded cache without another provider call or budget charge.

Case types:

| Case type | Count | Pass |
|---|---:|---:|
| deterministic link failure | 4 | 4 |
| deterministic device failure | 4 | 4 |
| deterministic traffic scale | 4 | 4 |
| AI link failure | 2 | 2 |
| AI device failure | 2 | 2 |
| AI traffic scale | 2 | 2 |
| AI clarification | 2 | 2 |
| AI out of scope | 2 | 2 |
| AI invented number rejected | 2 | 2 |

## Local real-response recording (manual, never in CI)

A developer may optionally inspect one real provider response. This is **not**
part of CI and is never committed:

```powershell
& ".venv\Scripts\python.exe" scripts\record_llm_responses.py --feature interpret
& ".venv\Scripts\python.exe" scripts\record_llm_responses.py --feature explain
```

Rules enforced by the recorder:

- It refuses to run when the `CI` environment variable is set.
- It reads the key only at runtime from `GROQ_API_KEY` or local settings; the
  key is never printed and every occurrence is replaced with `[REDACTED]`.
- It writes only to `tests/eval/recorded/`, which is ignored by Git.
- It does not change the golden suite or any application code.

Live Groq behaviour is therefore explicitly **not** part of automated
verification.
