"""Address utilization reporting.

Utilization is computed from prefix arithmetic, not host enumeration. All
counts are integers; percentages are rounded to two decimal places so reports
are stable across runs.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, Field, model_validator

from core.schemas.addressing import NetworkType
from network.addressing.cidr import IPNetwork, calculate_subnet, coerce_network


class UtilizationEntry(BaseModel):
    """One subnet with the number of addresses currently in use."""

    name: str = Field(min_length=1)
    network: NetworkType
    used_addresses: int = Field(ge=0)


class SubnetUtilization(BaseModel):
    """Utilization for one subnet."""

    name: str
    network: NetworkType
    total_addresses: int = Field(ge=1)
    usable_addresses: int = Field(ge=0)
    used_addresses: int = Field(ge=0)
    remaining_addresses: int = Field(ge=0)
    utilization_percent: float = Field(ge=0.0)


class UtilizationReport(BaseModel):
    """Per-subnet utilization plus totals for the parent block, if given."""

    subnets: list[SubnetUtilization] = Field(default_factory=list)
    total_addresses: int = Field(default=0, ge=0)
    usable_addresses: int = Field(default=0, ge=0)
    used_addresses: int = Field(default=0, ge=0)
    remaining_addresses: int = Field(default=0, ge=0)
    utilization_percent: float = Field(default=0.0, ge=0.0)
    parent: NetworkType | None = None
    parent_total_addresses: int | None = Field(default=None, ge=1)
    parent_used_addresses: int | None = Field(default=None, ge=0)
    parent_remaining_addresses: int | None = Field(default=None, ge=0)
    parent_utilization_percent: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def _parent_fields_are_consistent(self) -> UtilizationReport:
        values = (
            self.parent_total_addresses,
            self.parent_used_addresses,
            self.parent_remaining_addresses,
            self.parent_utilization_percent,
        )
        if self.parent is None and any(value is not None for value in values):
            raise ValueError("Parent utilization requires a parent network")
        if self.parent is not None and any(value is None for value in values):
            raise ValueError("Parent network requires complete parent utilization")
        return self


def _percent(used: int, total: int) -> float:
    return round(100.0 * used / total, 2) if total else 0.0


def build_utilization_report(
    entries: Sequence[UtilizationEntry],
    *,
    parent: str | IPNetwork | None = None,
) -> UtilizationReport:
    """Build utilization rows and totals.

    ``used_addresses`` counts the addresses in use inside each entry; it may
    not exceed that subnet's usable host count. When ``parent`` is supplied,
    every entry must lie inside it and parent totals are reported as well.
    """
    parent_network = coerce_network(parent) if parent is not None else None
    rows: list[SubnetUtilization] = []

    for entry in entries:
        info = calculate_subnet(entry.network, name=entry.name)
        if info.usable_host_count == 0 and entry.used_addresses:
            raise ValueError(
                f"Subnet {entry.name!r} has no usable host addresses but reports "
                f"{entry.used_addresses} in use"
            )
        if entry.used_addresses > info.usable_host_count:
            raise ValueError(
                f"Subnet {entry.name!r} reports {entry.used_addresses} addresses "
                f"in use but only {info.usable_host_count} are usable"
            )
        if parent_network is not None:
            if info.version != parent_network.version:
                raise ValueError(
                    f"Subnet {entry.name!r} is IPv{info.version} but the parent "
                    f"is IPv{parent_network.version}"
                )
            if not info.network.subnet_of(parent_network):
                raise ValueError(
                    f"Subnet {entry.name!r} ({info.network}) is not inside parent "
                    f"{parent_network}"
                )
        rows.append(
            SubnetUtilization(
                name=entry.name,
                network=info.network,
                total_addresses=info.total_addresses,
                usable_addresses=info.usable_host_count,
                used_addresses=entry.used_addresses,
                remaining_addresses=info.usable_host_count - entry.used_addresses,
                utilization_percent=_percent(
                    entry.used_addresses, info.usable_host_count
                ),
            )
        )

    total = sum(row.total_addresses for row in rows)
    usable = sum(row.usable_addresses for row in rows)
    used = sum(row.used_addresses for row in rows)
    remaining = usable - used

    report = UtilizationReport(
        subnets=rows,
        total_addresses=total,
        usable_addresses=usable,
        used_addresses=used,
        remaining_addresses=remaining,
        utilization_percent=_percent(used, usable),
    )
    if parent_network is not None:
        report.parent = parent_network
        report.parent_total_addresses = parent_network.num_addresses
        report.parent_used_addresses = used
        report.parent_remaining_addresses = parent_network.num_addresses - used
        report.parent_utilization_percent = _percent(
            used, parent_network.num_addresses
        )
    return report
