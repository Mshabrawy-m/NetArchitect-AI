"""Typed inputs for abstract wireless capacity and coverage planning.

This package deliberately has NO RF propagation model. Coverage uses only a
documented circular-area assumption; capacity uses a per-client Mbps assumption.
Every output is a modeled estimate, not a signal or site-survey prediction.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.limits import MAX_WIRELESS_AREAS

DEFAULT_CLIENT_MBPS = 10.0
DEFAULT_AP_CAPACITY_MBPS = 100.0
DEFAULT_COVERAGE_RADIUS_M = 20.0
DEFAULT_UTILIZATION_TARGET = 0.7
DEFAULT_OVERLAP_FACTOR = 0.8
DEFAULT_CLIENT_DENSITY_PER_100M2 = 20.0


class WirelessArea(BaseModel):
    """One abstract area whose AP count is estimated from explicit assumptions."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, description="Stable area identifier.")
    name: str = Field(default="", description="Optional human-readable label.")
    area_m2: float = Field(default=0.0, ge=0, description="Modeled floor area in m2.")
    clients: int = Field(default=0, ge=0, description="Explicit modeled client count.")
    client_density_per_100m2: float = Field(
        default=DEFAULT_CLIENT_DENSITY_PER_100M2,
        ge=0,
        description="Assumed clients per 100 m2 when clients is not supplied.",
    )
    client_mbps: float = Field(
        default=DEFAULT_CLIENT_MBPS,
        gt=0,
        description="Assumed demand per client in Mbps (modeled estimate).",
    )
    ap_capacity_mbps: float = Field(
        default=DEFAULT_AP_CAPACITY_MBPS,
        gt=0,
        description="Assumed usable aggregate throughput per AP in Mbps.",
    )
    coverage_radius_m: float = Field(
        default=DEFAULT_COVERAGE_RADIUS_M,
        gt=0,
        description="Assumed circular coverage radius per AP in metres.",
    )
    utilization_target: float = Field(
        default=DEFAULT_UTILIZATION_TARGET,
        gt=0,
        le=1,
        description="Fraction of AP capacity reserved for planning headroom.",
    )
    overlap_factor: float = Field(
        default=DEFAULT_OVERLAP_FACTOR,
        gt=0,
        le=1,
        description="Fraction of circle area credited after modeled overlap.",
    )
    uplink_switch_id: str | None = Field(
        default=None,
        description="Optional switch id whose uplink must serve this area's APs.",
    )

    @model_validator(mode="before")
    @classmethod
    def _fill_name(cls, data: object) -> object:
        if isinstance(data, dict) and not data.get("name"):
            return {**data, "name": str(data.get("id", ""))}
        return data


class WirelessDesign(BaseModel):
    """Bounded collection of abstract wireless areas stored on a twin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    areas: tuple[WirelessArea, ...] = Field(default_factory=tuple)

    @field_validator("areas")
    @classmethod
    def _validate_areas(cls, value: tuple[WirelessArea, ...]) -> tuple[WirelessArea, ...]:
        if len(value) > MAX_WIRELESS_AREAS:
            raise ValueError(
                f"Wireless design has {len(value)} areas; the limit is "
                f"{MAX_WIRELESS_AREAS}."
            )
        ids = [area.id for area in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Wireless area ids must be unique.")
        return value


__all__ = [
    "DEFAULT_AP_CAPACITY_MBPS",
    "DEFAULT_CLIENT_DENSITY_PER_100M2",
    "DEFAULT_CLIENT_MBPS",
    "DEFAULT_COVERAGE_RADIUS_M",
    "DEFAULT_OVERLAP_FACTOR",
    "DEFAULT_UTILIZATION_TARGET",
    "WirelessArea",
    "WirelessDesign",
]
