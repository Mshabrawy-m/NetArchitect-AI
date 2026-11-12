"""Unit tests for ``core.schemas.organization``."""

import pytest
from pydantic import ValidationError

from core.schemas.organization import Department, Organization, Site


def _sample_department() -> Department:
    return Department(id="dept-1", name="Engineering", user_count=25)


def _sample_site() -> Site:
    return Site(id="site-1", name="HQ", departments=[_sample_department()])


def test_department_valid() -> None:
    dept = _sample_department()
    assert dept.user_count == 25


def test_department_zero_users_valid() -> None:
    dept = Department(id="dept-0", name="Empty", user_count=0)
    assert dept.user_count == 0


def test_department_negative_user_count_invalid() -> None:
    with pytest.raises(ValidationError):
        Department(id="dept-1", name="Engineering", user_count=-1)


def test_site_valid() -> None:
    site = _sample_site()
    assert site.departments[0].id == "dept-1"


def test_site_duplicate_department_id_invalid() -> None:
    with pytest.raises(ValidationError):
        Site(
            id="site-1",
            name="HQ",
            departments=[
                Department(id="dup", name="A", user_count=1),
                Department(id="dup", name="B", user_count=2),
            ],
        )


def test_organization_valid() -> None:
    org = Organization(id="org-1", name="Acme", sites=[_sample_site()])
    assert org.sites[0].id == "site-1"


def test_organization_duplicate_site_id_invalid() -> None:
    with pytest.raises(ValidationError):
        Organization(
            id="org-1",
            name="Acme",
            sites=[
                Site(id="dup-site", name="A"),
                Site(id="dup-site", name="B"),
            ],
        )


def test_organization_duplicate_department_across_sites_invalid() -> None:
    with pytest.raises(ValidationError):
        Organization(
            id="org-1",
            name="Acme",
            sites=[
                Site(
                    id="site-1",
                    name="A",
                    departments=[Department(id="dup", name="X", user_count=1)],
                ),
                Site(
                    id="site-2",
                    name="B",
                    departments=[Department(id="dup", name="Y", user_count=2)],
                ),
            ],
        )


def test_organization_json_round_trip() -> None:
    org = Organization(
        id="org-1",
        name="Acme",
        sites=[
            Site(
                id="site-1",
                name="HQ",
                location="NYC",
                departments=[
                    Department(id="dept-1", name="Engineering", user_count=25),
                    Department(id="dept-2", name="Sales", user_count=10),
                ],
            ),
        ],
    )
    restored = Organization.model_validate_json(org.model_dump_json())
    assert restored == org
