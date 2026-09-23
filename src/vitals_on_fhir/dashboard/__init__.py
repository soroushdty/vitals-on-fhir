# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``dashboard`` package — WebSocket push and static UI."""

from vitals_on_fhir.dashboard.broadcaster import DashboardBroadcaster

__all__ = [
    # Concrete defaults
    "DashboardBroadcaster",
]
