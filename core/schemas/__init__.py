"""Public domain schema models for NetArchitect AI.

Re-exports the leaf models defined across the schema modules so callers can
import everything from ``core.schemas``. The custom IP types
(:data:`NetworkType`, :data:`AddressType`) are re-exported too because they
are used as field types by routing and other modules. The requirements models
(:class:`NetworkRequirements`, :class:`UserFacts`, :class:`Assumption`) are
re-exported as well.
"""

from .addressing import (
    AddressingPlan,
    AddressType,
    DhcpScope,
    NetworkType,
    Subnet,
    VlanPlan,
)
from .network import (
    Device,
    DeviceRole,
    DeviceType,
    Link,
    Topology,
)
from .optimization import (
    Constraint,
    ConstraintKind,
    Objective,
    ObjectiveDirection,
    OptimizationConfig,
)
from .organization import Department, Organization, Site
from .requirements import Assumption, NetworkRequirements, UserFacts
from .routing import RouteEntry, TrafficDemand
from .scenario import Scenario, ScenarioResult, ScenarioType
from .validation import Finding, Severity, ValidationReport

__all__ = [
    "AddressType",
    "AddressingPlan",
    "Assumption",
    "Constraint",
    "ConstraintKind",
    "Department",
    "Device",
    "DeviceRole",
    "DeviceType",
    "DhcpScope",
    "Finding",
    "Link",
    "NetworkRequirements",
    "NetworkType",
    "Objective",
    "ObjectiveDirection",
    "OptimizationConfig",
    "Organization",
    "RouteEntry",
    "Scenario",
    "ScenarioResult",
    "ScenarioType",
    "Severity",
    "Site",
    "Subnet",
    "Topology",
    "TrafficDemand",
    "UserFacts",
    "ValidationReport",
    "VlanPlan",
]
