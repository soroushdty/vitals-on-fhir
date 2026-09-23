# SPDX-License-Identifier: AGPL-3.0-or-later
"""FastAPI application factory.

``create_app`` is the single entry point for constructing the FastAPI
application instance.  It wires the read-only FHIR routes, the
``OperationOutcome`` exception handler, the dependency providers, the dashboard
static files, and the dashboard WebSocket endpoint together.  The composition
root (``cli.py``) calls this function, passing in the concrete instances it
built (store, authenticator, broadcaster, and the startup-built ``Patient`` /
``Device`` resources), and hands the resulting app to uvicorn.

There are no module-level singletons: every collaborator is injected as a
parameter and exposed to route handlers through ``app.dependency_overrides``.

Dependency-direction note (``structure.md``): ``api`` must NOT import
``dashboard``.  The broadcaster is therefore accepted *structurally* (see
:class:`BroadcasterLike`), and the dashboard static assets are located via a
path passed in by ``cli.py`` — this module never imports
``vitals_on_fhir.dashboard``.

Allowed imports: stdlib, ``fastapi``/``starlette``, ``store/``, ``fhir/``,
``vitals/``.  Must NOT import from ``adapters``, ``validation``, ``pipeline``,
``dashboard``, or ``cli``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast, runtime_checkable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from vitals_on_fhir.api import routes
from vitals_on_fhir.api.auth import Authenticator
from vitals_on_fhir.store import ObservationStore

if TYPE_CHECKING:
    from fhir.resources.R4B.device import Device
    from fhir.resources.R4B.patient import Patient
    from starlette.types import ExceptionHandler

logger = logging.getLogger(__name__)

#: WebSocket close code for a policy violation (RFC 6455 §7.4.1); used when the
#: dashboard handshake presents a missing or invalid token.
_WS_POLICY_VIOLATION = 1008


@runtime_checkable
class BroadcasterLike(Protocol):
    """Structural interface for the dashboard broadcaster.

    ``api`` must not import ``dashboard`` (dependency-direction rules), so the
    broadcaster is accepted structurally.  Any object exposing async
    ``register`` and ``unregister`` methods that take a WebSocket-like object
    satisfies this protocol — in production this is the
    ``DashboardBroadcaster`` instance built in ``cli.py``.
    """

    async def register(self, websocket: object) -> None:
        """Register an already-authenticated WebSocket connection."""
        ...

    async def unregister(self, websocket: object) -> None:
        """Drop a WebSocket connection from the active set."""
        ...


def create_app(
    *,
    store: ObservationStore,
    authenticator: Authenticator,
    broadcaster: BroadcasterLike,
    patient: Patient,
    device: Device,
    static_dir: str | Path | None = None,
) -> FastAPI:
    """Construct and return the configured FastAPI application.

    All collaborators are injected by the composition root (``cli.py``); this
    factory holds no module-level singletons.  The concrete instances are
    exposed to the plain ``async def`` route handlers through
    ``app.dependency_overrides`` so the handlers depend only on the provider
    callables declared in :mod:`vitals_on_fhir.api.routes`.

    The returned app:

    - registers the read-only FHIR routes (``routes.router``);
    - installs the :class:`~vitals_on_fhir.api.routes.FhirHttpError` handler so
      auth (401) and not-found (404) errors render as ``OperationOutcome``
      served as ``application/fhir+json`` (FR-11, FR-12);
    - overrides the store / authenticator / patient / device providers with the
      injected instances (FR-11);
    - mounts the dashboard static assets at ``/`` when *static_dir* exists
      (FR-5); mounting is defensive — a missing directory is created so an
      empty dashboard does not crash startup (task 11.2 populates it);
    - registers the ``/ws`` dashboard WebSocket endpoint, validating the token
      from the ``?token=`` query parameter with the shared ``Authenticator``
      **before** ``accept()`` and closing unauthenticated sockets with code
      ``1008`` — the token is never logged (FR-12.2, NFR-5).

    Args:
        store: The observation store serving FHIR reads and receiving pushes.
        authenticator: The authenticator used for both HTTP bearer tokens and
            the WebSocket handshake token.
        broadcaster: The dashboard broadcaster; authenticated WebSocket
            connections are registered with it after ``accept()``.
        patient: The startup-built local ``Patient`` resource.
        device: The startup-built ``Device`` resource for the connected device.
        static_dir: Filesystem path to the dashboard static assets.  When
            ``None``, no static mount is added (useful for API-only tests).

    Returns:
        A fully configured :class:`fastapi.FastAPI` instance ready for uvicorn.
    """
    app = FastAPI(title="vitals-on-fhir", docs_url=None, redoc_url=None)

    # Read-only FHIR routes and the OperationOutcome error handler.  Starlette
    # types handlers against the base ``Exception``, so the concrete-subtype
    # handler is cast to match the expected signature (runtime is unchanged).
    app.include_router(routes.router)
    app.add_exception_handler(
        routes.FhirHttpError,
        cast("ExceptionHandler", routes.fhir_error_handler),
    )

    # Inject the concrete collaborators.  Route handlers depend only on the
    # provider callables; the placeholders raise until overridden here, so a
    # missing wiring fails loudly rather than serving nothing.
    app.dependency_overrides[routes.get_store] = lambda: store
    app.dependency_overrides[routes.get_authenticator] = lambda: authenticator
    app.dependency_overrides[routes.get_patient_resource] = lambda: patient
    app.dependency_overrides[routes.get_device_resource] = lambda: device

    _register_websocket(app, authenticator=authenticator, broadcaster=broadcaster)

    if static_dir is not None:
        _mount_static(app, static_dir)

    return app


def _register_websocket(
    app: FastAPI,
    *,
    authenticator: Authenticator,
    broadcaster: BroadcasterLike,
) -> None:
    """Register the ``/ws`` dashboard WebSocket endpoint on *app*.

    The endpoint reads the bearer token from the ``?token=`` query parameter
    (browsers cannot set custom WebSocket handshake headers) and validates it
    with the shared :class:`Authenticator` **before** ``accept()``.  On
    failure the socket is closed with code ``1008`` and never registered with
    the broadcaster.  On success the socket is accepted, registered, and held
    open — all data is server-pushed by the broadcaster — until the client
    disconnects, at which point it is unregistered.  The token is never logged
    (FR-12.2, NFR-5).

    Args:
        app: The FastAPI app to register the endpoint on.
        authenticator: The authenticator used for the handshake token check.
        broadcaster: The broadcaster to register authenticated sockets with.
    """

    @app.websocket("/ws")
    async def dashboard_ws(websocket: WebSocket) -> None:
        """Authenticate and hold open a dashboard WebSocket connection."""
        token = websocket.query_params.get("token", "")
        if not token or not authenticator.authenticate(token):
            # Reject before accepting the handshake; never log the token.
            logger.info("Rejecting unauthenticated dashboard WebSocket connection")
            await websocket.close(code=_WS_POLICY_VIOLATION)
            return

        await websocket.accept()
        await broadcaster.register(websocket)
        logger.info("Dashboard WebSocket connection accepted")
        try:
            # All data is server-pushed; we only wait for the client to close.
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            logger.info("Dashboard WebSocket connection closed by client")
        finally:
            await broadcaster.unregister(websocket)


def _mount_static(app: FastAPI, static_dir: str | Path) -> None:
    """Mount the dashboard static assets at ``/`` (defensively).

    The directory may not exist yet (task 11.2 creates the dashboard assets);
    to keep startup robust it is created if missing so mounting an empty
    directory does not raise.  ``html=True`` serves ``index.html`` at ``/``.

    Args:
        app: The FastAPI app to mount the static files on.
        static_dir: Filesystem path to the dashboard static assets.
    """
    path = Path(static_dir)
    path.mkdir(parents=True, exist_ok=True)
    app.mount("/", StaticFiles(directory=str(path), html=True), name="dashboard")
