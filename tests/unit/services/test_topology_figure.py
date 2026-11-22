"""Vector topology figure tests (task B3)."""

from __future__ import annotations

from reportlab.graphics.shapes import String
from reportlab.platypus import Flowable

from core.schemas.network import (
    Device,
    DeviceRole,
    DeviceType,
    Link,
    Topology,
)
from services.export.pdf import pdf_page_count
from services.export.topology_figure import (
    topology_figure,
    topology_figure_pdf,
    topology_flowable,
)
from tests.unit.digital_twin.helpers import make_twin


def _texts(flowable: Flowable) -> list[str]:
    return [
        shape.text
        for shape in flowable.contents
        if isinstance(shape, String)
    ]


def test_flowable_and_pdf_are_deterministic() -> None:
    twin = make_twin()
    flowable = topology_flowable(twin)
    assert isinstance(flowable, Flowable)
    assert flowable.width == 520.0
    assert flowable.height <= 260.0
    data = topology_figure_pdf(twin)
    assert data.startswith(b"%PDF")
    assert pdf_page_count(data) >= 1
    assert topology_figure_pdf(twin) == data
    assert topology_figure(twin) == data


def test_hostile_arabic_and_markup_names_do_not_crash() -> None:
    twin = make_twin()
    hostile_id = '<device&"路由器>'
    devices = [
        *twin.topology.devices,
        Device(
            id=hostile_id,
            type=DeviceType.router,
            site="hq",
            role=DeviceRole.border,
        ),
    ]
    links = [
        *twin.topology.links,
        Link(
            id='link<&"الموجه>',
            endpoints=(hostile_id, "r1"),
            capacity_mbps=1000.0,
            cost=1.0,
            directed=True,
        ),
    ]
    topology = twin.topology.model_copy(update={"devices": devices, "links": links})
    hostile = twin.model_copy(update={"topology": topology})
    flowable = topology_flowable(hostile, language="ar")
    assert flowable.height <= 260.0
    assert topology_figure_pdf(hostile, language="ar").startswith(b"%PDF")


def test_empty_topology_has_an_empty_caption() -> None:
    twin = make_twin()
    empty = twin.model_copy(
        update={
            "topology": Topology(name="empty", devices=[], links=[]),
        }
    )
    flowable = topology_flowable(empty)
    assert any("Empty topology" in text for text in _texts(flowable))
    assert any("Legend" in text for text in _texts(flowable))
    data = topology_figure_pdf(empty)
    assert data.startswith(b"%PDF")
    assert pdf_page_count(data) >= 1


def test_large_topology_thins_labels_and_stays_bounded() -> None:
    twin = make_twin()
    devices = [
        Device(
            id=f"device-{index}",
            type=DeviceType.switch,
            site="hq",
            role=DeviceRole.access,
        )
        for index in range(18)
    ]
    links = [
        Link(
            id=f"link-{index}",
            endpoints=(devices[index].id, devices[index + 1].id),
            capacity_mbps=1000.0,
            cost=1.0,
            directed=index % 2 == 0,
        )
        for index in range(17)
    ]
    topology = twin.topology.model_copy(update={"devices": devices, "links": links})
    large = twin.model_copy(update={"topology": topology})
    flowable = topology_flowable(large, max_height=180.0)
    assert flowable.height <= 180.0
    assert any(text.startswith("Showing ") for text in _texts(flowable))
    data = topology_figure_pdf(large, max_height=180.0)
    assert data.startswith(b"%PDF")
    assert pdf_page_count(data) >= 1
    assert topology_figure_pdf(large, max_height=180.0) == data
