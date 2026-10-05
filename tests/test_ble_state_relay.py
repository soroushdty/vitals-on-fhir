# SPDX-License-Identifier: AGPL-3.0-or-later
"""Connection-state changes from real BLE adapters must reach the dashboard.

The BLE adapters already report every transition (``CONNECTING``,
``CONNECTED``, ``RECONNECTING``, ``DISCONNECTED``) through an
``on_state_change`` callback; ``cli.py`` has to hand them one, or a dropout and
the automatic reconnect never show on the dashboard.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from vitals_on_fhir import cli
from vitals_on_fhir.adapters import ConnectionState
from vitals_on_fhir.config import Settings
from vitals_on_fhir.dashboard import DashboardBroadcaster

_BLE_ADAPTERS = {
    "miband10": "MiBand10Adapter",
    "bp": "BloodPressureBleAdapter",
    "spo2": "PulseOximeterBleAdapter",
    "temp": "HealthThermometerBleAdapter",
    "weight": "WeightScaleBleAdapter",
}


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings with a token and no YAML file."""
    monkeypatch.setenv("VOF_API_TOKEN", "test-token-do-not-use")
    return Settings(_yaml_path=tmp_path / "absent.yaml")


@pytest.mark.parametrize("name, class_name", _BLE_ADAPTERS.items())
def test_every_builtin_ble_adapter_is_given_the_state_callback(
    name: str, class_name: str, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_resolve_adapter`` forwards ``on_state_change`` to each real-device adapter."""
    received: dict[str, Any] = {}

    class _Recorder:
        def __init__(self, **kwargs: Any) -> None:
            received.update(kwargs)

    async def relay(state: ConnectionState) -> None:
        """Stand-in for the broadcaster's ``on_state_change``."""

    monkeypatch.setattr(cli, class_name, _Recorder)

    cli._resolve_adapter(name, settings, None, relay)

    assert received["on_state_change"] is relay


def test_reconnect_states_from_a_real_adapter_reach_dashboard_clients(
    settings: Settings,
) -> None:
    """A dropout and reconnect on a Mi Band adapter are pushed to a connected client."""

    class _Client:
        def __init__(self) -> None:
            self.states: list[str] = []

        async def send_text(self, data: str) -> None:
            envelope = json.loads(data)
            if envelope["type"] == "connection_state":
                self.states.append(envelope["state"])

        async def close(self) -> None:
            """Nothing to close."""

    async def run() -> list[str]:
        broadcaster = DashboardBroadcaster()
        client = _Client()
        await broadcaster.register(client)
        adapter = cli._resolve_adapter("miband10", settings, None, broadcaster.on_state_change)
        connection = adapter._connection  # type: ignore[attr-defined]
        # What BleConnection does when the band drops and is found again.
        for state in (
            ConnectionState.CONNECTED,
            ConnectionState.RECONNECTING,
            ConnectionState.CONNECTING,
            ConnectionState.CONNECTED,
        ):
            await connection._set_state(state)
        return client.states

    assert asyncio.run(run()) == ["connected", "reconnecting", "connecting", "connected"]
