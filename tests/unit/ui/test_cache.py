"""Tests for content-keyed UI caches."""

from __future__ import annotations

import pytest

from tests.unit.digital_twin.helpers import make_twin
from ui import cache
from ui.cache import (
    cached_design_health,
    source_payload,
    twin_cache_key,
    twin_payload,
)


def test_twin_cache_key_is_stable_for_one_twin_and_changes_with_content() -> None:
    twin = make_twin()
    same = make_twin()

    assert twin_cache_key(twin) == twin_cache_key(same)
    assert twin_payload(twin) == twin_payload(same)

    changed = twin.model_copy(
        update={"metadata": twin.metadata.model_copy(update={"name": "Renamed"})}
    )
    assert twin_cache_key(changed) != twin_cache_key(twin)
    assert twin_payload(changed) != twin_payload(twin)


def test_source_payload_is_empty_only_for_no_source() -> None:
    assert source_payload(None) == ""


def test_cached_design_health_is_reused_until_the_twin_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = cache.build_design_health

    def spy(twin, **kwargs):
        calls.append(twin.metadata.name)
        return original(twin, **kwargs)

    monkeypatch.setattr(cache, "build_design_health", spy)
    cached_design_health.clear()

    first = make_twin()
    payload = twin_payload(first)

    assert cached_design_health(payload, False).summary == "No design-health findings."
    assert cached_design_health(payload, False).summary == "No design-health findings."
    assert calls == [first.metadata.name]

    changed = first.model_copy(
        update={"metadata": first.metadata.model_copy(update={"name": "Other"})}
    )
    cached_design_health(twin_payload(changed), False)
    assert calls == [first.metadata.name, "Other"]
