# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared pytest fixtures."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from vitals_on_fhir.adapters import ble as ble_module


@pytest.fixture(autouse=True)
def _no_system_bluetooth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the fast suite off the host's Bluetooth stack.

    ``BleConnection`` asks BlueZ over D-Bus for already-connected devices when
    a scan finds nothing. Tests fake ``bleak`` but would still reach the real
    system bus (and any real device connected to the machine) through that
    lookup, so it reports no connected devices unless a test patches it.
    """

    async def _none(_service_uuid: str) -> list[Any]:
        return []

    monkeypatch.setattr(ble_module, "_find_connected_devices", _none)


@pytest.fixture(autouse=True)
def _restore_package_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Undo ``cli.main()``'s logging setup after each test.

    ``main()`` adds a stderr handler to the ``vitals_on_fhir`` logger; left in
    place it would outlive the test's captured stderr.
    """
    package_logger = logging.getLogger("vitals_on_fhir")
    monkeypatch.setattr(package_logger, "handlers", list(package_logger.handlers))
    monkeypatch.setattr(package_logger, "level", package_logger.level)
