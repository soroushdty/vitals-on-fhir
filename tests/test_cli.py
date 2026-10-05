# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the composition-root helpers in :mod:`vitals_on_fhir.cli`.

These exercise the CLI precedence and ``--config`` path resolution helpers
directly (design §4, §5).  No server is started and no ``bleak`` is imported;
``cli.py`` itself is exempt from full coverage, but its path-resolution and
per-key precedence helpers are unit-tested here (spec/config-file, Task 4.1).
"""

import argparse
import os
import sys
from pathlib import Path

import pytest

from vitals_on_fhir import cli
from vitals_on_fhir.api import AnonymousAuthenticator, Authenticator, StaticTokenAuthenticator
from vitals_on_fhir.cli import _build_authenticator, _resolve_config_path
from vitals_on_fhir.config import DEFAULT_CONFIG_PATH, Settings

# Synthetic token — never a real credential (security-privacy.md).
_TOKEN = "test-token-do-not-use"


@pytest.fixture(autouse=True)
def _clean_vof_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove any ambient ``VOF_*`` variables so tests are hermetic."""
    for key in list(os.environ):
        if key.startswith("VOF_"):
            monkeypatch.delenv(key, raising=False)


def _write_env(directory: Path, contents: str) -> None:
    """Write a ``.env`` file into ``directory``."""
    (directory / ".env").write_text(contents, encoding="utf-8")


def _write_yaml(path: Path, contents: str) -> None:
    """Write a YAML file at ``path``."""
    path.write_text(contents, encoding="utf-8")


def _resolve_adapter_arg(settings: Settings, argv: list[str]) -> str:
    """Mirror ``main()``'s argparse override: an explicit ``--adapter`` wins.

    This is the exact precedence mechanism from ``cli.py`` — the flag default is
    sourced from the resolved ``Settings`` so an omitted flag falls through to
    env/YAML/default and an explicit flag overrides them (design §5, FR-CFG-2).
    """
    parser = argparse.ArgumentParser(prog="vitals-on-fhir")
    parser.add_argument("--adapter", default=settings.adapter)
    return str(parser.parse_args(argv).adapter)


# --- CLI beats env and YAML (design Testing Strategy 4) ---


def test_cli_adapter_beats_env_and_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit ``--adapter`` wins over a conflicting env var and YAML value."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    _write_yaml(tmp_path / "config.yaml", "adapter: spo2\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOF_ADAPTER", "bp")

    settings = Settings()

    # The resolved setting reflects env-over-yaml precedence...
    assert settings.adapter == "bp"
    # ...but the explicit CLI flag overrides everything for that key.
    assert _resolve_adapter_arg(settings, ["--adapter", "miband10"]) == "miband10"


def test_cli_adapter_omitted_falls_through_to_resolved_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no ``--adapter`` flag, the resolved setting (env > YAML) is used."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    _write_yaml(tmp_path / "config.yaml", "adapter: spo2\n")
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    # No env override: YAML supplies the adapter, and the omitted flag defers.
    assert settings.adapter == "spo2"
    assert _resolve_adapter_arg(settings, []) == "spo2"


# --- --config selects a non-default file (design Testing Strategy 4a) ---


def test_config_flag_selects_non_default_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--config PATH`` loads a YAML at a non-default path; default is not read."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    # A default config.yaml that would set hr_min to a distinct sentinel value...
    _write_yaml(tmp_path / "config.yaml", "hr_min: 99\n")
    # ...and a non-default file selected explicitly with a different value.
    custom = tmp_path / "custom.yaml"
    _write_yaml(custom, "hr_min: 42\n")
    monkeypatch.chdir(tmp_path)

    resolved = _resolve_config_path(["--config", str(custom)])
    assert resolved == custom

    settings = Settings(_yaml_path=resolved)

    # The custom file's value is used; the default config.yaml (99) is not read.
    assert settings.hr_min == 42.0


def test_config_flag_absent_uses_default_path() -> None:
    """With no ``--config``, the resolved path is the default ``config.yaml``."""
    assert _resolve_config_path([]) == DEFAULT_CONFIG_PATH


def test_absent_default_config_is_silent_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing *default* ``config.yaml`` is not an error (FR-CFG-1)."""
    _write_env(tmp_path, "VOF_API_TOKEN=test-token-do-not-use\n")
    monkeypatch.chdir(tmp_path)

    # No config.yaml on disk: resolution succeeds and Settings builds cleanly.
    resolved = _resolve_config_path([])
    settings = Settings(_yaml_path=resolved)
    assert settings.hr_min == 20.0


# --- --config missing fails loud (design Testing Strategy 4b) ---


def test_config_flag_missing_path_fails_loud(tmp_path: Path) -> None:
    """An explicit ``--config`` to a non-existent path fails, naming the path."""
    missing = tmp_path / "does-not-exist.yaml"

    with pytest.raises(FileNotFoundError, match="does-not-exist.yaml"):
        _resolve_config_path(["--config", str(missing)])


# --- Demo mode: which authenticator a missing token leads to ---


@pytest.mark.parametrize("adapter", ["mock", "mock-bp", "mock-spo2", "mock-temp", "mock-weight"])
def test_no_token_with_a_mock_adapter_runs_in_demo_mode(adapter: str) -> None:
    """With demo mode on and no token, every mock adapter runs without auth."""
    authenticator = _build_authenticator(Settings(), adapter, demo_mode=True)

    assert isinstance(authenticator, AnonymousAuthenticator)
    assert authenticator.requires_credentials is False


@pytest.mark.parametrize(
    "adapter", ["miband10", "bp", "spo2", "temp", "weight", "some_pkg.adapters.Thing"]
)
def test_no_token_with_a_real_device_is_refused(adapter: str) -> None:
    """A real device never falls back to the mock: a missing token is an error."""
    with pytest.raises(ValueError, match="requires VOF_API_TOKEN"):
        _build_authenticator(Settings(), adapter, demo_mode=True)


def test_no_token_with_demo_mode_off_is_refused() -> None:
    """``--no-demo`` makes a missing token an error, even for the mock."""
    with pytest.raises(ValueError, match="demo mode is off"):
        _build_authenticator(Settings(), "mock", demo_mode=False)


@pytest.mark.parametrize("adapter", ["mock", "miband10"])
@pytest.mark.parametrize("demo_mode", [True, False])
def test_a_configured_token_is_always_required(adapter: str, demo_mode: bool) -> None:
    """A set token turns auth on for every adapter, whatever demo mode says."""
    authenticator = _build_authenticator(
        Settings(api_token=_TOKEN), adapter, demo_mode=demo_mode
    )

    assert isinstance(authenticator, StaticTokenAuthenticator)
    assert authenticator.requires_credentials is True
    assert authenticator.authenticate(_TOKEN)
    assert not authenticator.authenticate("")


# --- main(): --demo / --no-demo and the startup error ---


def _main_authenticator(
    monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> Authenticator:
    """Run ``main()`` with *argv* and return the authenticator it would serve with.

    ``_run`` is replaced so no server or adapter starts; its arguments are
    captured instead.
    """
    captured: dict[str, Authenticator] = {}

    async def fake_run(settings: Settings, adapter_spec: str, authenticator: Authenticator) -> None:
        captured["authenticator"] = authenticator

    monkeypatch.setattr(cli, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["vitals-on-fhir", *argv])
    cli.main()
    return captured["authenticator"]


def test_main_without_a_token_starts_in_demo_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No token, no flags: the default mock adapter serves without auth."""
    monkeypatch.chdir(tmp_path)

    authenticator = _main_authenticator(monkeypatch, [])

    assert authenticator.requires_credentials is False


def test_main_no_demo_flag_overrides_the_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--no-demo`` wins over ``demo_mode: true`` and exits with a usage error."""
    _write_yaml(tmp_path / "config.yaml", "demo_mode: true\n")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        _main_authenticator(monkeypatch, ["--no-demo"])

    assert exc_info.value.code == 2
    assert "demo mode is off" in capsys.readouterr().err


def test_main_demo_flag_overrides_the_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--demo`` wins over ``VOF_DEMO_MODE=false``."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOF_DEMO_MODE", "false")

    authenticator = _main_authenticator(monkeypatch, ["--demo"])

    assert authenticator.requires_credentials is False


def test_main_real_device_without_a_token_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--adapter miband10`` with no token stops at startup, naming the fix."""
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        _main_authenticator(monkeypatch, ["--adapter", "miband10"])

    assert exc_info.value.code == 2
    assert "requires VOF_API_TOKEN" in capsys.readouterr().err
