"""Reproducible Phase 12 performance and memory profile.

This script is not part of the application. It measures the expensive operations
the UI can trigger at the configured limits so the defaults can be justified with
real numbers. Run it from the repository root:

    .venv\\Scripts\\python.exe scripts\\profile_phase12.py

The numbers include tracemalloc overhead; rerun with ``--no-memory`` for
wall-clock numbers without tracing. Every measured operation is deterministic:
the topology and optimization seeds are fixed.
"""

from __future__ import annotations

import argparse
import gc
import sys
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.limits import (
    MAX_DEMANDS,
    MAX_EVALUATIONS,
    MAX_OPTIMIZATION_ITERATIONS,
    MAX_OPTIMIZATION_RUNTIME_SECONDS,
    MAX_POPULATION,
    MAX_SUBNETS,
)
from core.schemas.addressing import AddressingPlan, DhcpScope, Subnet
from core.schemas.routing import TrafficDemand
from digital_twin import DigitalTwin, TwinMetadata
from network.routing import reachability_matrix
from network.topology import generate_hierarchical_campus
from network.vlan import VlanAssignment, VlanPlanResult
from optimization import (
    Algorithm,
    ObjectiveKind,
    ObjectiveSpec,
    OptimizationSettings,
    run_optimization,
)
from services.export import to_pdf
from services.reporting import ReportSources, build_report
from simulation import evaluate

FIXED_TIME = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)
TIME_BUDGET_SECONDS = 5.0
MEMORY_BUDGET_MIB = 300.0


@dataclass(frozen=True)
class Measurement:
    """One measured operation."""

    name: str
    seconds: float
    peak_mib: float
    note: str = ""


def _measure(
    name: str,
    action: Callable[[], Any],
    *,
    memory: bool = True,
    note: str = "",
) -> tuple[Any, Measurement]:
    gc.collect()
    if memory:
        tracemalloc.start()
    started = time.perf_counter()
    result: Any = None
    try:
        result = action()
    except Exception as error:  # noqa: BLE001 - the profile reports real failures
        note = "; ".join(
            part
            for part in (note, f"{type(error).__name__}: {error}")
            if part
        )
    seconds = time.perf_counter() - started
    peak_mib = 0.0
    if memory:
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        peak_mib = peak_bytes / (1024 * 1024)
    return result, Measurement(name, seconds, peak_mib, note)


def _max_topology():
    return generate_hierarchical_campus(
        name="Phase 12 profile campus",
        distribution_count=3,
        access_per_distribution=165,
        redundant_uplinks=True,
        id_prefix="profile",
    )


def _max_twin(topology) -> DigitalTwin:
    access_ids = sorted(
        device.id for device in topology.devices if device.role.value == "access"
    )
    subnet_count = min(MAX_SUBNETS, 256)
    subnets = [
        Subnet(name=f"profile-subnet-{index:03d}", network=f"10.0.{index}.0/24")
        for index in range(subnet_count)
    ]
    vlan_assignments = [
        VlanAssignment(
            department=f"department-{index:03d}",
            vlan_id=10 + index,
            vlan_name=f"Dept {index:03d}",
            subnet_name=subnet.name,
            network=subnet.network,
            purpose="Profile workload",
        )
        for index, subnet in enumerate(subnets)
    ]
    demands = tuple(
        TrafficDemand(
            name=f"profile-demand-{index:03d}",
            source=access_ids[index % len(access_ids)],
            destination=access_ids[(index * 37 + 1) % len(access_ids)],
            bandwidth_mbps=10.0,
            priority=1,
        )
        for index in range(MAX_DEMANDS)
    )
    return DigitalTwin(
        metadata=TwinMetadata(
            name="Phase 12 profile twin",
            created_at=FIXED_TIME,
        ),
        topology=topology,
        addressing=AddressingPlan(subnets=subnets),
        vlan_plan=VlanPlanResult(assignments=vlan_assignments),
        dhcp_scopes=(
            DhcpScope(
                name="profile DHCP",
                network="10.0.0.0/24",
                gateway="10.0.0.1",
                start_address="10.0.0.10",
                end_address="10.0.0.200",
            ),
        ),
        demands=demands,
    )


def _optimization_settings() -> OptimizationSettings:
    return OptimizationSettings(
        objectives=(
            ObjectiveSpec(
                kind=ObjectiveKind.max_utilization,
                weight=0.5,
                lower_bound=0.0,
                upper_bound=200.0,
            ),
            ObjectiveSpec(
                kind=ObjectiveKind.mean_path_cost,
                weight=0.5,
                lower_bound=0.0,
                upper_bound=100.0,
            ),
        ),
        seed=42,
        population_size=MAX_POPULATION,
        max_iterations=MAX_OPTIMIZATION_ITERATIONS,
        max_evaluations=MAX_EVALUATIONS,
        max_runtime_seconds=MAX_OPTIMIZATION_RUNTIME_SECONDS,
    )


def _print_table(measurements: list[Measurement], *, memory: bool) -> None:
    print()
    print("| operation | seconds | peak MiB | over budget | note |")
    print("| --- | ---: | ---: | :---: | --- |")
    for item in measurements:
        if memory:
            over = "yes" if item.peak_mib > MEMORY_BUDGET_MIB else "no"
            timing_note = "timing includes tracemalloc overhead"
        else:
            over = "yes" if item.seconds > TIME_BUDGET_SECONDS else "no"
            timing_note = ""
        note = "; ".join(
            part for part in (item.note, timing_note) if part
        ).replace("|", "/")
        print(
            f"| {item.name} | {item.seconds:.3f} | {item.peak_mib:.1f} | "
            f"{over} | {note} |"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-memory",
        action="store_true",
        help="Skip tracemalloc (wall-clock numbers only).",
    )
    parser.add_argument(
        "--skip-optimization",
        action="store_true",
        help="Skip the two bounded optimization runs.",
    )
    args = parser.parse_args()
    memory = not args.no_memory

    measurements: list[Measurement] = []
    topology, measurement = _measure("generate max-size topology", _max_topology, memory=memory)
    measurements.append(measurement)
    if topology is None:
        _print_table(measurements, memory=memory)
        return 1

    twin, measurement = _measure("build max twin", lambda: _max_twin(topology), memory=memory)
    measurements.append(measurement)
    if twin is None:
        _print_table(measurements, memory=memory)
        return 1

    _, measurement = _measure(
        "all-pairs routing",
        lambda: reachability_matrix(topology),
        memory=memory,
    )
    measurements.append(measurement)

    _, measurement = _measure("evaluate with MAX_DEMANDS", lambda: evaluate(twin), memory=memory)
    measurements.append(measurement)

    if not args.skip_optimization:
        settings = _optimization_settings()
        for algorithm in (Algorithm.genetic, Algorithm.nsga2):
            _, measurement = _measure(
                f"{algorithm.value} at configured maxima",
                lambda algorithm=algorithm: run_optimization(twin, settings, algorithm),
                memory=memory,
                note=(
                    "user-triggered search; wall clock is bounded by "
                    f"MAX_OPTIMIZATION_RUNTIME_SECONDS="
                    f"{MAX_OPTIMIZATION_RUNTIME_SECONDS}"
                ),
            )
            measurements.append(measurement)

    document, measurement = _measure(
        "report build",
        lambda: build_report(ReportSources(twin=twin, generated_at=FIXED_TIME)),
        memory=memory,
    )
    measurements.append(measurement)

    if document is not None:
        _, measurement = _measure("PDF build", lambda: to_pdf(document), memory=memory)
        measurements.append(measurement)

    _print_table(measurements, memory=memory)
    print()
    print(
        "Budget threshold: >5 s in a --no-memory run, or >300 MiB in a "
        "tracemalloc run, is flagged. Tracemalloc adds time overhead and "
        "records Python allocations, not total process RSS. Run with "
        "--no-memory for wall-clock numbers."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
