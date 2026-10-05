# SPDX-License-Identifier: AGPL-3.0-or-later
"""Typed application settings loaded from environment variables and YAML.

All configuration is loaded once at startup (in ``cli.py``) and passed
explicitly to every component that needs it.  No module-level global config
object; no mutation after startup.

Configuration sources, highest priority first:

1. constructor keyword arguments (``init``),
2. environment variables (the ``VOF_`` prefix),
3. a ``.env`` file (same ``VOF_`` prefix),
4. a ``config.yaml`` file whose keys are :class:`Settings` field names
   (``hr_min``, ``timezone``, ...), *not* ``VOF_``-prefixed,
5. the built-in field defaults.

The ``config.yaml`` tier is always part of the precedence chain; when the file
is absent it simply contributes nothing (a no-op), exactly as ``.env`` does when
no ``.env`` file exists.  Unknown keys from any source are rejected at startup
(``extra = "forbid"``).
"""

from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CONFIG_PATH = Path("config.yaml")
"""Default ``config.yaml`` location: the process working directory (repo root)."""


def resolve_timezone(name: str) -> ZoneInfo | None:
    """Resolve a ``timezone`` setting to a ``tzinfo``, or ``None`` for host-local.

    ``"local"`` returns ``None`` (signalling "use the host's local zone", the
    default behaviour).  Any other value is treated as an IANA zone name (e.g.
    ``"UTC"`` or ``"America/Phoenix"``) and resolved to a :class:`zoneinfo.ZoneInfo`.
    An unresolvable value raises :class:`ValueError` naming the offending value.
    """
    if name == "local":
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Invalid timezone setting: {name!r}") from exc


class Settings(BaseSettings):
    """Application settings sourced from CLI init, env (``VOF_`` prefix), and YAML.

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

    # Mock heart-rate adapter: seconds between simulated readings.  The rhythm
    # itself is chosen from the dashboard, not configured.
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

    # Validation bounds — body weight (kg); physical-plausibility, not clinical
    weight_min: float = 2.0
    weight_max: float = 650.0

    # Storage
    patient_id: str = "local-patient"
    store_max: int = 10000

    # Device-timestamp interpretation (FR-CFG-4).
    # "local" preserves today's host-local behaviour; an explicit zone name
    # (e.g. "UTC" or "America/Phoenix") interprets a device's zoneless
    # timestamp as being in that zone.
    timezone: str = "local"

    # Runtime ``config.yaml`` path, chosen by the composition root and threaded
    # into the YAML source below.  Not a settings field; carried on the class so
    # the ``settings_customise_sources`` classmethod can read it.
    _yaml_path: Path = DEFAULT_CONFIG_PATH

    def __init__(self, _yaml_path: Path | str = DEFAULT_CONFIG_PATH, **kwargs: Any) -> None:
        """Construct settings, reading YAML from ``_yaml_path`` (default ``config.yaml``).

        ``_yaml_path`` selects which file the YAML tier reads; it is not itself a
        settings field.  When the file is absent the YAML tier contributes nothing.
        """
        type(self)._yaml_path = Path(_yaml_path)
        super().__init__(**kwargs)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        """Fail at construction if ``timezone`` is neither ``local`` nor resolvable."""
        resolve_timezone(value)
        return value

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order sources so YAML sits below env/dotenv but above field defaults.

        First entry = highest priority: init kwargs > env > ``.env`` >
        ``config.yaml`` > field defaults (FR-CFG-2).
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=cls._yaml_path),
        )
