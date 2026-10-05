# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed application settings loaded from environment variables and an optional YAML file.

All configuration is loaded once at startup (in ``cli.py``) and passed
explicitly to every component that needs it.  No module-level global config
object; no mutation after startup.

Environment variables use the ``VOF_`` prefix.  An optional YAML file (see
``config.example.yaml``) may supply the same keys without the prefix, in
lowercase.  Precedence, highest first: process environment, ``.env``, YAML
file, field defaults.  Unknown ``VOF_*`` variables and unknown YAML keys are
rejected at startup (``extra = "forbid"``).  Secrets (``api_token``) belong in
the environment or ``.env``, never in a committed YAML file.
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any, Self

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

# The YAML path is only known per instantiation, but pydantic-settings resolves
# its sources on the class.  ``Settings.__init__`` publishes the path here for
# the duration of the call so ``settings_customise_sources`` can read it.
_YAML_PATH: ContextVar[Path | None] = ContextVar("_YAML_PATH", default=None)


class Settings(BaseSettings):
    """Application settings sourced from the environment (``VOF_`` prefix) and YAML.

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

    # Mock heart-rate adapter: the simulated rate wanders within this range (bpm)
    # and a reading is emitted every ``mock_interval`` seconds.
    mock_hr_min: float = 40.0
    mock_hr_max: float = 100.0
    mock_interval: float = Field(default=1.0, gt=0)

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

    def __init__(self, *, _yaml_path: Path | None = None, **kwargs: Any) -> None:
        """Load settings, optionally layering in the YAML file at *_yaml_path*.

        Args:
            _yaml_path: Path to a YAML config file, or ``None`` for none.  The
                file is lower-precedence than environment variables and ``.env``.
            **kwargs: Explicit field values (highest precedence), as for any
                ``BaseSettings``.
        """
        token = _YAML_PATH.set(_yaml_path)
        try:
            super().__init__(**kwargs)
        finally:
            _YAML_PATH.reset(token)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order the sources: init, environment, ``.env``, YAML file, secrets."""
        sources: list[PydanticBaseSettingsSource] = [init_settings, env_settings, dotenv_settings]
        yaml_path = _YAML_PATH.get()
        if yaml_path is not None:
            sources.append(YamlConfigSettingsSource(settings_cls, yaml_file=yaml_path))
        sources.append(file_secret_settings)
        return tuple(sources)

    @model_validator(mode="after")
    def _check_mock_hr_range(self) -> Self:
        """Require ``mock_hr_min < mock_hr_max`` so the simulated rate can vary."""
        if self.mock_hr_min >= self.mock_hr_max:
            raise ValueError("mock_hr_min must be less than mock_hr_max")
        return self
