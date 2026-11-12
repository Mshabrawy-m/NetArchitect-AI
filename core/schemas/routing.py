"""Routing domain models.

Route entries and traffic demands expressed against the IP types defined
in :mod:`core.schemas.addressing`. All numeric fields are non-negative.
"""

from pydantic import BaseModel, Field

from core.schemas.addressing import AddressType, NetworkType


class RouteEntry(BaseModel):
    """A single routing-table entry.

    A ``next_hop`` of ``None`` denotes a directly-connected network.
    """

    destination: NetworkType = Field(description="Destination network prefix.")
    next_hop: AddressType | None = Field(
        default=None,
        description="Next-hop address, or None for a directly-connected network.",
    )
    interface: str | None = Field(
        default=None,
        description="Outgoing interface name, if applicable.",
    )
    metric: int = Field(
        description="Route metric / administrative cost (non-negative).",
        ge=0,
    )
    source: str | None = Field(
        default=None,
        description="How the route was learned, e.g. 'static', 'ospf', 'bgp'.",
    )


class TrafficDemand(BaseModel):
    """A traffic demand between two devices.

    All numeric fields are non-negative.
    """

    name: str = Field(description="Human-readable demand name.")
    source: str = Field(description="Id of the source device.")
    destination: str = Field(description="Id of the destination device.")
    bandwidth_mbps: float = Field(
        description="Requested bandwidth in megabits per second (non-negative).",
        ge=0,
    )
    priority: int = Field(
        default=0,
        description="Relative priority of the demand (non-negative; higher is more important).",
        ge=0,
    )
