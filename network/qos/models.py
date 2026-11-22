"""Typed inputs for modeled QoS traffic classes and admission rules.

This is an admission model, not a queueing simulator. It classifies designer-
supplied demands and applies documented class priority and optional per-link
share caps; it does not model queues, drops, schedulers, or device hardware.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from config.limits import MAX_QOS_CLASS_CAPS


class TrafficClass(str, Enum):
    """Modeled strict-priority order; lower priority numbers are served first."""

    voice = "voice"
    video = "video"
    critical = "critical"
    best_effort = "best_effort"


TRAFFIC_CLASS_PRIORITY: dict[TrafficClass, int] = {
    TrafficClass.voice: 0,
    TrafficClass.video: 1,
    TrafficClass.critical: 2,
    TrafficClass.best_effort: 3,
}


class ClassShareCap(BaseModel):
    """Optional modeled cap on one class's share of one link's capacity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link_id: str = Field(min_length=1, description="Existing topology link id.")
    traffic_class: TrafficClass = Field(description="Class whose share is capped.")
    share_cap: float = Field(
        gt=0,
        le=1,
        description="Fraction of link capacity this class may consume (0..1].",
    )


class QosDesign(BaseModel):
    """Designer-supplied QoS facts stored additively on a digital twin."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    default_class: TrafficClass = Field(
        default=TrafficClass.best_effort,
        description="Class used when a demand has no explicit modeled class.",
    )
    class_share_caps: tuple[ClassShareCap, ...] = Field(default_factory=tuple)

    @field_validator("class_share_caps")
    @classmethod
    def _validate_caps(
        cls, value: tuple[ClassShareCap, ...]
    ) -> tuple[ClassShareCap, ...]:
        if len(value) > MAX_QOS_CLASS_CAPS:
            raise ValueError(
                f"QoS design has {len(value)} caps; the limit is {MAX_QOS_CLASS_CAPS}."
            )
        keys = [(cap.link_id, cap.traffic_class) for cap in value]
        if len(keys) != len(set(keys)):
            raise ValueError("QoS class-share cap keys must be unique.")
        return value


__all__ = [
    "TRAFFIC_CLASS_PRIORITY",
    "ClassShareCap",
    "QosDesign",
    "TrafficClass",
]
