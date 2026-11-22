"""Typed inputs for the modeled Layer-2 switching design package.

Nothing in this module configures equipment or simulates a protocol. The models
describe designer intent and documented assumptions for deterministic,
hand-checkable design rules.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from config.limits import (
    DEFAULT_VLAN_SPREAD_SWITCHES,
    MAX_ETHERCHANNEL_BUNDLES,
    MAX_ETHERCHANNEL_MEMBERS,
)

# Keep these literals local so importing this schema module never triggers the
# addressing/VLAN package import chain. They match ``network.vlan.plan``.
VLAN_ID_MIN = 1
VLAN_ID_MAX = 4094


class LinkL2Mode(str, Enum):
    """Modeled switch-port style for one topology link."""

    access = "access"  # A single untagged VLAN faces endpoints.
    trunk = "trunk"  # An allowed VLAN list crosses the link.


class EtherChannelBundle(BaseModel):
    """A deterministic logical grouping of parallel modeled links."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, description="Stable bundle identifier.")
    name: str = Field(default="", description="Optional human-readable label.")
    link_ids: tuple[str, ...] = Field(
        description="Member link ids; order is canonicalized by sorting.",
    )
    rationale: str = Field(
        default="Modeled parallel-link bundle.",
        description="Why these links are treated as one logical link.",
    )

    @model_validator(mode="before")
    @classmethod
    def _canonicalize(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        link_ids = tuple(sorted({str(item) for item in data.get("link_ids", ())}))
        identifier = str(data.get("id", ""))
        return {
            **data,
            "name": data.get("name") or identifier,
            "link_ids": link_ids,
            "rationale": data.get("rationale") or "Modeled parallel-link bundle.",
        }

    @field_validator("link_ids")
    @classmethod
    def _validate_members(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("An EtherChannel bundle needs at least one member link.")
        if len(value) > MAX_ETHERCHANNEL_MEMBERS:
            raise ValueError(
                f"Bundle has {len(value)} members; the limit is "
                f"{MAX_ETHERCHANNEL_MEMBERS}."
            )
        return value


class L2Design(BaseModel):
    """Designer-supplied Layer-2 facts stored additively on a digital twin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gateway_by_vlan: dict[int, str] = Field(
        default_factory=dict,
        description="Modeled default-gateway device id for each VLAN.",
    )
    root_priorities: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Documented root-bridge priority per switch. Lower wins; ties are "
            "broken by device id. Unlisted switches use the default priority."
        ),
    )
    vlan_spread_threshold: int = Field(
        default=DEFAULT_VLAN_SPREAD_SWITCHES,
        ge=1,
        description="Documented heuristic switch count before VLAN sprawl warns.",
    )
    etherchannel_bundles: tuple[EtherChannelBundle, ...] = Field(
        default_factory=tuple,
        description="Modeled parallel-link bundles over existing topology links.",
    )

    @field_validator("gateway_by_vlan")
    @classmethod
    def _validate_gateways(cls, value: dict[int, str]) -> dict[int, str]:
        for vlan_id, device_id in value.items():
            if not VLAN_ID_MIN <= vlan_id <= VLAN_ID_MAX:
                raise ValueError(
                    f"Gateway VLAN {vlan_id} is outside {VLAN_ID_MIN}..{VLAN_ID_MAX}."
                )
            if not device_id:
                raise ValueError("Gateway device ids must be non-empty.")
        return dict(value)

    @field_validator("root_priorities")
    @classmethod
    def _validate_priorities(cls, value: dict[str, int]) -> dict[str, int]:
        for device_id, priority in value.items():
            if not device_id:
                raise ValueError("Root-priority device ids must be non-empty.")
            if priority < 0:
                raise ValueError(f"Root priority for {device_id!r} must be >= 0.")
        return dict(value)

    @field_validator("etherchannel_bundles")
    @classmethod
    def _validate_bundles(
        cls, value: tuple[EtherChannelBundle, ...]
    ) -> tuple[EtherChannelBundle, ...]:
        if len(value) > MAX_ETHERCHANNEL_BUNDLES:
            raise ValueError(
                f"Twin has {len(value)} bundles; the limit is "
                f"{MAX_ETHERCHANNEL_BUNDLES}."
            )
        ids = [bundle.id for bundle in value]
        if len(ids) != len(set(ids)):
            raise ValueError("EtherChannel bundle ids must be unique.")
        return value


__all__ = ["EtherChannelBundle", "L2Design", "LinkL2Mode"]
