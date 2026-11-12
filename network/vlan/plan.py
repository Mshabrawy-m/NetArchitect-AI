"""Deterministic VLAN planning and department mapping.

VLAN ids are allocated in request order starting from ``start_vlan_id``. The
following ids are reserved and never assigned automatically:

* ``1`` - the default VLAN.
* ``1002`` - ``1005`` - legacy Token Ring/FDDI VLANs.

IEEE 802.1Q also reserves ``0`` and ``4095``; the domain schema only permits
``1`` to ``4094``, so those values are rejected as out of range. Every VLAN in
a plan is linked to exactly one subnet, and subnets in one plan may not
overlap.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field, model_validator

from core.exceptions import DuplicateIdError, InvalidVlanIdError, OverlappingSubnetError
from core.schemas.addressing import NetworkType, Subnet
from network.addressing.validation import detect_overlaps

VLAN_ID_MIN = 1
VLAN_ID_MAX = 4094
DEFAULT_VLAN_START = 10
RESERVED_VLAN_IDS: frozenset[int] = frozenset({1, 1002, 1003, 1004, 1005})
RESERVED_VLAN_RANGES: tuple[tuple[int, int], ...] = ((1, 1), (1002, 1005))


class VlanRequest(BaseModel):
    """A department that needs one VLAN and one subnet."""

    department: str = Field(min_length=1)
    subnet: Subnet
    vlan_id: int | None = Field(
        default=None,
        description="Optional explicit VLAN id; auto-assigned when omitted.",
    )
    vlan_name: str | None = Field(default=None)
    purpose: str = Field(default="")

    @model_validator(mode="after")
    def _explicit_vlan_id_is_valid(self) -> VlanRequest:
        if self.vlan_id is None:
            return self
        if not VLAN_ID_MIN <= self.vlan_id <= VLAN_ID_MAX:
            raise ValueError(
                f"VLAN id must be between {VLAN_ID_MIN} and {VLAN_ID_MAX}, "
                f"got {self.vlan_id}"
            )
        if self.vlan_id in RESERVED_VLAN_IDS:
            raise ValueError(f"VLAN id {self.vlan_id} is reserved")
        return self


class VlanAssignment(BaseModel):
    """One department-to-VLAN-to-subnet mapping."""

    department: str
    vlan_id: int = Field(ge=VLAN_ID_MIN, le=VLAN_ID_MAX)
    vlan_name: str
    subnet_name: str
    network: NetworkType
    purpose: str = ""


class VlanPlanResult(BaseModel):
    """A complete VLAN plan."""

    assignments: list[VlanAssignment] = Field(default_factory=list)
    reserved_vlan_ids: list[int] = Field(default_factory=list)


def _next_available_vlan_id(start: int, used: set[int]) -> int:
    candidate = max(start, VLAN_ID_MIN)
    while candidate <= VLAN_ID_MAX:
        if candidate not in RESERVED_VLAN_IDS and candidate not in used:
            return candidate
        candidate += 1
    raise InvalidVlanIdError(
        f"No VLAN ids available at or above {start}; "
        f"{len(used)} ids are already assigned"
    )


def plan_vlans(
    requests: Sequence[VlanRequest],
    *,
    start_vlan_id: int = DEFAULT_VLAN_START,
) -> VlanPlanResult:
    """Assign one VLAN id and one subnet to every department.

    Explicit ids and auto-assigned ids share the same uniqueness check, so a
    later explicit id that collides with an earlier automatic one is rejected.
    Overlapping subnets raise
    :class:`~core.exceptions.OverlappingSubnetError` before any ids are
    assigned.
    """
    if not VLAN_ID_MIN <= start_vlan_id <= VLAN_ID_MAX:
        raise InvalidVlanIdError(
            f"start_vlan_id must be between {VLAN_ID_MIN} and {VLAN_ID_MAX}, "
            f"got {start_vlan_id}"
        )

    departments: set[str] = set()
    subnet_names: set[str] = set()
    for request in requests:
        if request.department in departments:
            raise DuplicateIdError(
                f"Duplicate department in VLAN plan: {request.department!r}"
            )
        departments.add(request.department)
        if request.subnet.name in subnet_names:
            raise DuplicateIdError(
                f"Duplicate subnet name in VLAN plan: {request.subnet.name!r}"
            )
        subnet_names.add(request.subnet.name)

    overlaps = detect_overlaps([request.subnet for request in requests])
    if overlaps:
        raise OverlappingSubnetError(overlaps[0].explanation)

    used: set[int] = set()
    assignments: list[VlanAssignment] = []
    for request in requests:
        if request.vlan_id is not None:
            if request.vlan_id in used:
                raise DuplicateIdError(
                    f"VLAN id {request.vlan_id} is assigned more than once"
                )
            vlan_id = request.vlan_id
        else:
            vlan_id = _next_available_vlan_id(start_vlan_id, used)
        used.add(vlan_id)
        assignments.append(
            VlanAssignment(
                department=request.department,
                vlan_id=vlan_id,
                vlan_name=request.vlan_name or f"{request.department} VLAN",
                subnet_name=request.subnet.name,
                network=request.subnet.network,
                purpose=request.purpose or request.department,
            )
        )

    return VlanPlanResult(
        assignments=assignments,
        reserved_vlan_ids=sorted(RESERVED_VLAN_IDS),
    )
