"""Deterministic checks for user-supplied design constraints.

Constraints are free-form text in the requirements model. Only rules with an
unambiguous meaning are checked here; every other constraint is reported as
recorded-but-not-machine-checkable instead of being ignored silently.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from core.schemas.validation import Finding, Severity
from simulation import NetworkState

_MAX_UTILIZATION = re.compile(
    r"max(?:imum)?\s+(?:link\s+)?utilization\s*(?:of|<=|\u2264|:)?\s*"
    r"(\d+(?:\.\d+)?)\s*%?",
    re.IGNORECASE,
)
_MIN_SERVED_RATIO = re.compile(
    r"(?:min(?:imum)?\s+)?served\s+demands?\s+(?:ratio|fraction)\s*"
    r"(?:of|>=|\u2265|:)?\s*(\d+(?:\.\d+)?)\s*%?",
    re.IGNORECASE,
)
_NO_SPOF = re.compile(
    r"no\s+(?:single\s+point\s+of\s+failure|spof)",
    re.IGNORECASE,
)


def _not_checkable(text: str) -> Finding:
    return Finding(
        severity=Severity.info,
        code="constraint_not_machine_checkable",
        affected_entities=[text],
        explanation=(
            f"Constraint {text!r} is recorded but has no deterministic check in "
            "this build."
        ),
        remediation=(
            "State the constraint as 'max utilization N%', 'served demand ratio "
            "N', 'no single point of failure', or review it manually."
        ),
    )


def _max_utilization_finding(text: str, value: float, state: NetworkState | None) -> Finding:
    if state is None:
        return Finding(
            severity=Severity.info,
            code="constraint_not_evaluated",
            affected_entities=[text],
            explanation=(
                f"Constraint {text!r} could not be evaluated because the capacity "
                "check did not run."
            ),
            remediation="Resolve the capacity-check failure and rerun validation.",
        )
    if state.max_utilization_percent > value:
        return Finding(
            severity=Severity.error,
            code="constraint_max_utilization_violated",
            affected_entities=[],
            explanation=(
                f"Constraint {text!r} is violated: the modeled peak link "
                f"utilization is {state.max_utilization_percent:.1f}%, above the "
                f"stated {value:g}%."
            ),
            remediation=(
                "Add capacity or reroute traffic until the modeled peak "
                "utilization is within the constraint."
            ),
        )
    return Finding(
        severity=Severity.info,
        code="constraint_satisfied",
        affected_entities=[],
        explanation=(
            f"Constraint {text!r} is satisfied: the modeled peak link "
            f"utilization is {state.max_utilization_percent:.1f}%."
        ),
        remediation="",
    )


def _served_ratio_finding(text: str, value: float, state: NetworkState | None) -> Finding:
    if state is None or state.demand_count == 0:
        return Finding(
            severity=Severity.info,
            code="constraint_not_evaluated",
            affected_entities=[text],
            explanation=(
                f"Constraint {text!r} could not be evaluated because the twin has "
                "no traffic demands or the capacity check did not run."
            ),
            remediation="Add traffic demands and rerun validation.",
        )
    if state.served_demand_ratio + 1e-9 < value:
        return Finding(
            severity=Severity.error,
            code="constraint_served_ratio_violated",
            affected_entities=[],
            explanation=(
                f"Constraint {text!r} is violated: the modeled served-demand "
                f"ratio is {state.served_demand_ratio:.3f}, below the stated "
                f"{value:g}."
            ),
            remediation=(
                "Restore reachability for the unserved demands or relax the "
                "constraint."
            ),
        )
    return Finding(
        severity=Severity.info,
        code="constraint_satisfied",
        affected_entities=[],
        explanation=(
            f"Constraint {text!r} is satisfied: the modeled served-demand ratio "
            f"is {state.served_demand_ratio:.3f}."
        ),
        remediation="",
    )


def constraint_findings(
    constraints: Sequence[str] | Iterable[str],
    *,
    state: NetworkState | None,
    redundancy: Sequence[Finding] = (),
    include_expensive: bool = False,
) -> list[Finding]:
    """Return findings for the constraints that this build can check."""
    findings: list[Finding] = []
    seen: set[str] = set()
    for raw in constraints:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)

        utilization = _MAX_UTILIZATION.search(text)
        if utilization is not None:
            findings.append(
                _max_utilization_finding(text, float(utilization.group(1)), state)
            )
            continue

        ratio = _MIN_SERVED_RATIO.search(text)
        if ratio is not None:
            value = float(ratio.group(1))
            if value > 1.0:
                value /= 100.0
            if 0.0 <= value <= 1.0:
                findings.append(_served_ratio_finding(text, value, state))
            else:
                findings.append(_not_checkable(text))
            continue

        if _NO_SPOF.search(text):
            if not include_expensive:
                findings.append(
                    Finding(
                        severity=Severity.info,
                        code="constraint_requires_expensive_check",
                        affected_entities=[text],
                        explanation=(
                            f"Constraint {text!r} requires the redundancy check, "
                            "which was skipped."
                        ),
                        remediation="Enable expensive checks to evaluate redundancy.",
                    )
                )
            elif redundancy:
                entities = sorted(
                    {
                        entity
                        for finding in redundancy
                        for entity in finding.affected_entities
                    }
                )
                findings.append(
                    Finding(
                        severity=Severity.error,
                        code="constraint_no_spof_violated",
                        affected_entities=entities,
                        explanation=(
                            f"Constraint {text!r} is violated: the structural "
                            f"analysis found {len(redundancy)} single point(s) of "
                            "failure."
                        ),
                        remediation=(
                            "Add independent paths or dual-home the affected "
                            "entities."
                        ),
                    )
                )
            else:
                findings.append(
                    Finding(
                        severity=Severity.info,
                        code="constraint_satisfied",
                        affected_entities=[],
                        explanation=(
                            f"Constraint {text!r} is satisfied: the structural "
                            "analysis found no single point of failure."
                        ),
                        remediation="",
                    )
                )
            continue

        findings.append(_not_checkable(text))
    return findings


__all__ = ["constraint_findings"]
