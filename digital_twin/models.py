"""Digital twin domain models.

The digital twin is a *software model* of a network design. It is the single
source of truth for the topology, the addressed and VLAN-tagged plans, DHCP
scopes, traffic demands, and the operational state of devices and links. It is
not a connection to, or a live copy of, real networking equipment.

Units
-----
* Times are timezone-aware ISO-8601 timestamps supplied by the caller.
* ``Link.capacity_mbps`` is megabits per second.
* ``Link.cost`` is a routing metric with no physical unit.
* ``TrafficDemand.bandwidth_mbps`` is megabits per second.
* ``DhcpScope.lease_minutes`` is minutes.

All models in this module are frozen. Operations in
:mod:`digital_twin.operations` return new twins instead of mutating an existing
one. Missing device/link state entries mean ``up``; an explicit ``down`` entry
records a modeled failure.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.schemas.addressing import AddressingPlan, DhcpScope
from core.schemas.network import Topology
from core.schemas.requirements import Assumption
from core.schemas.routing import TrafficDemand
from network.routing.ha import HaGroup
from network.vlan.plan import VlanPlanResult
from security.models import SecurityModel

TWIN_SCHEMA_VERSION = 2
SUPPORTED_TWIN_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2)


class OperationalState(str, Enum):
    """Modeled operational state of one device or link."""

    up = "up"  # The entity participates in the modeled network.
    down = "down"  # The entity is modeled as failed and must be excluded.


class TwinMetadata(BaseModel):
    """Identity and versioning metadata for a digital twin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        min_length=1,
        description="Human-readable twin name supplied by the caller.",
    )
    created_at: datetime = Field(
        description="Timezone-aware creation timestamp supplied by the caller (ISO-8601).",
    )
    schema_version: int = Field(
        default=TWIN_SCHEMA_VERSION,
        ge=1,
        description="Digital-twin JSON schema version this model was written with.",
    )


class DeviceState(BaseModel):
    """The modeled operational state of one device."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    device_id: str = Field(
        min_length=1,
        description="Id of a device in the twin topology.",
    )
    state: OperationalState = Field(
        default=OperationalState.up,
        description="Modeled state; 'down' means the device is treated as failed.",
    )


class LinkState(BaseModel):
    """The modeled operational state of one link."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: str = Field(
        min_length=1,
        description="Id of a link in the twin topology.",
    )
    state: OperationalState = Field(
        default=OperationalState.up,
        description="Modeled state; 'down' means the link is treated as failed.",
    )


class SharedRiskGroup(BaseModel):
    """A set of devices/links modeled as failing together.

    This is a failure-model annotation, not a live equipment configuration. A
    sweep that targets any member marks every member of the group down. Member
    ids are canonicalized (sorted and duplicate-free) so equivalent groups have
    stable JSON and stable fingerprints.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(
        min_length=1,
        description="Stable identifier for this shared-risk group.",
    )
    name: str = Field(
        default="",
        description="Optional human-readable label.",
    )
    device_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Device ids that fail together with the group.",
    )
    link_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Link ids that fail together with the group.",
    )
    rationale: str = Field(
        default="",
        description="Why these entities share a modeled failure domain.",
    )

    @model_validator(mode="before")
    @classmethod
    def _canonicalize(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        device_ids = tuple(data.get("device_ids", ()))
        link_ids = tuple(data.get("link_ids", ()))
        if not device_ids and not link_ids:
            raise ValueError(
                "A shared-risk group must name at least one device or link."
            )
        identifier = str(data.get("id", ""))
        return {
            **data,
            "name": data.get("name") or identifier,
            "rationale": data.get("rationale") or "Modeled shared failure domain.",
            "device_ids": tuple(sorted(set(device_ids))),
            "link_ids": tuple(sorted(set(link_ids))),
        }


class DigitalTwin(BaseModel):
    """A complete software model of one network design.

    The twin is the single source of truth. Pages and engines read the baseline
    from this object; derived results are never a second copy of the model.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    metadata: TwinMetadata = Field(
        description="Twin identity, creation time, and schema version.",
    )
    topology: Topology = Field(
        description="Devices and links, including capacity (Mbps) and cost.",
    )
    addressing: AddressingPlan | None = Field(
        default=None,
        description="Optional IP addressing plan: VLAN-tagged and standalone subnets.",
    )
    vlan_plan: VlanPlanResult | None = Field(
        default=None,
        description="Optional department-to-VLAN assignment produced by the VLAN planner.",
    )
    dhcp_scopes: tuple[DhcpScope, ...] = Field(
        default_factory=tuple,
        description="DHCP scopes; lease durations are in minutes.",
    )
    demands: tuple[TrafficDemand, ...] = Field(
        default_factory=tuple,
        description="Traffic demands; bandwidth is in megabits per second.",
    )
    device_states: tuple[DeviceState, ...] = Field(
        default_factory=tuple,
        description="Explicit device states. A device without an entry is up.",
    )
    link_states: tuple[LinkState, ...] = Field(
        default_factory=tuple,
        description="Explicit link states. A link without an entry is up.",
    )
    assumptions: tuple[Assumption, ...] = Field(
        default_factory=tuple,
        description="Scenario assumptions recorded with the modeled design.",
    )
    security: SecurityModel | None = Field(
        default=None,
        description=(
            "Optional design-time security model. It is omitted from JSON and "
            "fingerprints when absent so legacy twin bytes stay compatible."
        ),
    )
    shared_risk_groups: tuple[SharedRiskGroup, ...] = Field(
        default_factory=tuple,
        description=(
            "Optional modeled failure domains. Empty groups are omitted from "
            "JSON and fingerprints so legacy twin bytes stay compatible."
        ),
    )
    ha_groups: tuple[HaGroup, ...] = Field(
        default_factory=tuple,
        description=(
            "Optional modeled first-hop redundancy groups. Empty groups are "
            "omitted from JSON and fingerprints so legacy twin bytes stay "
            "compatible."
        ),
    )


def effective_device_state(twin: DigitalTwin, device_id: str) -> OperationalState:
    """Return the modeled state for ``device_id``, defaulting to ``up``."""
    for entry in twin.device_states:
        if entry.device_id == device_id:
            return entry.state
    return OperationalState.up


def effective_link_state(twin: DigitalTwin, link_id: str) -> OperationalState:
    """Return the modeled state for ``link_id``, defaulting to ``up``."""
    for entry in twin.link_states:
        if entry.link_id == link_id:
            return entry.state
    return OperationalState.up
