# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for :class:`vitals_on_fhir.config.Settings` environment loading.

Regression coverage for the documented setup flow (``cp .env.example .env``,
optionally set ``VOF_API_TOKEN``): ``Settings`` must read the ``.env`` file, and
real process environment variables must take precedence over the file.  An
unedited copy of ``.env.example`` must give the built-in defaults (demo mode).
"""

import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from pydantic import ValidationError

from vitals_on_fhir.config import Settings, resolve_timezone

#: The repository root, where ``.env.example`` lives.
_REPO_ROOT = Path(__file__).resolve().parents[1]


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

    settings = Settings()

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

    settings = Settings()

    assert settings.adapter == "miband10"
    assert settings.port == 9000


def test_process_env_takes_precedence_over_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real ``VOF_*`` environment variable wins over the ``.env`` file."""
    _write_env(tmp_path, "VOF_API_TOKEN=from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOF_API_TOKEN", "from-process-env")

    settings = Settings()

    assert settings.api_token == "from-process-env"


def test_missing_token_is_none_and_demo_mode_defaults_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no ``.env`` and no env var, there is no token and demo mode is on.

    ``cli.py`` then runs the mock adapter without authentication, or refuses to
    start for a real device; ``Settings`` itself no longer requires the token.
    """
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.api_token is None
    assert settings.demo_mode is True


def test_empty_token_counts_as_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``VOF_API_TOKEN=`` is treated as no token, not as an empty password."""
    _write_env(tmp_path, "VOF_API_TOKEN=\n")
    monkeypatch.chdir(tmp_path)

    assert Settings().api_token is None


def test_empty_device_name_is_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``VOF_DEVICE_NAME=`` means "no filter", not "a device named ''"."""
    _write_env(tmp_path, "VOF_DEVICE_NAME=\n")
    monkeypatch.chdir(tmp_path)

    assert Settings().device_name is None


def test_demo_mode_can_be_turned_off_from_env_or_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``demo_mode`` follows the usual sources: YAML, overridden by env."""
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("demo_mode: false\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert Settings(_yaml_path=yaml_path).demo_mode is False

    monkeypatch.setenv("VOF_DEMO_MODE", "true")
    assert Settings(_yaml_path=yaml_path).demo_mode is True


def _documented_env_names(text: str) -> set[str]:
    """Return every ``VOF_*`` name in *text*, set or commented out (``# VOF_X=``)."""
    return set(re.findall(r"^#?\s*(VOF_[A-Z0-9_]+)=", text, flags=re.MULTILINE))


def test_env_example_documents_every_setting() -> None:
    """``.env.example`` lists every ``Settings`` field, so it cannot drift."""
    text = (_REPO_ROOT / ".env.example").read_text(encoding="utf-8")

    expected = {f"VOF_{name.upper()}" for name in Settings.model_fields}
    assert _documented_env_names(text) == expected


def test_copied_env_example_matches_the_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``cp .env.example .env`` gives exactly the built-in defaults: demo mode."""
    monkeypatch.chdir(tmp_path)
    defaults = Settings()
    _write_env(tmp_path, (_REPO_ROOT / ".env.example").read_text(encoding="utf-8"))

    from_example = Settings()

    assert from_example == defaults
    assert from_example.api_token is None
    assert from_example.adapter == "mock"


def test_bp_bounds_default_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``VOF_BP_*`` bounds fall back to their declared defaults when unset."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()

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

    settings = Settings()

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

    settings = Settings()

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

    settings = Settings()

    assert settings.spo2_min == 85.0
    assert settings.spo2_max == 99.0


def test_temp_bounds_default_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``VOF_TEMP_*`` bounds fall back to their declared defaults when unset."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()

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

    settings = Settings()

    assert settings.temp_min == 15.0
    assert settings.temp_max == 45.0


def test_weight_bounds_default_when_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``VOF_WEIGHT_*`` bounds fall back to their declared defaults when unset."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.weight_min == 2.0
    assert settings.weight_max == 650.0


def test_weight_bounds_load_from_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``VOF_WEIGHT_*`` values in ``.env`` override the defaults."""
    _write_env(
        tmp_path,
        "VOF_API_TOKEN=test-token-do-not-use\n"
        "VOF_WEIGHT_MIN=3\n"
        "VOF_WEIGHT_MAX=500\n",
    )
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.weight_min == 3.0
    assert settings.weight_max == 500.0


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
        Settings()


# --- config.yaml source, precedence, and timezone (spec/config-file, Task 1.1) ---


def _write_yaml(directory: Path, contents: str) -> None:
    """Write a ``config.yaml`` file into ``directory``."""
    (directory / "config.yaml").write_text(contents, encoding="utf-8")


def test_absent_config_file_is_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no ``config.yaml`` present, behaviour matches env/default-only.

    The absent file is not an error and contributes no values (FR-CFG-1).
    """
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.hr_min == 20.0
    assert settings.adapter == "mock"
    assert settings.timezone == "local"


def test_yaml_supplies_value_when_env_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``config.yaml`` value is reflected when the env var is unset (FR-CFG-2)."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    _write_yaml(tmp_path, "hr_min: 30\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.hr_min == 30.0


def test_env_beats_yaml_for_same_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An environment variable wins over a conflicting YAML value (FR-CFG-2)."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    _write_yaml(tmp_path, "hr_min: 30\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOF_HR_MIN", "40")

    settings = Settings()

    assert settings.hr_min == 40.0


def test_unknown_yaml_key_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown key in ``config.yaml`` fails at startup naming the key (FR-CFG-3)."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    _write_yaml(tmp_path, "bogus: 1\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="bogus"):
        Settings()


def test_malformed_yaml_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unparseable ``config.yaml`` fails at startup, not a silent fallback (FR-CFG-3)."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    _write_yaml(tmp_path, "hr_min: [unbalanced\n")
    monkeypatch.chdir(tmp_path)

    # Unparseable YAML surfaces as a parser error whose message names the file.
    with pytest.raises(yaml.YAMLError, match="config.yaml"):
        Settings()


def test_top_level_list_yaml_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A top-level list (not a mapping) in ``config.yaml`` is rejected (FR-CFG-3)."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    _write_yaml(tmp_path, "- one\n- two\n")
    monkeypatch.chdir(tmp_path)

    # A non-mapping document cannot be merged into the settings; startup fails
    # loudly rather than silently falling back to defaults.
    with pytest.raises(ValueError):
        Settings()


def test_timezone_default_is_local(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``timezone`` setting defaults to ``local`` (FR-CFG-4)."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    assert Settings().timezone == "local"


def test_valid_explicit_timezone_constructs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid explicit zone (``UTC``, ``America/Phoenix``) is accepted (FR-CFG-4)."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    monkeypatch.setenv("VOF_TIMEZONE", "UTC")
    assert Settings().timezone == "UTC"

    monkeypatch.setenv("VOF_TIMEZONE", "America/Phoenix")
    assert Settings().timezone == "America/Phoenix"


def test_invalid_timezone_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unresolvable ``timezone`` fails at startup naming the value (FR-CFG-4)."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOF_TIMEZONE", "Mars/Olympus")

    with pytest.raises(ValueError, match="Mars/Olympus"):
        Settings()


def test_resolve_timezone_local_returns_none() -> None:
    """``resolve_timezone("local")`` signals host-local with ``None`` (FR-CFG-4)."""
    assert resolve_timezone("local") is None


def test_resolve_timezone_named_returns_zoneinfo() -> None:
    """``resolve_timezone("UTC")`` returns a ``ZoneInfo`` (FR-CFG-4)."""
    resolved = resolve_timezone("UTC")
    assert isinstance(resolved, ZoneInfo)
    assert resolved == ZoneInfo("UTC")


# --- Mock adapter ------------------------------------------------------------


def test_mock_interval_defaults_to_one_second(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mock emits one reading per second unless configured otherwise."""
    monkeypatch.setenv("VOF_API_TOKEN", "test-token-do-not-use")

    assert Settings(_yaml_path=tmp_path / "absent.yaml").mock_interval == 1.0


def test_mock_interval_must_be_positive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero or negative interval would busy-loop the mock, so it is rejected."""
    monkeypatch.setenv("VOF_API_TOKEN", "test-token-do-not-use")

    with pytest.raises(ValidationError):
        Settings(_yaml_path=tmp_path / "absent.yaml", mock_interval=0)


def test_mock_hr_range_keys_are_gone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The rhythm is chosen on the dashboard, so the old range keys are rejected."""
    monkeypatch.setenv("VOF_API_TOKEN", "test-token-do-not-use")
    path = tmp_path / "config.yaml"
    path.write_text("mock_hr_min: 40\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        Settings(_yaml_path=path)
