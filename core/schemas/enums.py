"""Shared enumerations owned by the core domain layer.

The layer-2, QoS, WAN, and digital-twin modules re-export these exact enum
objects so legacy import paths keep working. Member names, values, and
serialization are unchanged.
"""

from enum import Enum


class LinkL2Mode(str, Enum):
    """Modeled switch-port style for one topology link."""

    access = "access"  # A single untagged VLAN faces endpoints.
    trunk = "trunk"  # An allowed VLAN list crosses the link.


class WanLinkType(str, Enum):
    """Modeled WAN circuit category attached to an existing topology link."""

    leased = "leased"
    mpls = "mpls"
    internet_vpn = "internet_vpn"
    cloud_interconnect = "cloud_interconnect"


class SiteType(str, Enum):
    """Modeled role of a site in the WAN design."""

    hq = "hq"
    branch = "branch"
    dc = "dc"
    cloud = "cloud"


class TrafficClass(str, Enum):
    """Modeled strict-priority order; lower priority numbers are served first."""

    voice = "voice"
    video = "video"
    critical = "critical"
    best_effort = "best_effort"


class OperationalState(str, Enum):
    """Modeled operational state of one device or link."""

    up = "up"  # The entity participates in the modeled network.
    down = "down"  # The entity is modeled as failed and must be excluded.


__all__ = [
    "LinkL2Mode",
    "OperationalState",
    "SiteType",
    "TrafficClass",
    "WanLinkType",
]
