"""Requirements Understanding Agent (Phase 10a).

The agent turns a bounded free-text description into a validated
:class:`~core.schemas.requirements.NetworkRequirements`. It is deliberately
split into two layers:

* the optional language model only *extracts* a draft from the text; it never
  calculates, plans, or executes code; and
* deterministic Python audits that draft, keeps user-supplied facts and
  system-inferred assumptions in separate fields, rejects invented numbers,
  detects contradictions, and produces clarification questions.

A number is treated as a user fact only when it appears literally in the
supplied text. Any other number is either dropped from the fact layer or
recorded as an assumption. The agent also works without a provider: structured
input is validated directly, while free text returns an ``unavailable`` status
and offers the deterministic form path.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field

from config.limits import (
    MAX_CLARIFICATION_QUESTIONS,
    MAX_HOSTS_PER_SUBNET,
    MAX_LLM_REPAIR_RETRIES,
    MAX_REQUIREMENTS_DEPARTMENTS,
    MAX_REQUIREMENTS_LIST_ITEMS,
    MAX_REQUIREMENTS_TEXT_CHARS,
)
from core.exceptions import LLMError, LLMMissingKeyError, LLMSchemaError
from core.schemas.organization import Department, Organization, Site
from core.schemas.requirements import Assumption, NetworkRequirements, UserFacts
from core.schemas.validation import Severity
from services.llm.models import LLMMessage, MessageRole
from services.llm.provider import LLMProvider
from services.llm.structured import repair_instruction, validate_structured

from .base import AgentContext, BaseAgent

EXTRACTION_SYSTEM_PROMPT = (
    "You convert a network requirements description into the "
    "RequirementsExtraction schema. Use only information explicitly present in "
    "the user's text. Never guess or invent a number, user count, department, "
    "site, device, budget, or constraint. Leave values that are not stated "
    "empty or null. If you must record an inference, put it in assumptions and "
    "do not put it in departments, total_user_count, constraints, or "
    "design_goals. Return one JSON object with no prose or code fences."
)

_NUMBER_PATTERN = re.compile(r"\d[\d,]*")


def _numbers_in_text(text: str) -> frozenset[int]:
    """Return every non-negative integer token that appears literally in text."""
    numbers: set[int] = set()
    for token in _NUMBER_PATTERN.findall(text):
        try:
            numbers.add(int(token.replace(",", "")))
        except ValueError:  # pragma: no cover - the regex only yields digits
            continue
    return frozenset(numbers)


def _normalize(text: str) -> str:
    """Return a lower-case, whitespace-normalized comparison key."""
    return " ".join(text.lower().split())


def _grounded(text: str, statement: str) -> bool:
    """Return whether ``statement`` appears literally in the supplied text."""
    normalized = _normalize(statement)
    return bool(normalized) and normalized in _normalize(text)


def _clean_text_items(
    structured_items: list[str],
    proposed_items: list[str],
    source_text: str,
) -> list[str]:
    """Merge user-supplied items with only grounded model-proposed items.

    Structured-form values are user input and are kept as-is. Model-proposed
    constraints and goals are accepted only when their text appears in the
    source description, so the model cannot add design goals that the user did
    not state.
    """
    result: list[str] = []
    seen: set[str] = set()
    for item in structured_items:
        value = str(item).strip()
        key = _normalize(value)
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    for item in proposed_items:
        value = str(item).strip()
        key = _normalize(value)
        if not value or key in seen or not _grounded(source_text, value):
            continue
        seen.add(key)
        result.append(value)
    return result[:MAX_REQUIREMENTS_LIST_ITEMS]


class ExtractedDepartment(BaseModel):
    """One department proposed by the extraction model."""

    name: str = Field(min_length=1, max_length=120)
    user_count: int | None = Field(default=None, ge=0)
    site: str = Field(default="", max_length=120)


class ExtractedAssumption(BaseModel):
    """One system assumption proposed by the extraction model."""

    category: str = Field(default="requirements", max_length=80)
    description: str = Field(min_length=1, max_length=500)
    rationale: str = Field(default="", max_length=500)


class RequirementsExtraction(BaseModel):
    """The only object the language model is allowed to return.

    This is a *draft*: it is never treated as validated requirements. The agent
    audits every number and rebuilds the typed requirements deterministically.
    """

    organization_name: str = Field(default="", max_length=160)
    site_name: str = Field(default="", max_length=160)
    departments: list[ExtractedDepartment] = Field(
        default_factory=list,
        max_length=MAX_REQUIREMENTS_DEPARTMENTS,
    )
    total_user_count: int | None = Field(default=None, ge=0)
    constraints: list[str] = Field(
        default_factory=list,
        max_length=MAX_REQUIREMENTS_LIST_ITEMS,
    )
    design_goals: list[str] = Field(
        default_factory=list,
        max_length=MAX_REQUIREMENTS_LIST_ITEMS,
    )
    assumptions: list[ExtractedAssumption] = Field(
        default_factory=list,
        max_length=MAX_REQUIREMENTS_LIST_ITEMS,
    )


class RequirementsAgentStatus(str, Enum):
    """Outcome of one requirements-understanding run."""

    parsed = "parsed"
    structured = "structured"
    unavailable = "unavailable"
    failed = "failed"


class RequirementsGap(BaseModel):
    """One missing or contradictory item found by the deterministic audit."""

    code: str
    description: str
    severity: Severity
    affected: list[str] = Field(default_factory=list)


class ClarificationQuestion(BaseModel):
    """One question the user should answer before relying on the extraction."""

    id: str
    question: str
    severity: Severity
    reason: str = ""
    field: str = ""


class RequirementsAgentInput(BaseModel):
    """Bounded free text plus optional already-structured requirements."""

    free_text: str = Field(default="", max_length=MAX_REQUIREMENTS_TEXT_CHARS)
    requirements: NetworkRequirements | None = None


class RequirementsAgentOutput(BaseModel):
    """Validated requirements plus provenance, gaps, and questions."""

    status: RequirementsAgentStatus
    requirements: NetworkRequirements | None = None
    facts: UserFacts | None = None
    assumptions: list[Assumption] = Field(default_factory=list)
    missing_information: list[RequirementsGap] = Field(default_factory=list)
    contradictions: list[RequirementsGap] = Field(default_factory=list)
    questions: list[ClarificationQuestion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    summary: str
    error: str = ""
    provider_used: bool = False


def _department_count(facts: UserFacts) -> int:
    """Return the distinct department count represented by ``facts``."""
    sites = (
        list(facts.organization.sites)
        if facts.organization is not None and facts.organization.sites
        else list(facts.sites)
    )
    return len(
        {
            department.id
            for site in sites
            for department in site.departments
        }
        | {department.id for department in facts.departments}
    )


def _facts_user_sum(facts: UserFacts) -> int:
    """Return the user count of every distinct department in ``facts``.

    A department can be present both inside a site and in the flat
    ``departments`` list; identifiers are used to avoid double counting, the
    same convention the deterministic requirements tool uses.
    """
    sites = (
        list(facts.organization.sites)
        if facts.organization is not None and facts.organization.sites
        else list(facts.sites)
    )
    seen: set[str] = set()
    total = 0
    for site in sites:
        for department in site.departments:
            if department.id in seen:
                continue
            seen.add(department.id)
            total += department.user_count
    for department in facts.departments:
        if department.id in seen:
            continue
        seen.add(department.id)
        total += department.user_count
    return total


def _existing_department_names(facts: UserFacts) -> set[str]:
    sites = (
        list(facts.organization.sites)
        if facts.organization is not None and facts.organization.sites
        else list(facts.sites)
    )
    return {
        _normalize(department.name)
        for site in sites
        for department in site.departments
    } | {_normalize(department.name) for department in facts.departments}


def _existing_department_ids(facts: UserFacts) -> set[str]:
    sites = (
        list(facts.organization.sites)
        if facts.organization is not None and facts.organization.sites
        else list(facts.sites)
    )
    return {
        department.id
        for site in sites
        for department in site.departments
    } | {department.id for department in facts.departments}


class RequirementsUnderstandingAgent(BaseAgent):
    """Extract, audit, and validate network requirements from bounded text."""

    name = "requirements_understanding"
    responsibility = (
        "Convert free-text requirements into validated typed requirements while "
        "keeping user facts and system assumptions separate."
    )
    input_model = RequirementsAgentInput
    output_model = RequirementsAgentOutput
    allowed_tools = frozenset({"requirements_validate"})

    def __init__(
        self,
        provider: LLMProvider | None = None,
        *,
        max_repair_retries: int = MAX_LLM_REPAIR_RETRIES,
    ) -> None:
        self.provider = provider
        self.max_repair_retries = max(0, int(max_repair_retries))

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def run(
        self,
        payload: RequirementsAgentInput,
        context: AgentContext,
    ) -> RequirementsAgentOutput:
        """Return validated requirements or a typed non-result."""
        text = payload.free_text.strip()

        if not text:
            if payload.requirements is not None:
                return self._structured_result(
                    payload.requirements,
                    context,
                    notes=["Structured requirements were validated without a model."],
                )
            return RequirementsAgentOutput(
                status=RequirementsAgentStatus.failed,
                summary="No requirements text or structured data was supplied.",
                error="Provide free text or fill in the structured requirements form.",
            )

        if self.provider is None:
            return self._unavailable(payload)

        try:
            draft = self._extract(text)
        except LLMMissingKeyError:
            return self._unavailable(payload)
        except LLMError as error:
            return RequirementsAgentOutput(
                status=RequirementsAgentStatus.failed,
                requirements=None,
                summary="Requirement extraction failed; no requirements were produced.",
                error=str(error),
                provider_used=True,
            )

        return self._build_output(payload, draft, text, context)

    # ------------------------------------------------------------------
    # Bounded provider interaction
    # ------------------------------------------------------------------
    def _extract(self, text: str) -> RequirementsExtraction:
        """Ask the provider for one schema-valid draft, with bounded repairs."""
        messages: list[LLMMessage] = [
            LLMMessage(role=MessageRole.system, content=EXTRACTION_SYSTEM_PROMPT),
            LLMMessage(role=MessageRole.user, content=text),
        ]
        last_error: LLMSchemaError | None = None
        for attempt in range(self.max_repair_retries + 1):
            if attempt:
                messages = [
                    *messages,
                    LLMMessage(
                        role=MessageRole.user,
                        content=repair_instruction(
                            RequirementsExtraction,
                            str(last_error) if last_error else "invalid schema",
                        ),
                    ),
                ]
            try:
                response = self.provider.complete(
                    messages,
                    schema=RequirementsExtraction,
                )
            except LLMSchemaError as error:
                last_error = error
                continue

            if response.structured is not None:
                return RequirementsExtraction.model_validate(response.structured)
            try:
                return validate_structured(response.text, RequirementsExtraction)
            except LLMSchemaError as error:
                last_error = error
                continue

        assert last_error is not None
        raise last_error

    # ------------------------------------------------------------------
    # Non-result paths
    # ------------------------------------------------------------------
    def _unavailable(self, payload: RequirementsAgentInput) -> RequirementsAgentOutput:
        requirements = payload.requirements
        notes = [
            "No AI provider is configured, so free text was not interpreted.",
            (
                "Use the structured requirements form; the deterministic workflow "
                "needs no API key."
            ),
        ]
        if requirements is not None:
            notes.append("The supplied structured requirements were kept as entered.")
        return RequirementsAgentOutput(
            status=RequirementsAgentStatus.unavailable,
            requirements=requirements,
            facts=requirements.user_provided if requirements is not None else None,
            assumptions=list(requirements.assumptions) if requirements else [],
            questions=[
                ClarificationQuestion(
                    id="q-form-path",
                    question=(
                        "Enter the organization, sites, departments, and user counts "
                        "in the structured form."
                    ),
                    severity=Severity.info,
                    reason=(
                        "Natural-language interpretation requires an optional API key."
                    ),
                    field="free_text",
                )
            ],
            notes=notes,
            summary=(
                "AI requirement extraction is unavailable. The structured form "
                "remains fully usable without a key."
            ),
            error="No AI provider is configured for free-text extraction.",
            provider_used=False,
        )

    def _structured_result(
        self,
        requirements: NetworkRequirements,
        context: AgentContext,
        *,
        notes: list[str],
    ) -> RequirementsAgentOutput:
        validated = context.call_tool(
            "requirements_validate",
            {"requirements": requirements},
        )
        return RequirementsAgentOutput(
            status=RequirementsAgentStatus.structured,
            requirements=requirements,
            facts=requirements.user_provided,
            assumptions=list(requirements.assumptions),
            notes=notes,
            summary=(
                f"Structured requirements accepted: {validated.site_count} site(s), "
                f"{validated.department_count} department(s), "
                f"{validated.total_user_count} reported user(s)."
            ),
            provider_used=False,
        )

    # ------------------------------------------------------------------
    # Deterministic audit and construction
    # ------------------------------------------------------------------
    def _build_output(
        self,
        payload: RequirementsAgentInput,
        draft: RequirementsExtraction,
        text: str,
        context: AgentContext,
    ) -> RequirementsAgentOutput:
        numbers = _numbers_in_text(text)
        missing: list[RequirementsGap] = []
        contradictions: list[RequirementsGap] = []
        questions: list[ClarificationQuestion] = []
        assumptions: list[Assumption] = []
        notes: list[str] = [
            (
                "User facts come only from the structured input and numbers that "
                "appear literally in the supplied text."
            ),
        ]

        def add_issue(
            *,
            code: str,
            description: str,
            severity: Severity,
            question: str = "",
            affected: list[str] | None = None,
            field: str = "",
            contradiction: bool = False,
        ) -> None:
            gap = RequirementsGap(
                code=code,
                description=description,
                severity=severity,
                affected=list(affected or []),
            )
            (contradictions if contradiction else missing).append(gap)
            if question:
                questions.append(
                    ClarificationQuestion(
                        id=f"q-{len(questions) + 1}",
                        question=question,
                        severity=severity,
                        reason=description,
                        field=field,
                    )
                )

        def add_assumption(category: str, description: str, rationale: str) -> None:
            assumptions.append(
                Assumption(
                    id=f"assumption-{len(assumptions) + 1}",
                    category=category,
                    description=description,
                    rationale=rationale,
                )
            )

        verified: list[tuple[str, int, str]] = []
        seen_names: set[str] = set()
        for department in draft.departments:
            name = department.name.strip()
            if not name:
                continue
            key = _normalize(name)
            if key in seen_names:
                add_issue(
                    code="duplicate_department",
                    description=(
                        f"Department {name!r} was proposed more than once; only the "
                        "first occurrence was kept."
                    ),
                    severity=Severity.warning,
                    affected=[name],
                )
                continue
            seen_names.add(key)

            if department.user_count is None:
                add_issue(
                    code="missing_user_count",
                    description=(
                        f"No user count for department {name!r} appears in the "
                        "supplied text."
                    ),
                    severity=Severity.warning,
                    question=f"How many users are in the {name} department?",
                    affected=[name],
                    field="departments",
                )
                add_assumption(
                    "requirements",
                    (
                        f"Department {name!r} is not included in the user-fact layer "
                        "because its user count was not stated."
                    ),
                    "A department user count is required before the deterministic "
                    "planner can size its subnet.",
                )
                continue

            if department.user_count > MAX_HOSTS_PER_SUBNET:
                add_issue(
                    code="user_count_limit",
                    description=(
                        f"Department {name!r} reports {department.user_count} users, "
                        f"above the {MAX_HOSTS_PER_SUBNET}-host planning limit."
                    ),
                    severity=Severity.error,
                    question=(
                        f"Confirm the user count for {name}; it exceeds the "
                        "per-subnet planning limit."
                    ),
                    affected=[name],
                    field="departments",
                )
                add_assumption(
                    "requirements",
                    (
                        f"Department {name!r} is excluded from the user-fact layer "
                        "because its reported user count exceeds the planning limit."
                    ),
                    "Address arithmetic must stay inside the configured bounds.",
                )
                continue

            if department.user_count not in numbers:
                add_issue(
                    code="unverified_user_count",
                    description=(
                        f"The proposed user count for {name!r} "
                        f"({department.user_count}) does not appear in the supplied "
                        "text and is not treated as a user fact."
                    ),
                    severity=Severity.warning,
                    question=f"How many users are in the {name} department?",
                    affected=[name],
                    field="departments",
                )
                add_assumption(
                    "requirements",
                    (
                        f"Department {name!r} is not included in the user-fact layer "
                        f"because the proposed count {department.user_count} was not "
                        "found in the supplied text."
                    ),
                    "Numbers not present in the source text are never promoted to "
                    "user-provided facts.",
                )
                continue

            verified.append((name, department.user_count, department.site.strip()))

        stated_total = draft.total_user_count
        extracted_total_is_verified = (
            stated_total is not None
            and stated_total > 0
            and stated_total <= MAX_HOSTS_PER_SUBNET
            and stated_total in numbers
        )
        if stated_total is not None:
            if stated_total > MAX_HOSTS_PER_SUBNET:
                add_issue(
                    code="user_count_limit",
                    description=(
                        f"The proposed total user count {stated_total} is above the "
                        f"{MAX_HOSTS_PER_SUBNET}-host planning limit."
                    ),
                    severity=Severity.error,
                    question="Confirm the total number of users.",
                    field="total_user_count",
                )
            elif stated_total > 0 and not extracted_total_is_verified:
                add_issue(
                    code="unverified_user_count",
                    description=(
                        f"The proposed total user count ({stated_total}) does not "
                        "appear in the supplied text and is not treated as a user "
                        "fact."
                    ),
                    severity=Severity.warning,
                    question="What is the total number of network users?",
                    field="total_user_count",
                )

        structured_total = (
            payload.requirements.user_provided.total_user_count
            if payload.requirements is not None
            else 0
        )
        reported_total = (
            structured_total
            if structured_total > 0
            else (stated_total if extracted_total_is_verified else 0)
        )
        total_is_verified = reported_total > 0
        structured_departments = (
            _department_count(payload.requirements.user_provided)
            if payload.requirements is not None
            else 0
        )

        facts = self._build_facts(
            payload.requirements,
            draft,
            verified,
            reported_total if total_is_verified else None,
        )
        facts_user_sum = _facts_user_sum(facts)

        if not verified and not structured_departments:
            add_issue(
                code="missing_user_counts",
                description=(
                    "No department user counts could be verified from the supplied "
                    "text."
                ),
                severity=Severity.error,
                question=(
                    "How many users are in each department, and is there a stated "
                    "total?"
                ),
                field="departments",
            )
        elif not total_is_verified:
            add_issue(
                code="missing_total_user_count",
                description=(
                    "No verified total user count appears in the supplied text."
                ),
                severity=Severity.warning,
                question="What is the total number of network users?",
                field="total_user_count",
            )

        if total_is_verified and facts_user_sum and reported_total != facts_user_sum:
            add_issue(
                code="user_count_mismatch",
                description=(
                    f"The stated total ({reported_total}) does not match the sum of "
                    f"the verified department counts ({facts_user_sum})."
                ),
                severity=Severity.error,
                question=(
                    "Which user count is correct: the stated total or the sum of "
                    "the department counts?"
                ),
                field="total_user_count",
                contradiction=True,
            )
        elif not total_is_verified:
            if facts_user_sum:
                add_assumption(
                    "requirements",
                    (
                        "No total user count was stated; the verified department "
                        f"counts sum to {facts_user_sum}."
                    ),
                    "Only numbers present in the supplied text are user facts, so "
                    "the total is recorded as an assumption.",
                )
            else:
                add_assumption(
                    "requirements",
                    (
                        "No total user count was stated and no verified department "
                        "counts were supplied."
                    ),
                    "The deterministic planner will use its documented fallback "
                    "instead of inventing a user count.",
                )

        design_goals = _clean_text_items(
            list(payload.requirements.design_goals) if payload.requirements else [],
            draft.design_goals,
            text,
        )

        if not draft.organization_name.strip() and (
            facts.organization is None or not facts.organization.name.strip()
        ):
            add_issue(
                code="missing_organization",
                description="No organization name appears in the supplied text.",
                severity=Severity.info,
                question="What is the organization name?",
                field="organization",
            )
            add_assumption(
                "requirements",
                "No organization name was supplied; the design uses default labels.",
                "Names are presentation labels and do not affect the deterministic "
                "engineering calculations.",
            )
        structured_sites = bool(
            payload.requirements is not None
            and (
                payload.requirements.user_provided.sites
                or (
                    payload.requirements.user_provided.organization is not None
                    and payload.requirements.user_provided.organization.sites
                )
            )
        )
        if not draft.site_name.strip() and not structured_sites:
            add_issue(
                code="missing_site",
                description="No site name or site count appears in the supplied text.",
                severity=Severity.info,
                question="Which sites should the design cover?",
                field="sites",
            )
            add_assumption(
                "requirements",
                "No site was named; the design uses a single default site label.",
                "A site label is presentation metadata and does not change the "
                "deterministic engineering calculations.",
            )
        if not design_goals:
            add_issue(
                code="missing_design_goals",
                description="No design goals appear in the supplied text.",
                severity=Severity.info,
                question=(
                    "What are the main design goals (for example resilience or "
                    "simplicity)?"
                ),
                field="design_goals",
            )

        for proposed in draft.assumptions:
            add_assumption(
                proposed.category.strip() or "requirements",
                proposed.description.strip(),
                proposed.rationale.strip(),
            )

        assumptions = self._dedupe_assumptions(
            [
                *(payload.requirements.assumptions if payload.requirements else []),
                *assumptions,
            ]
        )
        facts = facts.model_copy(
            update={
                "constraints": self._constraints(
                    payload.requirements,
                    draft,
                    text,
                )
            }
        )
        requirements = NetworkRequirements(
            user_provided=facts,
            assumptions=assumptions,
            design_goals=design_goals,
        )

        validated = context.call_tool(
            "requirements_validate",
            {"requirements": requirements},
        )

        questions = questions[:MAX_CLARIFICATION_QUESTIONS]
        summary = self._summary(
            validated.department_count,
            validated.total_user_count,
            total_is_verified,
            assumptions,
            missing,
            contradictions,
        )
        return RequirementsAgentOutput(
            status=RequirementsAgentStatus.parsed,
            requirements=requirements,
            facts=requirements.user_provided,
            assumptions=assumptions,
            missing_information=missing,
            contradictions=contradictions,
            questions=questions,
            notes=notes,
            summary=summary,
            provider_used=True,
        )

    def _build_facts(
        self,
        structured: NetworkRequirements | None,
        draft: RequirementsExtraction,
        verified: list[tuple[str, int, str]],
        stated_total: int | None,
    ) -> UserFacts:
        """Merge structured facts with verified extracted departments.

        Structured values always win. Extracted departments are appended only
        when their names are new and only after the number audit verified their
        counts.
        """
        if structured is None:
            base = UserFacts()
        else:
            base = structured.user_provided.model_copy(deep=True)

        organization = base.organization
        sites = list(base.sites)
        flat = list(base.departments)

        existing_names = _existing_department_names(base)
        existing_ids = _existing_department_ids(base)
        next_id = 1

        def new_id() -> str:
            nonlocal next_id
            while f"dept-ext-{next_id}" in existing_ids:
                next_id += 1
            identifier = f"dept-ext-{next_id}"
            existing_ids.add(identifier)
            next_id += 1
            return identifier

        new_departments: list[Department] = []
        for name, count, _ in verified:
            key = _normalize(name)
            if key in existing_names:
                continue
            existing_names.add(key)
            new_departments.append(
                Department(id=new_id(), name=name, user_count=count)
            )

        has_site_structure = organization is not None or bool(sites)
        if new_departments:
            if has_site_structure:
                flat.extend(new_departments)
            else:
                site = Site(
                    id="site-1",
                    name=draft.site_name.strip() or "Main site",
                    departments=new_departments,
                )
                sites = [site]
                if draft.organization_name.strip():
                    organization = Organization(
                        id="org-1",
                        name=draft.organization_name.strip(),
                        sites=[site],
                    )
        elif not has_site_structure and (
            draft.site_name.strip() or draft.organization_name.strip()
        ):
            site = Site(
                id="site-1",
                name=draft.site_name.strip() or "Main site",
                departments=[],
            )
            sites = [site]
            if draft.organization_name.strip():
                organization = Organization(
                    id="org-1",
                    name=draft.organization_name.strip(),
                    sites=[site],
                )

        if organization is None and draft.organization_name.strip() and sites:
            organization = Organization(
                id="org-1",
                name=draft.organization_name.strip(),
                sites=sites,
            )

        total = (
            base.total_user_count
            if base.total_user_count > 0
            else (stated_total if stated_total is not None and stated_total > 0 else 0)
        )
        return UserFacts(
            organization=organization,
            sites=sites,
            departments=flat,
            device_requirements=list(base.device_requirements),
            link_requirements=list(base.link_requirements),
            constraints=list(base.constraints),
            total_user_count=total,
        )

    @staticmethod
    def _constraints(
        structured: NetworkRequirements | None,
        draft: RequirementsExtraction,
        text: str,
    ) -> list[str]:
        return _clean_text_items(
            list(structured.user_provided.constraints) if structured else [],
            draft.constraints,
            text,
        )

    @staticmethod
    def _dedupe_assumptions(assumptions: list[Assumption]) -> list[Assumption]:
        result: list[Assumption] = []
        seen: set[str] = set()
        for assumption in assumptions:
            key = _normalize(assumption.description)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(
                assumption.model_copy(update={"id": f"assumption-{len(result) + 1}"})
            )
        return result[:MAX_REQUIREMENTS_LIST_ITEMS]

    @staticmethod
    def _summary(
        department_count: int,
        reported_total: int,
        total_is_verified: bool,
        assumptions: list[Assumption],
        missing: list[RequirementsGap],
        contradictions: list[RequirementsGap],
    ) -> str:
        total_phrase = (
            f"{reported_total} reported user(s)"
            if total_is_verified
            else "total user count not stated as a verified fact"
        )
        return (
            f"{department_count} department(s), {total_phrase}; "
            f"{len(assumptions)} assumption(s), "
            f"{len(missing)} missing item(s), "
            f"{len(contradictions)} contradiction(s)."
        )


__all__ = [
    "EXTRACTION_SYSTEM_PROMPT",
    "ClarificationQuestion",
    "ExtractedAssumption",
    "ExtractedDepartment",
    "RequirementsAgentInput",
    "RequirementsAgentOutput",
    "RequirementsAgentStatus",
    "RequirementsExtraction",
    "RequirementsGap",
    "RequirementsUnderstandingAgent",
]
