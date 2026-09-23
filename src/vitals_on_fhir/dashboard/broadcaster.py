# SPDX-License-Identifier: AGPL-3.0-or-later
"""DashboardBroadcaster — WebSocket push sink for the live dashboard.

Maintains a set of active, authenticated WebSocket connections.  On each
``publish()`` call the Observation is serialised to FHIR JSON and sent to
every connected client.  Connection-state changes relayed from the adapter
(via ``on_state_change``) are pushed to every client so the dashboard can
show disconnection and reconnection in real time.

Two WebSocket message envelopes are emitted (see design §10 / Data Models):

- ``{"type": "observation", "resource": {...full FHIR Observation...}}``
- ``{"type": "connection_state", "state": "<state>"}``

The ``resource`` payload is the exact FHIR JSON produced by
``Observation.model_dump_json()``; the dashboard never receives a non-FHIR
measurement representation (FR-8).

Allowed imports: ``pipeline/`` (for ``ObservationSink``), ``fhir/``,
``vitals/``, and stdlib only.  This module must NOT import from ``adapters``,
``validation``, ``api``, or ``cli`` (dependency-direction rules).  In
particular the adapter's ``ConnectionState`` is never imported here;
``on_state_change`` accepts the state structurally.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from vitals_on_fhir.pipeline.base import ObservationSink

if TYPE_CHECKING:
    from fhir.resources.R4B.observation import Observation

logger = logging.getLogger(__name__)


@runtime_checkable
class WebSocketLike(Protocol):
    """Minimal structural interface for a dashboard WebSocket connection.

    The broadcaster does not depend on FastAPI/Starlette concrete WebSocket
    types.  Any object exposing async ``send_text`` and ``close`` methods can
    be registered — this keeps the dashboard decoupled from the web framework
    and makes it trivial to substitute in-memory fakes in tests.
    """

    async def send_text(self, data: str) -> None:
        """Send a text frame to the connected client."""
        ...

    async def close(self) -> None:
        """Close the underlying connection."""
        ...


def _state_value(state: object) -> str:
    """Return the wire string for a connection *state*.

    Accepts the state structurally so the dashboard need not import the
    adapter's ``ConnectionState`` enum.  Enum members contribute their
    ``value`` (falling back to their ``name``); anything else is stringified.

    Args:
        state: A connection-state value.  Typically an ``enum.Enum`` member
            (e.g. ``ConnectionState.CONNECTED``) or a plain string.

    Returns:
        The string used in the ``connection_state`` envelope.
    """
    if isinstance(state, enum.Enum):
        value = state.value
        return value if isinstance(value, str) else state.name
    return str(state)


class DashboardBroadcaster(ObservationSink):
    """Fans each FHIR Observation out to all connected WebSocket clients.

    This class is an :class:`~vitals_on_fhir.pipeline.base.ObservationSink`
    that also relays connection-state updates from the adapter (via
    :meth:`on_state_change`) so the dashboard reflects live connection status.

    WebSocket connections must be authenticated by the endpoint *before* being
    registered with :meth:`register`; the broadcaster performs no
    authentication itself.  On :meth:`publish`, the Observation is serialised
    once with ``Observation.model_dump_json()`` and broadcast to every active
    connection.  Connections that raise on send are logged and unregistered so
    one failing socket never blocks delivery to the others.

    The active-connection set is guarded by an :class:`asyncio.Lock`.
    """

    def __init__(self) -> None:
        """Create a broadcaster with an empty set of connections."""
        self._connections: set[WebSocketLike] = set()
        self._lock = asyncio.Lock()

    async def register(self, websocket: WebSocketLike) -> None:
        """Add an already-authenticated *websocket* to the active set.

        Called by the WebSocket endpoint after the handshake token check has
        passed.  The broadcaster assumes the socket is authenticated.

        Args:
            websocket: A connected, authenticated WebSocket-like object.
        """
        async with self._lock:
            self._connections.add(websocket)
        logger.info("Dashboard client registered; active clients: %d", len(self._connections))

    async def unregister(self, websocket: WebSocketLike) -> None:
        """Remove *websocket* from the active set if present.

        Safe to call for a socket that is not registered.

        Args:
            websocket: The WebSocket-like object to drop.
        """
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("Dashboard client unregistered; active clients: %d", len(self._connections))

    async def publish(self, observation: Observation) -> None:
        """Serialise *observation* to FHIR JSON and push to all active clients.

        The Observation is serialised exactly once via
        ``Observation.model_dump_json()`` and wrapped in an ``observation``
        envelope.  Per-connection send errors are caught and logged, and the
        offending socket is unregistered, so delivery to the remaining clients
        is unaffected.  This method never raises (``ObservationSink`` contract).

        Args:
            observation: The FHIR Observation produced by the mapper for one
                validated reading.
        """
        resource_json = observation.model_dump_json()
        # Embed the FHIR JSON as a parsed object under "resource" so the client
        # receives a single JSON document, not a JSON-encoded string.
        envelope = '{"type": "observation", "resource": ' + resource_json + "}"
        await self._broadcast(envelope)

    async def on_state_change(self, state: object) -> None:
        """Push a ``connection_state`` envelope to all clients.

        Relayed by the orchestrator (via an injected callback) when the
        adapter's connection state changes, so the dashboard can show
        disconnection and resume on reconnect (FR-6, FR-10).  Never raises.

        Args:
            state: The new connection state.  Accepted structurally so the
                dashboard need not import the adapter's ``ConnectionState``.
        """
        envelope = json.dumps({"type": "connection_state", "state": _state_value(state)})
        await self._broadcast(envelope)

    async def _broadcast(self, message: str) -> None:
        """Send *message* to every active connection, pruning failed sockets.

        A snapshot of the connection set is taken under the lock so sends can
        proceed without holding it.  Sockets that raise on send are collected
        and unregistered afterwards; errors are logged (no measurement values
        or secrets appear in log messages).

        Args:
            message: The pre-serialised JSON envelope to send.
        """
        async with self._lock:
            connections = list(self._connections)

        failed: list[WebSocketLike] = []
        for websocket in connections:
            try:
                await websocket.send_text(message)
            except Exception:
                # A closed or broken socket must not stop delivery to the rest.
                logger.info("Dropping dashboard client after send failure", exc_info=True)
                failed.append(websocket)

        for websocket in failed:
            await self.unregister(websocket)
