# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for :class:`vitals_on_fhir.config.Settings` environment loading.

Regression coverage for the documented setup flow (``cp .env.example .env``,
set ``VOF_API_TOKEN``): ``Settings`` must read the ``.env`` file, and real
process environment variables must take precedence over the file.
"""

import os
from pathlib import Path

import pytest

from vitals_on_fhir.config import Settings


@pytest.fixture(autouse=True)
def _clean_vof_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any ambient ``VOF_*`` variables so tests are hermetic."""
    for key in list(os.environ):
        if key.startswith("VOF_"):
            monkeypatch.delenv(key, raising=False)


def _write_env(directory: Path, contents: str) -> None:
    """Write a ``.env`` file into ``directory``."""
    (directory / ".env").write_text(contents, encoding="utf-8")


def test_settings_loads_api_token_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``.env`` file in the working directory supplies ``VOF_API_TOKEN``.

    This is the exact flow that previously crashed with a required-field
    ``ValidationError`` because ``Settings`` did not declare ``env_file``.
    """
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.api_token == "test-token-do-not-use"
    # Untouched fields fall back to their declared defaults.
    assert settings.adapter == "mock"
    assert settings.host == "127.0.0.1"


def test_env_file_populates_non_required_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-required ``VOF_*`` values in ``.env`` override the field defaults."""
    _write_env(
        tmp_path,
        "VOF_API_TOKEN=test-token-do-not-use\n"
        "VOF_ADAPTER=miband10\n"
        "VOF_PORT=9000\n",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.adapter == "miband10"
    assert settings.port == 9000


def test_process_env_takes_precedence_over_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real ``VOF_*`` environment variable wins over the ``.env`` file."""
    _write_env(tmp_path, "VOF_API_TOKEN=from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOF_API_TOKEN", "from-process-env")

    settings = Settings()  # type: ignore[call-arg]

    assert settings.api_token == "from-process-env"


def test_missing_token_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no ``.env`` and no env var, the required token is reported missing."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError):
        Settings()  # type: ignore[call-arg]


def test_bp_bounds_default_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``VOF_BP_*`` bounds fall back to their declared defaults when unset."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.bp_systolic_min == 50.0
    assert settings.bp_systolic_max == 250.0
    assert settings.bp_diastolic_min == 30.0
    assert settings.bp_diastolic_max == 150.0


def test_bp_bounds_load_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``VOF_BP_*`` values in ``.env`` override the defaults."""
    _write_env(
        tmp_path,
        "VOF_API_TOKEN=test-token-do-not-use\n"
        "VOF_BP_SYSTOLIC_MIN=80\n"
        "VOF_BP_SYSTOLIC_MAX=200\n"
        "VOF_BP_DIASTOLIC_MIN=40\n"
        "VOF_BP_DIASTOLIC_MAX=130\n",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.bp_systolic_min == 80.0
    assert settings.bp_systolic_max == 200.0
    assert settings.bp_diastolic_min == 40.0
    assert settings.bp_diastolic_max == 130.0


def test_spo2_bounds_default_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``VOF_SPO2_*`` bounds fall back to their declared defaults when unset."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.spo2_min == 70.0
    assert settings.spo2_max == 100.0


def test_spo2_bounds_load_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``VOF_SPO2_*`` values in ``.env`` override the defaults."""
    _write_env(
        tmp_path,
        "VOF_API_TOKEN=test-token-do-not-use\n"
        "VOF_SPO2_MIN=85\n"
        "VOF_SPO2_MAX=99\n",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.spo2_min == 85.0
    assert settings.spo2_max == 99.0


def test_temp_bounds_default_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``VOF_TEMP_*`` bounds fall back to their declared defaults when unset."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.temp_min == 10.0
    assert settings.temp_max == 47.0


def test_temp_bounds_load_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``VOF_TEMP_*`` values in ``.env`` override the defaults."""
    _write_env(
        tmp_path,
        "VOF_API_TOKEN=test-token-do-not-use\n"
        "VOF_TEMP_MIN=15\n"
        "VOF_TEMP_MAX=45\n",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()  # type: ignore[call-arg]

    assert settings.temp_min == 15.0
    assert settings.temp_max == 45.0


def test_unknown_vof_variable_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown ``VOF_*`` variable is rejected (``extra = "forbid"``)."""
    _write_env(
        tmp_path,
        "VOF_API_TOKEN=test-token-do-not-use\nVOF_BP_UNKNOWN=1\n",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError):
        Settings()  # type: ignore[call-arg]
