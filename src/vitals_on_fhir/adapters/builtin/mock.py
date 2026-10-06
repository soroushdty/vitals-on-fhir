# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mock device adapter that produces simulated vital signs without hardware.

``MockAdapter`` never imports ``bleak``. It is used for development, CI, and
tests that don't carry the ``hardware`` marker. Its emission mode lets tests
drive each branch of the validator chain (in-range, out-of-range, and
sensor-contact-lost readings).
"""

from __future__ import annotations

import asyncio
import contextlib
import enum
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.adapters.builtin.hr_scenarios import (
    HeartRateScenario,
    ScenarioEngine,
    Tick,
    scenario_infos,
)
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign
from vitals_on_fhir.vitals.builtin.blood_pressure import BloodPressure
from vitals_on_fhir.vitals.builtin.body_temperature import BodyTemperature
from vitals_on_fhir.vitals.builtin.body_weight import BodyWeight
from vitals_on_fhir.vitals.builtin.heart_rate import HeartRate
from vitals_on_fhir.vitals.builtin.oxygen_saturation import OxygenSaturation

_DEFAULT_INTERVAL = 0.01  # seconds between yields; small so tests stay fast
_VALID_HEART_RATE = 72.0  # bpm, comfortably inside the plausible range
_IMPLAUSIBLE_HEART_RATE = 300.0  # bpm, above the default plausible upper bound
# Connection states in which the mock keeps its stream open (RECONNECTING = a simulated dropout).
_ACTIVE_STATES = (ConnectionState.CONNECTED, ConnectionState.RECONNECTING)


class EmissionMode(enum.Enum):
    """Controls the kind of reading ``MockAdapter`` emits.

    - ``VALID`` — in-range readings with sensor contact reported ``True``.
    - ``IMPLAUSIBLE`` — readings whose value is outside the plausible range.
    - ``NO_SENSOR_CONTACT`` — readings with ``sensor_contact`` set to ``False``.
    """

    VALID = "valid"
    IMPLAUSIBLE = "implausible"
    NO_SENSOR_CONTACT = "no_sensor_contact"


class MockAdapter(DeviceAdapter):
    """Simulated device adapter that emits synthetic heart-rate readings.

    Configurable via ``emission_mode`` to produce valid readings, implausible
    values, or readings with lost sensor contact so the full validator chain
    can be exercised in tests. An optional ``count`` bounds how many readings
    are yielded (``None`` yields indefinitely until disconnected), and
    ``interval`` sets the cooperative delay between yields. With a ``scenario``
    set, ``VALID`` readings follow that :class:`HeartRateScenario` (and it can be
    changed while running) instead of repeating one fixed value; scenarios can
    also flag lost sensor contact or drop the simulated connection, reported
    through ``on_state_change`` like a real device. Never imports ``bleak``.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (HeartRate,)

    def __init__(
        self,
        emission_mode: EmissionMode = EmissionMode.VALID,
        *,
        interval: float = _DEFAULT_INTERVAL,
        count: int | None = None,
        scenario: HeartRateScenario | None = None,
        rng: random.Random | None = None,
        on_state_change: Callable[[ConnectionState], Awaitable[None]] | None = None,
        on_restart: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Create a mock adapter.

        Args:
            emission_mode: Which kind of reading to emit; drives the validator
                chain branch under test.
            interval: Seconds to sleep between yielded readings.
            count: Maximum number of readings to yield, or ``None`` to yield
                indefinitely until ``disconnect`` is called.
            scenario: Heart-rate pattern for ``VALID`` readings, or ``None`` to
                emit a fixed 72 bpm.
            rng: Random source for variable readings; pass a seeded
                ``random.Random`` for reproducible output.
            on_state_change: Optional async callback invoked on every
                connection-state change, as the BLE adapters do.
            on_restart: Optional async callback awaited when the scenario is
                (re)started, after every earlier reading has been delivered and
                before the first reading of the new run; the composition root
                uses it to clear what the previous run left behind.
        """
        self._emission_mode = emission_mode
        self._interval = interval
        self._count = count
        self._scenario = scenario
        self._engine = ScenarioEngine(rng if rng is not None else random.Random())
        if scenario is not None:
            self._engine.select(scenario)
        self._on_state_change = on_state_change
        self._on_restart = on_restart
        self._restart_pending = False
        self._wake = asyncio.Event()  # set to cut the wait between readings short
        self._state = ConnectionState.DISCONNECTED

    @property
    def device_info(self) -> DeviceInfo:
        """Return a synthetic ``DeviceInfo`` for the mock device."""
        return DeviceInfo(
            manufacturer="vitals-on-fhir",
            model="Mock HR",
            identifiers={"mock": "1"},
            simulated=True,
        )

    @property
    def scenario(self) -> HeartRateScenario | None:
        """Return the active heart-rate scenario, or ``None`` for a fixed 72 bpm."""
        return self._scenario

    @scenario.setter
    def scenario(self, scenario: HeartRateScenario) -> None:
        """(Re)start *scenario* from the beginning, right away.

        The pending wait between readings is cut short; before the first new
        reading ``on_restart`` runs, so nothing from the previous run follows it.
        Selecting the running scenario again restarts it.
        """
        self._scenario = scenario
        self._engine.select(scenario)
        self._restart_pending = True
        self._wake.set()

    @property
    def state(self) -> ConnectionState:
        """Return the current simulated connection state."""
        return self._state

    async def _set_state(self, state: ConnectionState) -> None:
        """Record *state* and report it through ``on_state_change``."""
        self._state = state
        if self._on_state_change is not None:
            await self._on_state_change(state)

    async def connect(self) -> None:
        """Simulate connecting to the mock device.

        Transitions ``CONNECTING`` then ``CONNECTED``, consistent with the
        ``DeviceAdapter`` contract.
        """
        await self._set_state(ConnectionState.CONNECTING)
        await self._set_state(ConnectionState.CONNECTED)

    async def disconnect(self) -> None:
        """Simulate disconnecting from the mock device."""
        await self._set_state(ConnectionState.DISCONNECTED)

    async def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield simulated ``HeartRate`` readings per the configured mode.

        Each reading carries a timezone-aware ``effective`` timestamp. Yields
        until ``count`` readings have been produced, or indefinitely while
        connected when ``count`` is ``None``. During a simulated dropout (state
        ``RECONNECTING``) the stream stays open but yields nothing. A small
        ``asyncio.sleep`` between readings keeps the generator cooperative.
        """
        emitted = 0
        while self._state in _ACTIVE_STATES:
            if self._count is not None and emitted >= self._count:
                return
            if self._restart_pending:
                # Every earlier reading has been delivered by now (the consumer
                # only asks for the next one after handling the last), so
                # clearing here cannot let a stale reading slip in afterwards.
                self._restart_pending = False
                if self._on_restart is not None:
                    await self._on_restart()
            reading = await self._next_reading()
            if reading is not None:
                yield reading
                emitted += 1
            await self._pause()

    async def _pause(self) -> None:
        """Wait ``interval`` seconds between readings, or less if a restart is requested."""
        if self._interval <= 0:
            await asyncio.sleep(0)
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
        self._wake.clear()

    async def _next_reading(self) -> HeartRate | None:
        """Return the next reading, or ``None`` while the simulated link is down.

        Only ``VALID`` mode with a scenario consults the scenario engine; it may
        also move the connection between ``CONNECTED`` and ``RECONNECTING``.
        """
        if self._scenario is None or self._emission_mode != EmissionMode.VALID:
            return self._make_reading()
        tick = self._engine.step()
        wanted = ConnectionState.CONNECTED if tick.connected else ConnectionState.RECONNECTING
        if self._state != wanted:
            await self._set_state(wanted)
        return self._make_reading(tick) if tick.bpm is not None else None

    def _make_reading(self, tick: Tick | None = None) -> HeartRate:
        """Build a single ``HeartRate`` reading for the configured emission mode."""
        effective = datetime.now(UTC)
        if self._emission_mode == EmissionMode.IMPLAUSIBLE:
            return HeartRate(
                effective=effective,
                device_id=self._device_id(),
                value=_IMPLAUSIBLE_HEART_RATE,
                sensor_contact=True,
            )
        if self._emission_mode == EmissionMode.NO_SENSOR_CONTACT:
            return HeartRate(
                effective=effective,
                device_id=self._device_id(),
                value=_VALID_HEART_RATE,
                sensor_contact=False,
            )
        return HeartRate(
            effective=effective,
            device_id=self._device_id(),
            value=tick.bpm if tick is not None and tick.bpm is not None else _VALID_HEART_RATE,
            sensor_contact=tick.contact if tick is not None else True,
        )

    def _device_id(self) -> str:
        """Return the device identifier used for readings from this adapter."""
        return self.device_info.identifiers["mock"]


class HeartRateScenarioControl:
    """Lets the dashboard start a :class:`MockAdapter` heart-rate scenario.

    Structurally satisfies ``api.mock_control.ScenarioControl`` (the ``api``
    package cannot import adapters); ``cli.py`` hands it to ``create_app``.
    """

    def __init__(self, adapter: MockAdapter) -> None:
        """Wrap *adapter*, starting it on normal sinus rhythm if it has no scenario."""
        if adapter.scenario is None:
            adapter.scenario = HeartRateScenario.NORMAL_SINUS_RHYTHM
        self._adapter = adapter

    @property
    def current(self) -> str:
        """Return the id of the active scenario."""
        scenario = self._adapter.scenario
        assert scenario is not None  # set in __init__
        return scenario.value

    def options(self) -> list[dict[str, str]]:
        """Return every scenario as ``{"id", "label", "description", "group"}``."""
        return [
            {"id": i.id, "label": i.label, "description": i.description, "group": i.group}
            for i in scenario_infos()
        ]

    def start(self, scenario_id: str) -> None:
        """Start the scenario with id *scenario_id* from the beginning.

        Starting the scenario that is already running restarts it.

        Raises:
            ValueError: If *scenario_id* is not one of :meth:`options`.
        """
        try:
            self._adapter.scenario = HeartRateScenario(scenario_id)
        except ValueError:
            raise ValueError(f"Unknown scenario {scenario_id!r}") from None


_VALID_SYSTOLIC = 118.0  # mmHg, inside the default plausible range
_VALID_DIASTOLIC = 76.0  # mmHg, inside the default plausible range
_IMPLAUSIBLE_SYSTOLIC = 300.0  # mmHg, above the default upper bound
_IMPLAUSIBLE_DIASTOLIC = 200.0  # mmHg, above the default upper bound
_STORE_AND_FORWARD_DELAY = 300.0  # seconds in the past for the buffered-reading mode


class BloodPressureEmissionMode(enum.Enum):
    """Controls the kind of reading ``MockBloodPressureAdapter`` emits.

    - ``VALID`` — in-range systolic/diastolic readings.
    - ``IMPLAUSIBLE_SYSTOLIC`` — systolic above the plausible upper bound.
    - ``IMPLAUSIBLE_DIASTOLIC`` — diastolic above the plausible upper bound.
    - ``STORE_AND_FORWARD`` — a valid reading whose ``effective`` time is in the
      past, so ``effective`` differs from the processing (``issued``) time.
    """

    VALID = "valid"
    IMPLAUSIBLE_SYSTOLIC = "implausible_systolic"
    IMPLAUSIBLE_DIASTOLIC = "implausible_diastolic"
    STORE_AND_FORWARD = "store_and_forward"


class MockBloodPressureAdapter(DeviceAdapter):
    """Simulated device adapter that emits synthetic blood-pressure readings.

    Configurable via ``emission_mode`` to produce valid readings, an out-of-range
    systolic or diastolic, or a store-and-forward reading (past ``effective``
    time), so the component validator chain and the effective-vs-issued path can
    be exercised in tests. An optional ``count`` bounds how many readings are
    yielded (``None`` yields indefinitely until disconnected). Never imports
    ``bleak``.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (BloodPressure,)

    def __init__(
        self,
        emission_mode: BloodPressureEmissionMode = BloodPressureEmissionMode.VALID,
        *,
        interval: float = _DEFAULT_INTERVAL,
        count: int | None = None,
    ) -> None:
        """Create a mock blood-pressure adapter.

        Args:
            emission_mode: Which kind of reading to emit; drives the component
                validator chain and the store-and-forward path under test.
            interval: Seconds to sleep between yielded readings.
            count: Maximum number of readings to yield, or ``None`` to yield
                indefinitely until ``disconnect`` is called.
        """
        self._emission_mode = emission_mode
        self._interval = interval
        self._count = count
        self._state = ConnectionState.DISCONNECTED

    @property
    def device_info(self) -> DeviceInfo:
        """Return a synthetic ``DeviceInfo`` for the mock blood-pressure device."""
        return DeviceInfo(
            manufacturer="vitals-on-fhir",
            model="Mock BP",
            identifiers={"mock": "bp-1"},
            simulated=True,
        )

    @property
    def state(self) -> ConnectionState:
        """Return the current simulated connection state."""
        return self._state

    async def connect(self) -> None:
        """Simulate connecting to the mock device (``CONNECTING`` then ``CONNECTED``)."""
        self._state = ConnectionState.CONNECTING
        self._state = ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        """Simulate disconnecting from the mock device."""
        self._state = ConnectionState.DISCONNECTED

    async def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield simulated ``BloodPressure`` readings per the configured mode.

        Each reading carries a timezone-aware ``effective`` timestamp. Yields
        until ``count`` readings have been produced, or indefinitely while
        connected when ``count`` is ``None``.
        """
        emitted = 0
        while self._state == ConnectionState.CONNECTED:
            if self._count is not None and emitted >= self._count:
                return
            yield self._make_reading()
            emitted += 1
            await asyncio.sleep(self._interval)

    def _make_reading(self) -> BloodPressure:
        """Build a single ``BloodPressure`` reading for the configured emission mode."""
        effective = datetime.now(UTC)
        systolic = _VALID_SYSTOLIC
        diastolic = _VALID_DIASTOLIC

        if self._emission_mode == BloodPressureEmissionMode.IMPLAUSIBLE_SYSTOLIC:
            systolic = _IMPLAUSIBLE_SYSTOLIC
        elif self._emission_mode == BloodPressureEmissionMode.IMPLAUSIBLE_DIASTOLIC:
            diastolic = _IMPLAUSIBLE_DIASTOLIC
        elif self._emission_mode == BloodPressureEmissionMode.STORE_AND_FORWARD:
            effective = datetime.now(UTC) - timedelta(seconds=_STORE_AND_FORWARD_DELAY)

        return BloodPressure(
            effective=effective,
            device_id=self._device_id(),
            systolic=systolic,
            diastolic=diastolic,
        )

    def _device_id(self) -> str:
        """Return the device identifier used for readings from this adapter."""
        return self.device_info.identifiers["mock"]


_VALID_OXYGEN_SATURATION = 98.0  # %, comfortably inside the default plausible range
_IMPLAUSIBLE_OXYGEN_SATURATION = 50.0  # %, below the default plausible lower bound


class OximeterEmissionMode(enum.Enum):
    """Controls the kind of reading ``MockOximeterAdapter`` emits.

    - ``VALID`` — in-range SpO2 readings (e.g. 98%).
    - ``IMPLAUSIBLE`` — readings below the plausible lower bound (e.g. 50%).

    There is no store-and-forward mode: the PLX Continuous Measurement
    characteristic carries no timestamp, so a continuous SpO2 reading's
    ``effective`` time is always the processing time.
    """

    VALID = "valid"
    IMPLAUSIBLE = "implausible"


class MockOximeterAdapter(DeviceAdapter):
    """Simulated device adapter that emits synthetic oxygen-saturation readings.

    Configurable via ``emission_mode`` to produce valid readings or an
    out-of-range (implausible) SpO2 value so the plausible-range validator can
    be exercised in tests without hardware. An optional ``count`` bounds how
    many readings are yielded (``None`` yields indefinitely until disconnected).
    Never imports ``bleak``.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (OxygenSaturation,)

    def __init__(
        self,
        emission_mode: OximeterEmissionMode = OximeterEmissionMode.VALID,
        *,
        interval: float = _DEFAULT_INTERVAL,
        count: int | None = None,
    ) -> None:
        """Create a mock pulse-oximeter adapter.

        Args:
            emission_mode: Which kind of reading to emit; drives the
                plausible-range validator branch under test.
            interval: Seconds to sleep between yielded readings.
            count: Maximum number of readings to yield, or ``None`` to yield
                indefinitely until ``disconnect`` is called.
        """
        self._emission_mode = emission_mode
        self._interval = interval
        self._count = count
        self._state = ConnectionState.DISCONNECTED

    @property
    def device_info(self) -> DeviceInfo:
        """Return a synthetic ``DeviceInfo`` for the mock pulse-oximeter device."""
        return DeviceInfo(
            manufacturer="vitals-on-fhir",
            model="Mock SpO2",
            identifiers={"mock": "spo2-1"},
            simulated=True,
        )

    @property
    def state(self) -> ConnectionState:
        """Return the current simulated connection state."""
        return self._state

    async def connect(self) -> None:
        """Simulate connecting to the mock device (``CONNECTING`` then ``CONNECTED``)."""
        self._state = ConnectionState.CONNECTING
        self._state = ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        """Simulate disconnecting from the mock device."""
        self._state = ConnectionState.DISCONNECTED

    async def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield simulated ``OxygenSaturation`` readings per the configured mode.

        Each reading carries a timezone-aware ``effective`` timestamp. Yields
        until ``count`` readings have been produced, or indefinitely while
        connected when ``count`` is ``None``.
        """
        emitted = 0
        while self._state == ConnectionState.CONNECTED:
            if self._count is not None and emitted >= self._count:
                return
            yield self._make_reading()
            emitted += 1
            await asyncio.sleep(self._interval)

    def _make_reading(self) -> OxygenSaturation:
        """Build a single ``OxygenSaturation`` reading for the configured mode."""
        value = _VALID_OXYGEN_SATURATION
        if self._emission_mode == OximeterEmissionMode.IMPLAUSIBLE:
            value = _IMPLAUSIBLE_OXYGEN_SATURATION
        return OxygenSaturation(
            effective=datetime.now(UTC),
            device_id=self._device_id(),
            value=value,
        )

    def _device_id(self) -> str:
        """Return the device identifier used for readings from this adapter."""
        return self.device_info.identifiers["mock"]


_VALID_BODY_TEMPERATURE = 37.0  # °C, comfortably inside the default plausible range
_IMPLAUSIBLE_BODY_TEMPERATURE = 5.0  # °C, below the default plausible lower bound
# 98.6 °F normalizes to exactly 37.0 °C; the mock emits the already-normalized value.
_FAHRENHEIT_SOURCE_CELSIUS = 37.0  # °C, the Celsius equivalent of a 98.6 °F source


class ThermometerEmissionMode(enum.Enum):
    """Controls the kind of reading ``MockThermometerAdapter`` emits.

    - ``VALID`` — in-range body-temperature readings (e.g. 37.0 °C).
    - ``IMPLAUSIBLE`` — readings below the plausible lower bound (e.g. 5.0 °C).
    - ``FAHRENHEIT_SOURCE`` — a reading whose source device reported Fahrenheit;
      the mock emits the already-normalized Celsius equivalent (e.g. 37.0 °C),
      mirroring the parser, which normalizes Fahrenheit to Celsius before
      constructing the reading. The domain object is always Celsius.
    """

    VALID = "valid"
    IMPLAUSIBLE = "implausible"
    FAHRENHEIT_SOURCE = "fahrenheit_source"


class MockThermometerAdapter(DeviceAdapter):
    """Simulated device adapter that emits synthetic body-temperature readings.

    Configurable via ``emission_mode`` to produce valid readings, an out-of-range
    (implausible) value so the plausible-range validator can be exercised, or a
    reading whose source device reported Fahrenheit — emitted as the already-
    normalized Celsius equivalent, since a ``BodyTemperature`` is always Celsius.
    An optional ``count`` bounds how many readings are yielded (``None`` yields
    indefinitely until disconnected). Never imports ``bleak``.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (BodyTemperature,)

    def __init__(
        self,
        emission_mode: ThermometerEmissionMode = ThermometerEmissionMode.VALID,
        *,
        interval: float = _DEFAULT_INTERVAL,
        count: int | None = None,
    ) -> None:
        """Create a mock health-thermometer adapter.

        Args:
            emission_mode: Which kind of reading to emit; drives the
                plausible-range validator branch and the Fahrenheit-source path
                under test.
            interval: Seconds to sleep between yielded readings.
            count: Maximum number of readings to yield, or ``None`` to yield
                indefinitely until ``disconnect`` is called.
        """
        self._emission_mode = emission_mode
        self._interval = interval
        self._count = count
        self._state = ConnectionState.DISCONNECTED

    @property
    def device_info(self) -> DeviceInfo:
        """Return a synthetic ``DeviceInfo`` for the mock thermometer device."""
        return DeviceInfo(
            manufacturer="vitals-on-fhir",
            model="Mock Temp",
            identifiers={"mock": "temp-1"},
            simulated=True,
        )

    @property
    def state(self) -> ConnectionState:
        """Return the current simulated connection state."""
        return self._state

    async def connect(self) -> None:
        """Simulate connecting to the mock device (``CONNECTING`` then ``CONNECTED``)."""
        self._state = ConnectionState.CONNECTING
        self._state = ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        """Simulate disconnecting from the mock device."""
        self._state = ConnectionState.DISCONNECTED

    async def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield simulated ``BodyTemperature`` readings per the configured mode.

        Each reading carries a timezone-aware ``effective`` timestamp. Yields
        until ``count`` readings have been produced, or indefinitely while
        connected when ``count`` is ``None``.
        """
        emitted = 0
        while self._state == ConnectionState.CONNECTED:
            if self._count is not None and emitted >= self._count:
                return
            yield self._make_reading()
            emitted += 1
            await asyncio.sleep(self._interval)

    def _make_reading(self) -> BodyTemperature:
        """Build a single ``BodyTemperature`` reading for the configured mode."""
        value = _VALID_BODY_TEMPERATURE
        if self._emission_mode == ThermometerEmissionMode.IMPLAUSIBLE:
            value = _IMPLAUSIBLE_BODY_TEMPERATURE
        elif self._emission_mode == ThermometerEmissionMode.FAHRENHEIT_SOURCE:
            value = _FAHRENHEIT_SOURCE_CELSIUS
        return BodyTemperature(
            effective=datetime.now(UTC),
            device_id=self._device_id(),
            value=value,
        )

    def _device_id(self) -> str:
        """Return the device identifier used for readings from this adapter."""
        return self.device_info.identifiers["mock"]


_VALID_BODY_WEIGHT = 70.0  # kg, comfortably inside the default plausible range
_IMPLAUSIBLE_BODY_WEIGHT = 900.0  # kg, above the default plausible upper bound
# 154.323... lb normalizes to 70.0 kg; the mock emits the already-normalized value.
_IMPERIAL_SOURCE_KILOGRAMS = 70.0  # kg, the kilogram equivalent of an Imperial source


class WeightEmissionMode(enum.Enum):
    """Controls the kind of reading ``MockWeightAdapter`` emits.

    - ``VALID`` — in-range body-weight readings (e.g. 70.0 kg).
    - ``IMPLAUSIBLE`` — readings above the plausible upper bound (e.g. 900.0 kg).
    - ``IMPERIAL_SOURCE`` — a reading whose source device reported pounds; the
      mock emits the already-normalized kilogram equivalent (e.g. 70.0 kg),
      mirroring the parser, which normalizes pounds to kilograms before
      constructing the reading. The domain object is always kilograms.
    """

    VALID = "valid"
    IMPLAUSIBLE = "implausible"
    IMPERIAL_SOURCE = "imperial_source"


class MockWeightAdapter(DeviceAdapter):
    """Simulated device adapter that emits synthetic body-weight readings.

    Configurable via ``emission_mode`` to produce valid readings, an out-of-range
    (implausible) value so the plausible-range validator can be exercised, or a
    reading whose source device reported pounds — emitted as the already-
    normalized kilogram equivalent, since a ``BodyWeight`` is always kilograms.
    An optional ``count`` bounds how many readings are yielded (``None`` yields
    indefinitely until disconnected). Never imports ``bleak``.
    """

    supported_vitals: ClassVar[tuple[type[VitalSign], ...]] = (BodyWeight,)

    def __init__(
        self,
        emission_mode: WeightEmissionMode = WeightEmissionMode.VALID,
        *,
        interval: float = _DEFAULT_INTERVAL,
        count: int | None = None,
    ) -> None:
        """Create a mock weight-scale adapter.

        Args:
            emission_mode: Which kind of reading to emit; drives the
                plausible-range validator branch and the Imperial-source path
                under test.
            interval: Seconds to sleep between yielded readings.
            count: Maximum number of readings to yield, or ``None`` to yield
                indefinitely until ``disconnect`` is called.
        """
        self._emission_mode = emission_mode
        self._interval = interval
        self._count = count
        self._state = ConnectionState.DISCONNECTED

    @property
    def device_info(self) -> DeviceInfo:
        """Return a synthetic ``DeviceInfo`` for the mock weight-scale device."""
        return DeviceInfo(
            manufacturer="vitals-on-fhir",
            model="Mock Weight",
            identifiers={"mock": "weight-1"},
            simulated=True,
        )

    @property
    def state(self) -> ConnectionState:
        """Return the current simulated connection state."""
        return self._state

    async def connect(self) -> None:
        """Simulate connecting to the mock device (``CONNECTING`` then ``CONNECTED``)."""
        self._state = ConnectionState.CONNECTING
        self._state = ConnectionState.CONNECTED

    async def disconnect(self) -> None:
        """Simulate disconnecting from the mock device."""
        self._state = ConnectionState.DISCONNECTED

    async def vitals(self) -> AsyncIterator[VitalSign]:
        """Yield simulated ``BodyWeight`` readings per the configured mode.

        Each reading carries a timezone-aware ``effective`` timestamp. Yields
        until ``count`` readings have been produced, or indefinitely while
        connected when ``count`` is ``None``.
        """
        emitted = 0
        while self._state == ConnectionState.CONNECTED:
            if self._count is not None and emitted >= self._count:
                return
            yield self._make_reading()
            emitted += 1
            await asyncio.sleep(self._interval)

    def _make_reading(self) -> BodyWeight:
        """Build a single ``BodyWeight`` reading for the configured mode."""
        value = _VALID_BODY_WEIGHT
        if self._emission_mode == WeightEmissionMode.IMPLAUSIBLE:
            value = _IMPLAUSIBLE_BODY_WEIGHT
        elif self._emission_mode == WeightEmissionMode.IMPERIAL_SOURCE:
            value = _IMPERIAL_SOURCE_KILOGRAMS
        return BodyWeight(
            effective=datetime.now(UTC),
            device_id=self._device_id(),
            value=value,
        )

    def _device_id(self) -> str:
        """Return the device identifier used for readings from this adapter."""
        return self.device_info.identifiers["mock"]
