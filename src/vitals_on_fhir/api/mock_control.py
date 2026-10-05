# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dashboard control for the mock adapter's heart-rate scenario.

Two token-protected endpoints, registered only when the composition root passes
a :class:`ScenarioControl` to ``create_app`` (i.e. only with ``--adapter mock``):

- ``GET /mock/scenarios`` — the selectable scenarios and the active one.
- ``PUT /mock/scenario`` with ``{"scenario": "<id>"}`` — start that scenario from
  the beginning (restarting it if it is already running).

With any other adapter the paths are not registered, so they answer ``404`` and
the dashboard hides its simulator panel.

Allowed imports: stdlib, ``fastapi``/``pydantic``, and the rest of ``api/``.
The control is accepted structurally so ``api`` never imports ``adapters``.
"""

from __future__ import annotations

from typing import Protocol

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from vitals_on_fhir.api.routes import require_token


class ScenarioControl(Protocol):
    """Structural interface for something that can start a simulated scenario."""

    @property
    def current(self) -> str:
        """Return the id of the active scenario."""
        ...

    def options(self) -> list[dict[str, str]]:
        """Return every scenario as ``{"id", "label", "description"}``."""
        ...

    def start(self, scenario_id: str) -> None:
        """Start *scenario_id* from the beginning, raising ``ValueError`` if it is unknown."""
        ...


class ScenarioRequest(BaseModel):
    """Body of ``PUT /mock/scenario``."""

    scenario: str


def build_router(control: ScenarioControl) -> APIRouter:
    """Return the router exposing *control*, with every route requiring the token."""
    router = APIRouter(prefix="/mock", dependencies=[Depends(require_token)])

    @router.get("/scenarios")
    async def list_scenarios() -> dict[str, object]:
        """List the selectable scenarios and which one is active."""
        return {"current": control.current, "scenarios": control.options()}

    @router.put("/scenario")
    async def set_scenario(body: ScenarioRequest) -> dict[str, str]:
        """Start a scenario from the beginning; ``400`` if the id is unknown."""
        try:
            control.start(body.scenario)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"current": control.current}

    return router
