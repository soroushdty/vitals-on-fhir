# SPDX-License-Identifier: AGPL-3.0-or-later
"""Starting a mock scenario leaves nothing of the previous run behind.

Wires the real pieces the way ``cli.py`` does (mock adapter, orchestrator,
in-memory store, dashboard broadcaster) and starts a new scenario while the
first is running.  Every Observation stored afterwards, and every one a client
receives after the ``reset`` message, must belong to the new run.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from vitals_on_fhir.adapters import HeartRateScenarioControl, MockAdapter
from vitals_on_fhir.cli import _build_orchestrator, _resolve_adapter, _restart_hook
from vitals_on_fhir.config import Settings
from vitals_on_fhir.dashboard import DashboardBroadcaster
from vitals_on_fhir.store import InMemoryObservationStore


class _FakeSocket:
    """Records every frame sent to it."""

    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_text(self, data: str) -> None:
        self.messages.append(json.loads(data))

    async def close(self) -> None:
        """Nothing to close."""


def _value(resource: object) -> float:
    """Return the bpm of an Observation resource (parsed JSON)."""
    assert isinstance(resource, dict)
    return float(resource["valueQuantity"]["value"])


def test_starting_a_scenario_clears_store_and_dashboards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a restart the store and every client hold only readings from the new run."""
    monkeypatch.setenv("VOF_API_TOKEN", "test-token-do-not-use")
    settings = Settings(_yaml_path=tmp_path / "absent.yaml", mock_interval=0.01)

    async def run() -> tuple[list[float], list[dict[str, object]]]:
        store = InMemoryObservationStore(1000)
        broadcaster = DashboardBroadcaster()
        client = _FakeSocket()
        await broadcaster.register(client)

        adapter = _resolve_adapter(
            "mock", settings, None, broadcaster.on_state_change, _restart_hook(store, broadcaster)
        )
        assert isinstance(adapter, MockAdapter)
        control = HeartRateScenarioControl(adapter)
        orchestrator = _build_orchestrator(
            adapter,
            settings,
            patient_ref="Patient/p",
            device_ref="Device/d",
            sinks=[store, broadcaster],
            state_relay=broadcaster.on_state_change,
        )
        task = asyncio.create_task(orchestrator.run())

        async def stored_values() -> list[float]:
            return [_value(o.model_dump(mode="json")) for o in await store.search()]

        while len(await stored_values()) < 10:  # a normal-rhythm run (60-100 bpm)
            await asyncio.sleep(0.01)
        control.start("sinus_bradycardia")  # new run: always below 60
        while len([v for v in await stored_values() if v < 60]) < 5:
            await asyncio.sleep(0.01)

        await adapter.disconnect()
        await asyncio.wait_for(task, timeout=5)
        return await stored_values(), client.messages

    stored, messages = asyncio.run(run())

    assert stored and all(v < 60 for v in stored)  # nothing from the old run is stored

    types = [m["type"] for m in messages]
    reset_at = types.index("reset")
    before = [_value(m["resource"]) for m in messages[:reset_at] if m["type"] == "observation"]
    after = [_value(m["resource"]) for m in messages[reset_at + 1 :] if m["type"] == "observation"]
    assert before and all(60 <= v <= 100 for v in before)
    assert after and all(v < 60 for v in after)  # no stale old-run reading after the reset
    assert types.count("reset") == 1
