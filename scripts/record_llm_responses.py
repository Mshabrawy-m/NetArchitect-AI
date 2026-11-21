"""Local-only recorder for redacted real-provider copilot responses.

This is a manual developer aid. It is never run by CI, never imported by the
application, and never writes into a tracked directory. The API key is read at
runtime from the environment or local settings, is replaced in every recorded
string, and is never printed. Recorded files are ignored by Git.

Usage (PowerShell, from the repository root)::

    & ".venv\\Scripts\\python.exe" scripts\\record_llm_responses.py --feature interpret
    & ".venv\\Scripts\\python.exe" scripts\\record_llm_responses.py --feature explain

The golden evaluation suite in ``tests/eval`` uses FakeProvider and needs no
recorded file and no network access.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import get_settings
from services.llm import (
    EXPLAIN_RESULT,
    INTERPRET_SCENARIO,
    LLMMessage,
    MessageRole,
    PromptSpec,
)
from services.llm.budget import RequestBudget
from services.llm.groq import GroqProvider

EXAMPLES: dict[str, tuple[PromptSpec, str]] = {
    "interpret": (
        INTERPRET_SCENARIO,
        json.dumps(
            {
                "sentence": "please take the ab link down",
                "allowlist": {
                    "link_ids": ["ab", "bd", "ac", "cd"],
                    "device_ids": ["a", "b", "c", "d"],
                    "demands": [],
                },
            },
            ensure_ascii=False,
        ),
    ),
    "explain": (
        EXPLAIN_RESULT,
        json.dumps(
            {
                "target": "route",
                "facts": (
                    "Demand a-to-c, path a -> b -> c, links ab, bc, 2 hops, "
                    "total cost 2, requested 150 Mbps"
                ),
            },
            ensure_ascii=False,
        ),
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feature", choices=sorted(EXAMPLES), required=True)
    parser.add_argument(
        "--out",
        default="tests/eval/recorded",
        help="Ignored output directory for redacted recordings.",
    )
    args = parser.parse_args()

    if os.environ.get("CI", "").strip():
        print("REFUSED: real-provider recording is disabled in CI.")
        return 2

    key = os.environ.get("GROQ_API_KEY", "").strip() or get_settings().GROQ_API_KEY.strip()
    if not key:
        print("REFUSED: set GROQ_API_KEY locally before recording.")
        return 2

    prompt, user_content = EXAMPLES[args.feature]
    provider = GroqProvider(api_key=key, budget=RequestBudget())
    response = provider.complete(
        [
            LLMMessage(role=MessageRole.system, content=prompt.text),
            LLMMessage(role=MessageRole.user, content=user_content),
        ]
    )

    payload = {
        "feature": args.feature,
        "prompt_id": prompt.id,
        "prompt_version": prompt.version,
        "model": response.model,
        "recorded_at": datetime.now(UTC).isoformat(),
        "text": response.text.replace(key, "[REDACTED]"),
        "note": "Local sample only. Not part of the golden suite.",
    }
    output = ROOT / args.out / f"{args.feature}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"PASS: redacted sample written to {output.relative_to(ROOT)} (Git-ignored).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
