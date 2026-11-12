"""Organization domain models.

Models describing the organizational hierarchy that owns and consumes the
network: a single :class:`Organization` containing :class:`Site` instances,
each of which contains :class:`Department` instances with a user count.
"""

from pydantic import BaseModel, Field, model_validator


class Department(BaseModel):
    """A department within a site that has network users.

    ``user_count`` is non-negative because a department may legitimately have
    zero users today (for example a planned or dormant department).
    """

    id: str = Field(description="Unique identifier for the department within its site.")
    name: str = Field(description="Human-readable department name.")
    user_count: int = Field(
        description="Number of network users in the department (non-negative).",
        ge=0,
    )


class Site(BaseModel):
    """A physical site (office, campus, data center) of an organization.

    A site groups departments and carries an optional location label.
    """

    id: str = Field(description="Unique identifier for the site within its organization.")
    name: str = Field(description="Human-readable site name.")
    location: str | None = Field(
        default=None,
        description="Optional free-form location label (city, address, region).",
    )
    departments: list[Department] = Field(
        default_factory=list,
        description="Departments located at this site.",
    )

    @model_validator(mode="after")
    def _reject_duplicate_department_ids(self) -> "Site":
        """Reject duplicate department ids within this site."""
        seen: set[str] = set()
        for department in self.departments:
            if department.id in seen:
                raise ValueError(
                    f"Duplicate department id within site: {department.id!r}"
                )
            seen.add(department.id)
        return self


class Organization(BaseModel):
    """The top-level organization that owns the network.

    An organization groups sites. Department ids must be unique both within
    a site (enforced by :class:`Site`) and across the whole organization
    (enforced here).
    """

    id: str = Field(description="Unique identifier for the organization.")
    name: str = Field(description="Human-readable organization name.")
    sites: list[Site] = Field(
        default_factory=list,
        description="Sites belonging to this organization.",
    )

    @model_validator(mode="after")
    def _reject_duplicate_ids(self) -> "Organization":
        """Reject duplicate site ids and duplicate department ids across the org."""
        seen_sites: set[str] = set()
        seen_departments: set[str] = set()
        for site in self.sites:
            if site.id in seen_sites:
                raise ValueError(f"Duplicate site id: {site.id!r}")
            seen_sites.add(site.id)
            for department in site.departments:
                if department.id in seen_departments:
                    raise ValueError(
                        f"Duplicate department id across organization: {department.id!r}"
                    )
                seen_departments.add(department.id)
        return self
