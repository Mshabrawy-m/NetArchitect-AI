"""Typed inputs for the modeled WAN and multi-site design package.

These are design-time classifications and cost proxies. They do not represent a
carrier circuit, an active measurement, or a vendor quote.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.limits import MAX_WAN_DESIGN_SITES
from core.schemas.enums import SiteType, WanLinkType


class WanDesign(BaseModel):
    """Designer-supplied site facts stored additively on a digital twin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    site_types: dict[str, SiteType] = Field(
        default_factory=dict,
        description="Modeled site type keyed by the site id used by devices.",
    )
    hq_site_ids: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Sites that branches must be able to reach in the model.",
    )

    @field_validator("site_types")
    @classmethod
    def _validate_sites(cls, value: dict[str, SiteType]) -> dict[str, SiteType]:
        if len(value) > MAX_WAN_DESIGN_SITES:
            raise ValueError(
                f"WAN design has {len(value)} sites; the limit is "
                f"{MAX_WAN_DESIGN_SITES}."
            )
        if any(not key for key in value):
            raise ValueError("WAN site ids must be non-empty.")
        return dict(value)

    @field_validator("hq_site_ids")
    @classmethod
    def _validate_hq(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item for item in value):
            raise ValueError("HQ site ids must be non-empty.")
        return tuple(sorted(set(value)))


__all__ = ["SiteType", "WanDesign", "WanLinkType"]
