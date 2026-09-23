# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the ``ComponentVital`` concrete shape and ``ComponentSpec``.

Covers the component-vital domain contract: component structure declared as
class metadata, values in named instance fields, ``component_values`` iteration,
and import-time metadata enforcement.

Requirements: FR-HH-1, NFR-HH-1.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, dataclass
from datetime import UTC, datetime
from typing import ClassVar

import pytest

from vitals_on_fhir.vitals import ComponentSpec, ComponentVital


def _spec(field_name: str, loinc_code: str = "1111-1") -> ComponentSpec:
    """Build a ``ComponentSpec`` with a default unit and range for tests."""
    return ComponentSpec(
        field_name=field_name,
        loinc_code=loinc_code,
        ucum_unit="u",
        default_range=(0.0, 10.0),
    )


def _make_valid_subclass() -> type[ComponentVital]:
    """Return a minimal, valid concrete ``ComponentVital`` subclass for testing."""

    @dataclass(frozen=True, kw_only=True)
    class _TwoPart(ComponentVital):
        loinc_code: ClassVar[str] = "0000-0"
        us_core_profile: ClassVar[str] = "http://hl7.org/fhir/example"
        components: ClassVar[tuple[ComponentSpec, ...]] = (_spec("a"), _spec("b", "2222-2"))
        a: float
        b: float

    return _TwoPart


def test_component_values_returns_declared_order() -> None:
    """``component_values`` returns ``(spec, value)`` pairs in declared order."""
    cls = _make_valid_subclass()
    instance = cls(effective=datetime.now(UTC), device_id="d", a=3.0, b=7.0)

    pairs = instance.component_values()

    assert [spec.field_name for spec, _ in pairs] == ["a", "b"]
    assert [value for _, value in pairs] == [3.0, 7.0]
    assert all(isinstance(value, float) for _, value in pairs)


def test_component_spec_is_frozen() -> None:
    """``ComponentSpec`` instances are immutable."""
    spec = _spec("a")
    with pytest.raises(FrozenInstanceError):
        spec.field_name = "b"  # type: ignore[misc]


def test_missing_components_raises_at_class_definition() -> None:
    """A concrete ``ComponentVital`` without a ``components`` tuple raises ``TypeError``."""
    with pytest.raises(TypeError, match="non-empty 'components'"):

        @dataclass(frozen=True, kw_only=True)
        class _NoComponents(ComponentVital):
            loinc_code: ClassVar[str] = "0000-0"
            us_core_profile: ClassVar[str] = "http://hl7.org/fhir/example"
            components: ClassVar[tuple[ComponentSpec, ...]] = ()
            a: float


def test_spec_field_without_matching_instance_field_raises() -> None:
    """A ``ComponentSpec.field_name`` with no matching instance field raises ``TypeError``."""
    with pytest.raises(TypeError, match="no matching"):

        @dataclass(frozen=True, kw_only=True)
        class _Mismatch(ComponentVital):
            loinc_code: ClassVar[str] = "0000-0"
            us_core_profile: ClassVar[str] = "http://hl7.org/fhir/example"
            components: ClassVar[tuple[ComponentSpec, ...]] = (_spec("missing"),)
            present: float


def test_missing_profile_enforced_by_vitalsign_contract() -> None:
    """A concrete component vital missing ``us_core_profile`` raises via the base contract."""
    with pytest.raises(TypeError, match="us_core_profile"):

        @dataclass(frozen=True, kw_only=True)
        class _NoProfile(ComponentVital):
            loinc_code: ClassVar[str] = "0000-0"
            components: ClassVar[tuple[ComponentSpec, ...]] = (_spec("a"),)
            a: float
