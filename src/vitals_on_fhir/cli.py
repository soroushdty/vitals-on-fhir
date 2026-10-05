# SPDX-License-Identifier: AGPL-3.0-or-later
"""Composition root — the only module that may import from all packages.

``main()`` is the CLI entry point registered as ``vitals-on-fhir`` in
``pyproject.toml``.  It is the single place in the codebase where concrete
classes from every package are named and wired together, and the only place
``asyncio.run()`` is called (``tech.md``, FR-ORCH).

Responsibilities (design §11):

1. Load :class:`~vitals_on_fhir.config.Settings` once.  Configuration is never
   logged — it may carry ``VOF_API_TOKEN`` (NFR-5, ``security-privacy.md``).
2. Parse ``--adapter`` (defaulting to the configured value) and resolve it to a
   concrete :class:`~vitals_on_fhir.adapters.DeviceAdapter`: the short names
   ``mock``, ``mock-bp``, ``mock-spo2``, ``mock-temp``, ``mock-weight``,
   ``miband10``, ``bp``, ``spo2``, ``temp``, and ``weight`` map
   to the built-in adapters, and any other value is treated as a fully
   qualified ``package.module.ClassName`` imported via :mod:`importlib` (FR-13).
3. Build the startup ``Patient`` and ``Device`` resources and derive their
   ``Patient/<id>`` / ``Device/<id>`` reference strings.
4. Assemble the :class:`~vitals_on_fhir.validation.ValidatorChain` from the
   configured plausibility bounds.
5. Construct the in-memory store and the dashboard broadcaster, wire the
   :class:`~vitals_on_fhir.pipeline.Orchestrator` with both as sinks and the
   broadcaster's ``on_state_change`` as the state relay.
6. Build the FastAPI app via :func:`~vitals_on_fhir.api.create_app`, injecting
   the store, a :class:`~vitals_on_fhir.api.StaticTokenAuthenticator`, the
   broadcaster, and the startup resources.
7. Run the uvicorn server and the orchestrator concurrently inside a single
   ``asyncio.run`` (FR-7, FR-ORCH).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import logging
from collections.abc import Awaitable, Callable
from datetime import tzinfo
from pathlib import Path
from typing import cast

import uvicorn

from vitals_on_fhir import dashboard as _dashboard
from vitals_on_fhir.adapters import (
    BloodPressureBleAdapter,
    ConnectionState,
    DeviceAdapter,
    HealthThermometerBleAdapter,
    MiBand10Adapter,
    MockAdapter,
    MockBloodPressureAdapter,
    MockOximeterAdapter,
    MockThermometerAdapter,
    MockWeightAdapter,
    PulseOximeterBleAdapter,
    WeightScaleBleAdapter,
)
from vitals_on_fhir.api import StaticTokenAuthenticator, create_app
from vitals_on_fhir.api.app import BroadcasterLike
from vitals_on_fhir.config import DEFAULT_CONFIG_PATH, Settings, resolve_timezone
from vitals_on_fhir.dashboard import DashboardBroadcaster
from vitals_on_fhir.fhir import ScalarVitalMapper, build_device, build_patient
from vitals_on_fhir.pipeline import ObservationSink, Orchestrator
from vitals_on_fhir.store import InMemoryObservationStore
from vitals_on_fhir.validation import (
    ComponentRangeValidator,
    DuplicateValidator,
    PlausibleRangeValidator,
    SensorContactValidator,
    ValidatorChain,
)
from vitals_on_fhir.vitals import (
    BloodPressure,
    BodyTemperature,
    BodyWeight,
    HeartRate,
    OxygenSaturation,
)

logger = logging.getLogger(__name__)

#: Filesystem path to the dashboard static assets, resolved relative to the
#: ``dashboard`` package.  ``cli.py`` is permitted to import from every package,
#: so importing the module here to locate its assets is allowed.
_STATIC_DIR = Path(_dashboard.__file__).parent / "static"


def _resolve_config_path(argv: list[str] | None = None) -> Path:
    """Resolve the ``config.yaml`` path from ``--config``, validating explicit-missing.

    ``--config`` must be known before :class:`Settings` is built because it
    selects which file the YAML tier reads.  A small ``parse_known_args`` pass
    reads it ahead of the full argument parse (design §4, Architecture).

    Args:
        argv: Argument vector to parse (defaults to ``sys.argv[1:]``).

    Returns:
        The resolved :class:`~pathlib.Path`.  With no ``--config`` this is the
        default ``config.yaml`` at the working directory (repo root); a missing
        *default* file stays a silent no-op (FR-CFG-1).

    Raises:
        FileNotFoundError: If ``--config PATH`` is given explicitly and ``PATH``
            does not exist — fail loud, naming the path, distinct from the
            absent-default no-op (FR-CFG-6, design §4).
    """
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", default=None)
    known, _ = pre_parser.parse_known_args(argv)

    if known.config is None:
        return DEFAULT_CONFIG_PATH

    explicit = Path(known.config)
    if not explicit.exists():
        raise FileNotFoundError(f"Config file not found: {explicit}")
    return explicit


def _resolve_adapter(
    adapter_spec: str, settings: Settings, tz: tzinfo | None = None
) -> DeviceAdapter:
    """Resolve *adapter_spec* to an instantiated :class:`DeviceAdapter`.

    The short names ``mock``, ``mock-bp``, ``mock-spo2``, ``mock-temp``,
    ``mock-weight``, ``miband10``, ``bp``, ``spo2``, ``temp``, and ``weight`` map
    to the shipped built-in adapters.  Any other value is
    treated as a fully qualified ``package.module.ClassName`` and imported
    dynamically, so third-party adapters are selectable without modifying the
    repository (FR-13).

    Args:
        adapter_spec: Either a short name (``mock``/``miband10``) or a fully
            qualified class path.
        settings: The loaded application settings (passed through to adapters
            that accept configuration).
        tz: The resolved timezone in which to interpret a device's zoneless
            timestamp, forwarded to the three timestamp-decoding BLE adapters
            (``bp``, ``temp``, ``weight``).  ``None`` preserves host-local
            behavior (FR-CFG-4, design §4).

    Returns:
        An instantiated ``DeviceAdapter``.

    Raises:
        ValueError: If a fully qualified spec is malformed.
        RuntimeError: If the target module or class cannot be imported, or the
            resolved class is not a ``DeviceAdapter`` subclass.
    """
    if adapter_spec == "mock":
        return MockAdapter()
    if adapter_spec == "mock-bp":
        return MockBloodPressureAdapter()
    if adapter_spec == "miband10":
        return MiBand10Adapter(device_name=settings.device_name)
    if adapter_spec == "bp":
        return BloodPressureBleAdapter(device_name=settings.device_name, tz=tz)
    if adapter_spec == "spo2":
        return PulseOximeterBleAdapter(device_name=settings.device_name)
    if adapter_spec == "mock-spo2":
        return MockOximeterAdapter()
    if adapter_spec == "temp":
        return HealthThermometerBleAdapter(device_name=settings.device_name, tz=tz)
    if adapter_spec == "mock-temp":
        return MockThermometerAdapter()
    if adapter_spec == "weight":
        return WeightScaleBleAdapter(device_name=settings.device_name, tz=tz)
    if adapter_spec == "mock-weight":
        return MockWeightAdapter()

    if "." not in adapter_spec:
        raise ValueError(
            f"Unknown adapter '{adapter_spec}'. Use 'mock', 'mock-bp', 'mock-spo2', "
            "'mock-temp', 'mock-weight', 'miband10', 'bp', 'spo2', 'temp', 'weight', "
            "or a fully qualified 'package.module.ClassName'."
        )

    module_path, _, class_name = adapter_spec.rpartition(".")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise RuntimeError(f"Could not import adapter module '{module_path}'.") from exc

    try:
        adapter_class = getattr(module, class_name)
    except AttributeError as exc:
        raise RuntimeError(
            f"Adapter module '{module_path}' has no class '{class_name}'."
        ) from exc

    if not (isinstance(adapter_class, type) and issubclass(adapter_class, DeviceAdapter)):
        raise RuntimeError(
            f"Adapter '{adapter_spec}' is not a DeviceAdapter subclass."
        )

    return adapter_class()


def _build_orchestrator(
    adapter: DeviceAdapter,
    settings: Settings,
    *,
    patient_ref: str,
    device_ref: str,
    sinks: list[ObservationSink],
    state_relay: Callable[[ConnectionState], Awaitable[None]],
) -> Orchestrator:
    """Assemble the validator chain and construct the orchestrator.

    Args:
        adapter: The resolved device adapter.
        settings: The loaded application settings.
        patient_ref: The ``Patient/<id>`` reference for produced Observations.
        device_ref: The ``Device/<id>`` reference for produced Observations.
        sinks: The ordered list of observation sinks (store + broadcaster).
        state_relay: The coroutine invoked on connection-state changes.

    Returns:
        A wired :class:`~vitals_on_fhir.pipeline.Orchestrator`.
    """
    bp_overrides: dict[tuple[type, str], tuple[float, float]] = {
        (BloodPressure, "systolic"): (settings.bp_systolic_min, settings.bp_systolic_max),
        (BloodPressure, "diastolic"): (settings.bp_diastolic_min, settings.bp_diastolic_max),
    }
    scalar_overrides: dict[type, tuple[float, float]] = {
        HeartRate: (settings.hr_min, settings.hr_max),
        OxygenSaturation: (settings.spo2_min, settings.spo2_max),
        BodyTemperature: (settings.temp_min, settings.temp_max),
        BodyWeight: (settings.weight_min, settings.weight_max),
    }
    chain = ValidatorChain(
        [
            PlausibleRangeValidator(overrides=scalar_overrides),
            SensorContactValidator(),
            ComponentRangeValidator(bp_overrides),
            DuplicateValidator(),
        ]
    )
    return Orchestrator(
        adapter,
        chain,
        ScalarVitalMapper(),
        sinks,
        patient_ref=patient_ref,
        device_ref=device_ref,
        state_relay=state_relay,
    )


async def _run(settings: Settings, adapter_spec: str) -> None:
    """Wire every component and run serving + acquisition concurrently.

    Builds the adapter, startup FHIR resources, store, broadcaster,
    orchestrator, and FastAPI app, then runs the uvicorn server and the
    orchestrator together in the current event loop.  Adapter/orchestrator
    errors are caught and logged at the boundary so a failure in acquisition
    does not silently crash serving (``tech.md`` error-handling rule); the
    measurement value and the token never appear in any log message.

    Args:
        settings: The loaded application settings.
        adapter_spec: The adapter short name or fully qualified class path.
    """
    # Resolve the configured zone once at startup; threaded to the three
    # timestamp-decoding BLE adapters (FR-CFG-4, design §4).
    tz = resolve_timezone(settings.timezone)
    adapter = _resolve_adapter(adapter_spec, settings, tz)

    device = build_device(adapter.device_info)
    patient = build_patient(settings.patient_id)
    patient_ref = f"Patient/{patient.id}"
    device_ref = f"Device/{device.id}"

    store = InMemoryObservationStore(settings.store_max)
    broadcaster = DashboardBroadcaster()

    sinks: list[ObservationSink] = [store, broadcaster]
    orchestrator = _build_orchestrator(
        adapter,
        settings,
        patient_ref=patient_ref,
        device_ref=device_ref,
        sinks=sinks,
        state_relay=broadcaster.on_state_change,
    )

    app = create_app(
        store=store,
        authenticator=StaticTokenAuthenticator(settings.api_token),
        # ``api`` cannot import ``dashboard`` (dependency-direction rules), so it
        # declares a wider ``BroadcasterLike`` (register/unregister take ``object``).
        # ``DashboardBroadcaster`` narrows those parameters to ``WebSocketLike``;
        # the composition root bridges the two structurally-compatible protocols.
        broadcaster=cast(BroadcasterLike, broadcaster),
        patient=patient,
        device=device,
        static_dir=_STATIC_DIR,
    )

    server = uvicorn.Server(
        uvicorn.Config(app, host=settings.host, port=settings.port, log_level="info")
    )

    logger.info("Starting vitals-on-fhir on %s:%d", settings.host, settings.port)

    async def _acquire() -> None:
        """Run the acquisition pipeline, logging failures at the boundary."""
        try:
            await orchestrator.run()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Acquisition pipeline stopped due to an error.")

    await asyncio.gather(server.serve(), _acquire())


def main() -> None:
    """Start the vitals-on-fhir service.

    Loads :class:`~vitals_on_fhir.config.Settings` from the environment, parses
    ``--adapter`` (defaulting to the configured adapter), and hands off to
    :func:`_run` inside a single ``asyncio.run`` — the only ``asyncio.run``
    call in the codebase.  Configuration values (including ``VOF_API_TOKEN``)
    are never logged (NFR-5).
    """
    # ``--config`` selects which file the YAML tier reads and must be known
    # before Settings is built, so resolve it via a small parse_known_args pass
    # first (FR-CFG-6, design §4).  An explicit missing path fails loud here;
    # any Settings() construction error (unknown key, malformed YAML, invalid
    # timezone) propagates unmodified and aborts startup (design Error Handling).
    config_path = _resolve_config_path()

    # Fields are sourced from CLI init, the environment (VOF_ prefix), and
    # config.yaml; see Settings for the precedence chain.
    settings = Settings(_yaml_path=config_path)

    parser = argparse.ArgumentParser(prog="vitals-on-fhir")
    parser.add_argument(
        "--config",
        default=None,
        help=(
            "Path to the config.yaml file (default: config.yaml in the working "
            "directory). An explicit path that does not exist fails at startup."
        ),
    )
    parser.add_argument(
        "--adapter",
        default=settings.adapter,
        help=(
            "Device adapter: 'mock', 'mock-bp', 'mock-spo2', 'mock-temp', "
            "'mock-weight', 'miband10', 'bp', 'spo2', 'temp', 'weight', or a "
            "fully qualified 'package.module.ClassName'."
        ),
    )
    args = parser.parse_args()

    asyncio.run(_run(settings, args.adapter))
