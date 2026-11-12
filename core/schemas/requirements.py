"""Composite requirements domain models.

The requirements layer bundles the facts a user explicitly supplies
(:class:`UserFacts`) together with the assumptions the system infers
(:class:`Assumption`). These two kinds of input are deliberately kept in
SEPARATE fields on :class:`NetworkRequirements` so downstream engineering and
audit logic can always tell which inputs came from the user and which were
inferred by the system; they must never be mixed or merged into a single
collection.
"""

from pydantic import BaseModel, Field

from .network import Device, Link
from .organization import Department, Organization, Site


class Assumption(BaseModel):
    """A single assumption inferred by the system (NOT supplied by the user).

    Assumptions are SYSTEM-INFERRED and are kept strictly separate from the
    user-supplied facts in :class:`UserFacts`; the two must never be mixed.
    Each assumption records the category it belongs to and why it was made so
    downstream logic can revisit or override it.
    """

    id: str = Field(description="Unique identifier for the assumption.")
    category: str = Field(
        description="Category the assumption belongs to, e.g. 'growth' or 'traffic'.",
    )
    description: str = Field(description="What the system is assuming.")
    rationale: str = Field(
        default="",
        description="Why the assumption was made (traceability for later review).",
    )


class UserFacts(BaseModel):
    """The facts the user explicitly supplied about their network.

    These are the user-provided inputs: the organization, sites, departments,
    device and link requirements, free-form constraints, and a total user
    count. They are the counterpart to :class:`Assumption` and the two are
    kept in separate fields on :class:`NetworkRequirements` so user input is
    never confused with system-inferred assumptions.
    """

    organization: Organization | None = Field(
        default=None,
        description="The organization the requirements are for, if supplied by the user.",
    )
    sites: list[Site] = Field(
        default_factory=list,
        description="Sites the user identified.",
    )
    departments: list[Department] = Field(
        default_factory=list,
        description="Departments the user identified.",
    )
    device_requirements: list[Device] = Field(
        default_factory=list,
        description="Devices the user requires in the design.",
    )
    link_requirements: list[Link] = Field(
        default_factory=list,
        description="Links the user requires in the design.",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="Free-form constraint statements supplied by the user.",
    )
    total_user_count: int = Field(
        default=0,
        description="Total number of network users the user reported (non-negative).",
        ge=0,
    )


class NetworkRequirements(BaseModel):
    """The complete requirements bundle for a design run.

    IMPORTANT: ``user_provided`` (the facts the user supplied, a
    :class:`UserFacts` instance) and ``assumptions`` (a list of
    :class:`Assumption`, system-inferred) are SEPARATE fields and must never
    be mixed. Keeping user-supplied facts distinct from system-inferred
    assumptions is a core invariant: downstream engineering and audit logic
    relies on being able to tell the provenance of every input. Do not merge
    the two into a single collection, copy assumptions into ``user_provided``,
    or copy user facts into ``assumptions``.
    """

    user_provided: UserFacts = Field(
        description="Facts the user explicitly supplied; never mixed with assumptions.",
    )
    assumptions: list[Assumption] = Field(
        default_factory=list,
        description="Assumptions inferred by the system; never mixed with user facts.",
    )
    design_goals: list[str] = Field(
        default_factory=list,
        description="High-level design goals the solution should aim for.",
    )
