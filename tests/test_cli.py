# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the composition-root helpers in :mod:`vitals_on_fhir.cli`.

These exercise the CLI precedence and ``--config`` path resolution helpers
directly (design §4, §5).  No server is started and no ``bleak`` is imported;
``cli.py`` itself is exempt from full coverage, but its path-resolution and
per-key precedence helpers are unit-tested here (spec/config-file, Task 4.1).
"""

import argparse
import os
from pathlib import Path

import pytest

from vitals_on_fhir.cli import _resolve_config_path
from vitals_on_fhir.config import DEFAULT_CONFIG_PATH, Settings


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
