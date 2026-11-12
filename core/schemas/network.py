"""Network topology domain models.

Devices, links, and a topology that enforces referential integrity between
links and devices. Device types and roles are enumerated so downstream
engineering logic can branch on stable categories.
"""

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class DeviceType(str, Enum):
    """Categories of network equipment a device can be."""

    router = "router"  # Forwards packets between IP subnets.
    switch = "switch"  # Forwards frames at layer 2.
    layer3_switch = "layer3_switch"  # Switch with routing capability.
    firewall = "firewall"  # Enforces security policy between zones.
    load_balancer = "load_balancer"  # Distributes traffic across servers.
    access_point = "access_point"  # Wireless LAN access point.
    server = "server"  # Endpoint providing a service.
    host = "host"  # Endpoint consuming a service.
    controller = "controller"  # Manages other devices (e.g. SDN controller).
    modem = "modem"  # Modulates a carrier (e.g. WAN modem).


class DeviceRole(str, Enum):
    """Role a device plays in the network hierarchy."""

    core = "core"  # Backbone, highest-tier switching/routing.
    distribution = "distribution"  # Aggregates access switches.
    aggregation = "aggregation"  # Aggregation point (alias-family of distribution).
    access = "access"  # Edge switch facing endpoints.
    border = "border"  # Inter-domain boundary device.
    edge = "edge"  # Outermost user-facing edge.
    wan = "wan"  # WAN-facing device.
    dmz = "dmz"  # Demilitarized zone device.


class Device(BaseModel):
    """A single network device in a topology.

    ``site`` is stored as the id of the :class:`~core.schemas.organization.Site`
    that hosts the device (kept as a plain string here to avoid importing the
    organization layer into the network layer).
    """

    id: str = Field(description="Unique identifier for the device within the topology.")
    type: DeviceType = Field(description="Equipment category of the device.")
    site: str = Field(description="Id of the site that hosts this device.")
    role: DeviceRole = Field(description="Hierarchical role of the device.")


class Link(BaseModel):
    """A network link connecting two devices.

    ``endpoints`` is an unordered pair for undirected links and an ordered
    pair when ``directed`` is true. ``capacity_mbps`` and ``cost`` must be
    strictly positive.
    """

    id: str = Field(description="Unique identifier for the link within the topology.")
    endpoints: tuple[str, str] = Field(
        description="The two device ids this link connects (exactly two, distinct).",
    )
    capacity_mbps: float = Field(
        description="Link capacity in megabits per second (must be > 0).",
        gt=0,
    )
    cost: float = Field(
        description="Link cost metric used by routing/optimization (must be > 0).",
        gt=0,
    )
    directed: bool = Field(
        default=False,
        description="Whether the link is directed (endpoints are ordered).",
    )

    @field_validator("endpoints")
    @classmethod
    def _validate_endpoints(cls, endpoints: tuple[str, str]) -> tuple[str, str]:
        """Reject links that don't have exactly two distinct endpoints."""
        if len(endpoints) != 2:
            raise ValueError(
                f"A link must have exactly two endpoints, got {len(endpoints)}"
            )
        if endpoints[0] == endpoints[1]:
            raise ValueError(
                f"A link cannot connect a device to itself: {endpoints[0]!r}"
            )
        return endpoints


class Topology(BaseModel):
    """A network topology: its devices and the links between them.

    Enforces referential integrity: device ids must be unique, link ids must
    be unique, and every link endpoint must reference an existing device.
    """

    name: str = Field(description="Human-readable topology name.")
    devices: list[Device] = Field(
        default_factory=list,
        description="Devices in the topology.",
    )
    links: list[Link] = Field(
        default_factory=list,
        description="Links between devices in the topology.",
    )

    @model_validator(mode="after")
    def _reject_invalid_topology(self) -> "Topology":
        """Reject duplicate device ids, duplicate link ids, and dangling endpoints."""
        device_ids: set[str] = set()
        for device in self.devices:
            if device.id in device_ids:
                raise ValueError(f"Duplicate device id: {device.id!r}")
            device_ids.add(device.id)

        link_ids: set[str] = set()
        for link in self.links:
            if link.id in link_ids:
                raise ValueError(f"Duplicate link id: {link.id!r}")
            link_ids.add(link.id)
            for endpoint in link.endpoints:
                if endpoint not in device_ids:
                    raise ValueError(
                        f"Link {link.id!r} references unknown device {endpoint!r}"
                    )
        return self
