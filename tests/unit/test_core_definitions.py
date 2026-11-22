"""Shared definitions are core-owned and re-exported as the same objects."""

from __future__ import annotations

from core.constants import VLAN_ID_MAX, VLAN_ID_MIN
from core.schemas.enums import (
    LinkL2Mode,
    OperationalState,
    SiteType,
    TrafficClass,
    WanLinkType,
)
from digital_twin.models import OperationalState as TwinOperationalState
from network.l2.models import VLAN_ID_MAX as L2VlanIdMax
from network.l2.models import VLAN_ID_MIN as L2VlanIdMin
from network.l2.models import LinkL2Mode as L2LinkL2Mode
from network.qos.models import TrafficClass as QosTrafficClass
from network.vlan.plan import VLAN_ID_MAX as PlanVlanIdMax
from network.vlan.plan import VLAN_ID_MIN as PlanVlanIdMin
from network.wan.models import SiteType as WanSiteType
from network.wan.models import WanLinkType as WanCircuitType
from security.models import PolicyAction, SecurityModel, Service, Zone, ZoneType


def test_reexports_are_identical_objects() -> None:
    assert L2LinkL2Mode is LinkL2Mode
    assert QosTrafficClass is TrafficClass
    assert WanSiteType is SiteType
    assert WanCircuitType is WanLinkType
    assert TwinOperationalState is OperationalState
    assert L2VlanIdMin is VLAN_ID_MIN
    assert L2VlanIdMax is VLAN_ID_MAX
    assert PlanVlanIdMin is VLAN_ID_MIN
    assert PlanVlanIdMax is VLAN_ID_MAX


def test_enum_values_and_serialization_are_unchanged() -> None:
    assert [member.value for member in LinkL2Mode] == ["access", "trunk"]
    assert [member.value for member in WanLinkType] == [
        "leased",
        "mpls",
        "internet_vpn",
        "cloud_interconnect",
    ]
    assert [member.value for member in SiteType] == ["hq", "branch", "dc", "cloud"]
    assert [member.value for member in TrafficClass] == [
        "voice",
        "video",
        "critical",
        "best_effort",
    ]
    assert [member.value for member in OperationalState] == ["up", "down"]
    assert TrafficClass("voice") is TrafficClass.voice


def test_security_input_models_are_identical_objects() -> None:
    from core.schemas.security import PolicyAction as CorePolicyAction
    from core.schemas.security import SecurityModel as CoreSecurityModel
    from core.schemas.security import Service as CoreService
    from core.schemas.security import Zone as CoreZone
    from core.schemas.security import ZoneType as CoreZoneType

    assert CorePolicyAction is PolicyAction
    assert CoreSecurityModel is SecurityModel
    assert CoreService is Service
    assert CoreZone is Zone
    assert CoreZoneType is ZoneType
