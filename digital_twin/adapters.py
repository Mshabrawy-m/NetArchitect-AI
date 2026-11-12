"""Thin adapters that feed a digital twin into the routing/analysis engines.

The engines stay topology-based. These adapters extract the twin's topology and
the ids whose effective state is ``down``; stale state entries that reference
removed entities are listed separately and are *not* passed to the engines,
because the engines correctly reject unknown failure ids. Validation reports
those stale entries.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import DigitalTwin, OperationalState
from .validation import validate_twin


@dataclass(frozen=True)
class FailureSelection:
    """Known failed entities, plus stale state entries kept out of engines."""

    devices: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    stale_devices: tuple[str, ...] = ()
    stale_links: tuple[str, ...] = ()

    @property
    def has_failures(self) -> bool:
        """Return whether any known device or link is modeled as down."""
        return bool(self.devices or self.links)

    def as_kwargs(self) -> dict[str, tuple[str, ...]]:
        """Return engine keyword arguments for the known failure ids."""
        return {"failed_devices": self.devices, "failed_links": self.links}


def failed_entities(twin: DigitalTwin) -> FailureSelection:
    """Extract known and stale failed entity ids from twin state."""
    device_ids = {device.id for device in twin.topology.devices}
    link_ids = {link.id for link in twin.topology.links}

    down_devices = sorted(
        entry.device_id
        for entry in twin.device_states
        if entry.state is OperationalState.down
    )
    down_links = sorted(
        entry.link_id
        for entry in twin.link_states
        if entry.state is OperationalState.down
    )
    return FailureSelection(
        devices=tuple(
            device_id for device_id in down_devices if device_id in device_ids
        ),
        links=tuple(link_id for link_id in down_links if link_id in link_ids),
        stale_devices=tuple(
            device_id for device_id in down_devices if device_id not in device_ids
        ),
        stale_links=tuple(
            link_id for link_id in down_links if link_id not in link_ids
        ),
    )


def routing_arguments(twin: DigitalTwin) -> dict[str, object]:
    """Return keyword arguments accepted by the routing engine."""
    return {
        "topology": twin.topology,
        **failed_entities(twin).as_kwargs(),
    }


def analysis_arguments(twin: DigitalTwin) -> dict[str, object]:
    """Return keyword arguments accepted by the structural analysis engine."""
    return {
        "topology": twin.topology,
        **failed_entities(twin).as_kwargs(),
    }


def validate_engine_twin(twin: DigitalTwin) -> None:
    """Raise ``ValueError`` when stale state would make engine input ambiguous.

    Engines ignore stale state through :func:`failed_entities`, so this helper
    is optional. Callers use it when they want to refuse to run until the twin
    is consistent.
    """
    report = validate_twin(twin)
    stale = [
        finding
        for finding in report.findings
        if finding.code
        in {
            "twin_unknown_device_state",
            "twin_unknown_link_state",
        }
    ]
    if stale:
        raise ValueError(
            "Twin has stale operational state; resolve it before running engines."
        )
