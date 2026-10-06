# SPDX-License-Identifier: AGPL-3.0-or-later
"""Temperature Type -> body site -> ``Observation.bodySite`` (issue #11, ADR-0006).

The expected values are restated here from GSS (2026-09-09) Table 3.370 and the
SNOMED CT concepts recorded in ``docs/protocol-body-temperature-measurement.md``,
rather than imported from the parser, so a wrong entry fails a test.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime

import pytest

from vitals_on_fhir.adapters.temp_parser import TemperatureMeasurementParser
from vitals_on_fhir.fhir.mappers import ScalarVitalMapper
from vitals_on_fhir.vitals import BodySite, BodyTemperature

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
_TIMESTAMP = (2026).to_bytes(2, "little") + bytes([10, 6, 8, 30, 0])

# GSS Temperature Type value -> (SNOMED CT code, display). Values not listed
# (0 and 10-255 reserved, 2 "Body (general)") must give no body site.
_SITES = {
    1: ("91470000", "Axillary region structure"),  # Armpit
    3: ("48800003", "Ear lobule structure"),  # Ear (usually earlobe)
    4: ("7569003", "Finger structure"),  # Finger
    5: ("122865005", "Gastrointestinal tract structure"),  # Gastrointestinal Tract
    6: ("74262004", "Oral cavity structure"),  # Mouth
    7: ("34402009", "Rectum structure"),  # Rectum
    8: ("29707007", "Toe structure"),  # Toe
    9: ("42859004", "Tympanic membrane structure"),  # Tympanum (ear drum)
}


def _float(value: int, exponent: int = -1) -> bytes:
    """Encode an IEEE-11073 32-bit FLOAT (24-bit mantissa, 8-bit exponent)."""
    return struct.pack("<I", ((exponent & 0xFF) << 24) | (value & 0xFFFFFF))


def _parse(temperature_type: int | None, *, timestamp: bool = True) -> BodyTemperature:
    flags = (0x02 if timestamp else 0) | (0x04 if temperature_type is not None else 0)
    payload = bytes([flags]) + _float(368)  # 36.8 Cel
    if timestamp:
        payload += _TIMESTAMP
    if temperature_type is not None:
        payload += bytes([temperature_type])
    reading = TemperatureMeasurementParser("thermometer", now=lambda: _NOW).parse(payload)
    assert isinstance(reading, BodyTemperature)
    return reading


@pytest.mark.parametrize("temperature_type", range(256))
@pytest.mark.parametrize("timestamp", [True, False])
def test_every_temperature_type_value(temperature_type: int, timestamp: bool) -> None:
    """Each GSS value maps to its site; general, reserved and unknown values give none."""
    reading = _parse(temperature_type, timestamp=timestamp)
    expected = _SITES.get(temperature_type)
    if expected is None:
        assert reading.body_site is None
    else:
        assert reading.body_site is not None
        assert (reading.body_site.snomed_code, reading.body_site.snomed_display) == expected
    assert reading.value == pytest.approx(36.8)


def test_absent_temperature_type_gives_no_body_site() -> None:
    """A thermometer that sends no Temperature Type behaves as before."""
    assert _parse(None).body_site is None


@pytest.mark.parametrize("site", list(BodySite))
def test_mapper_sets_body_site(site: BodySite) -> None:
    """Every site becomes a single SNOMED CT coding in ``Observation.bodySite``."""
    reading = BodyTemperature(effective=_NOW, device_id="t", value=36.8, body_site=site)
    observation = ScalarVitalMapper().to_observation(reading, "Patient/p", "Device/t", _NOW)
    assert observation.bodySite is not None
    assert [(c.system, c.code, c.display) for c in observation.bodySite.coding] == [
        ("http://snomed.info/sct", site.snomed_code, site.snomed_display)
    ]


def test_mapper_omits_body_site_when_unknown() -> None:
    """No site on the reading, no ``bodySite`` on the Observation."""
    reading = BodyTemperature(effective=_NOW, device_id="t", value=36.8)
    observation = ScalarVitalMapper().to_observation(reading, "Patient/p", "Device/t", _NOW)
    assert observation.bodySite is None
    assert "bodySite" not in observation.model_dump(exclude_none=True)


def test_every_documented_site_has_a_member() -> None:
    """The domain enum and the GSS mapping cover exactly the same sites."""
    assert {(s.snomed_code, s.snomed_display) for s in BodySite} == set(_SITES.values())
