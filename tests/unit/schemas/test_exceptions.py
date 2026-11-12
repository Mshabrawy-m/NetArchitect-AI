"""Unit tests for the ``core.exceptions`` hierarchy."""

import pytest

import core.exceptions as exc


def test_netarchitect_error_is_exception() -> None:
    assert issubclass(exc.NetArchitectError, Exception)


def test_schema_errors_subclass_schema_error() -> None:
    assert issubclass(exc.DuplicateIdError, exc.SchemaError)
    assert issubclass(exc.MissingEndpointError, exc.SchemaError)
    assert issubclass(exc.OverlappingSubnetError, exc.SchemaError)
    assert issubclass(exc.InvalidVlanIdError, exc.SchemaError)


def test_schema_error_subclass_netarchitect_error() -> None:
    assert issubclass(exc.SchemaError, exc.NetArchitectError)


def test_runtime_errors_subclass_netarchitect_error() -> None:
    assert issubclass(exc.ConstraintViolationError, exc.NetArchitectError)
    assert issubclass(exc.LimitsExceededError, exc.NetArchitectError)
    assert issubclass(exc.ConfigError, exc.NetArchitectError)


@pytest.mark.parametrize(
    "error_cls",
    [
        exc.NetArchitectError,
        exc.SchemaError,
        exc.DuplicateIdError,
        exc.MissingEndpointError,
        exc.OverlappingSubnetError,
        exc.InvalidVlanIdError,
        exc.ConstraintViolationError,
        exc.LimitsExceededError,
        exc.ConfigError,
    ],
)
def test_error_is_raisable_and_catchable(error_cls: type[Exception]) -> None:
    with pytest.raises(exc.NetArchitectError):
        raise error_cls("boom")


def test_schema_error_catches_subclasses() -> None:
    with pytest.raises(exc.SchemaError):
        raise exc.DuplicateIdError("dup")
    with pytest.raises(exc.SchemaError):
        raise exc.MissingEndpointError("missing")
    with pytest.raises(exc.SchemaError):
        raise exc.OverlappingSubnetError("overlap")
    with pytest.raises(exc.SchemaError):
        raise exc.InvalidVlanIdError("bad vlan")
