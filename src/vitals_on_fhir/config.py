# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed application settings loaded from environment variables.

All configuration is loaded once at startup (in ``cli.py``) and passed
explicitly to every component that needs it.  No module-level global config
object; no mutation after startup.

Environment variables use the ``VOF_`` prefix.  Unknown ``VOF_*`` variables
are rejected at startup (``extra = "forbid"``).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings sourced from environment variables (``VOF_`` prefix).

    Instantiate once in ``cli.py`` and pass to components explicitly.
    Never log the ``api_token`` field at any level.
    """

    model_config = SettingsConfigDict(env_prefix="VOF_", extra="forbid")

    # Required — no default; must be supplied via VOF_API_TOKEN
    api_token: str

    # Network
    host: str = "127.0.0.1"
    port: int = 8000

    # Device
    adapter: str = "mock"
    device_name: str | None = None

    # Validation bounds
    hr_min: float = 20.0
    hr_max: float = 250.0

    # Storage
    patient_id: str = "local-patient"
    store_max: int = 10000
