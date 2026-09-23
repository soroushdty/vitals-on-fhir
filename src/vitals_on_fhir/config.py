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

    model_config = SettingsConfigDict(
        env_prefix="VOF_",
        extra="forbid",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Required — no default; must be supplied via VOF_API_TOKEN
    api_token: str

    # Network
    host: str = "127.0.0.1"
    port: int = 8000

    # Device
    adapter: str = "mock"
    device_name: str | None = None

    # Validation bounds — heart rate (bpm)
    hr_min: float = 20.0
    hr_max: float = 250.0

    # Validation bounds — blood pressure components (mmHg)
    bp_systolic_min: float = 50.0
    bp_systolic_max: float = 250.0
    bp_diastolic_min: float = 30.0
    bp_diastolic_max: float = 150.0

    # Validation bounds — oxygen saturation (%)
    spo2_min: float = 70.0
    spo2_max: float = 100.0

    # Validation bounds — body temperature (Cel); physical-plausibility, not clinical
    temp_min: float = 10.0
    temp_max: float = 47.0

    # Storage
    patient_id: str = "local-patient"
    store_max: int = 10000
