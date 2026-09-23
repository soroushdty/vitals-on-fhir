# SPDX-License-Identifier: AGPL-3.0-or-later
# Ported from EviTrace (https://github.com/soroushdty/EviTrace), GPL-3.0
# Original author: Soroush Dianaty
"""AST-based enforcement of the dependency-direction rules.

Parses every ``.py`` file under ``src/vitals_on_fhir/`` and asserts that no
module imports from a package it is forbidden to depend on.  Uses only the
standard library ``ast`` module — the source files are never imported at
runtime.

Forbidden-import table (from structure steering doc):

    vitals     → must not import any other vitals_on_fhir package
    adapters   → must not import: validation, fhir, pipeline, store, api, dashboard, cli
    validation → must not import: adapters, fhir, pipeline, store, api, dashboard, cli
    fhir       → must not import: adapters, validation, pipeline, store, api, dashboard, cli
    pipeline   → must not import: store, api, dashboard, cli
    store      → must not import: adapters, validation, api, dashboard, cli
    api        → must not import: adapters, validation, pipeline, dashboard, cli
    dashboard  → must not import: adapters, validation, api, cli

``cli.py`` lives at the root of the package and is exempt (composition root).
"""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Root of the source tree to inspect.
SRC_ROOT = Path(__file__).parent.parent / "src" / "vitals_on_fhir"

#: The package prefix used in import statements.
PKG_PREFIX = "vitals_on_fhir"

#: Forbidden import table.
#: Maps a *source package name* (the directory under vitals_on_fhir/, or
#: "root" for top-level modules like config.py) to the list of
#: vitals_on_fhir sub-packages it must not import.
FORBIDDEN: dict[str, list[str]] = {
    "vitals": ["adapters", "validation", "fhir", "pipeline", "store", "api", "dashboard"],
    "adapters": ["validation", "fhir", "pipeline", "store", "api", "dashboard"],
    "validation": ["adapters", "fhir", "pipeline", "store", "api", "dashboard"],
    "fhir": ["adapters", "validation", "pipeline", "store", "api", "dashboard"],
    "pipeline": ["store", "api", "dashboard"],
    "store": ["adapters", "validation", "api", "dashboard"],
    "api": ["adapters", "validation", "pipeline", "dashboard"],
    "dashboard": ["adapters", "validation", "api"],
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _source_package(path: Path) -> str | None:
    """Return the vitals_on_fhir sub-package that *path* belongs to.

    Returns ``None`` for ``cli.py`` (exempt) and ``"root"`` for other
    top-level files like ``config.py`` and ``__init__.py``.
    """
    relative = path.relative_to(SRC_ROOT)
    parts = relative.parts  # e.g. ("adapters", "base.py") or ("cli.py",)

    # Exempt the composition root.
    if parts == ("cli.py",):
        return None

    if len(parts) == 1:
        # Top-level file such as config.py or __init__.py.
        return "root"

    # The first path component is the sub-package directory name.
    return parts[0]


def _imported_vof_packages(tree: ast.Module) -> list[str]:
    """Return all vitals_on_fhir sub-package names imported by *tree*.

    Only the first component after ``vitals_on_fhir.`` is returned, so both
    ``from vitals_on_fhir.fhir.base import X`` and
    ``import vitals_on_fhir.fhir`` yield ``"fhir"``.

    ``cli`` (imported as ``vitals_on_fhir.cli``) is included so that the
    check catches any module accidentally depending on the composition root.
    """
    packages: list[str] = []
    for node in ast.walk(tree):
        module: str | None = None
        if isinstance(node, ast.ImportFrom):
            module = node.module  # may be None for relative imports
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(PKG_PREFIX + "."):
                    sub = alias.name[len(PKG_PREFIX) + 1 :].split(".")[0]
                    packages.append(sub)
            continue

        if module and module.startswith(PKG_PREFIX + "."):
            sub = module[len(PKG_PREFIX) + 1 :].split(".")[0]
            packages.append(sub)

    return packages


def _collect_violations() -> list[tuple[str, str, str]]:
    """Walk the source tree and collect all forbidden-import violations.

    Returns a list of ``(relative_file_path, source_pkg, imported_pkg)``
    triples for every violation found.
    """
    violations: list[tuple[str, str, str]] = []
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        src_pkg = _source_package(py_file)
        if src_pkg is None:
            # cli.py — exempt
            continue

        forbidden_for_pkg = FORBIDDEN.get(src_pkg, [])
        if not forbidden_for_pkg:
            continue

        source_code = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source_code, filename=str(py_file))
        imported_pkgs = _imported_vof_packages(tree)

        rel_path = str(py_file.relative_to(SRC_ROOT.parent.parent))
        for imp in imported_pkgs:
            if imp in forbidden_for_pkg:
                violations.append((rel_path, src_pkg, imp))

    return violations


# ---------------------------------------------------------------------------
# Parametrized per-direction tests
# ---------------------------------------------------------------------------

#: Each entry is (source_pkg, list_of_forbidden_targets) for parametrize.
_DIRECTION_PARAMS: Sequence[tuple[str, list[str]]] = list(FORBIDDEN.items())


@pytest.mark.parametrize("source_pkg,forbidden_targets", _DIRECTION_PARAMS)
def test_no_forbidden_import_for_package(source_pkg: str, forbidden_targets: list[str]) -> None:
    """Assert that *source_pkg* does not import any of its forbidden targets."""
    violations: list[tuple[str, str, str]] = []
    for py_file in sorted(SRC_ROOT.rglob("*.py")):
        pkg = _source_package(py_file)
        if pkg != source_pkg:
            continue

        source_code = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source_code, filename=str(py_file))
        imported_pkgs = _imported_vof_packages(tree)

        rel_path = str(py_file.relative_to(SRC_ROOT.parent.parent))
        for imp in imported_pkgs:
            if imp in forbidden_targets:
                violations.append((rel_path, source_pkg, imp))

    assert not violations, "\n".join(
        f'"{f}" imports from forbidden package "{i}" (not allowed from "{s}")'
        for f, s, i in violations
    )


# ---------------------------------------------------------------------------
# Combined "catch-all" test
# ---------------------------------------------------------------------------


def test_no_forbidden_imports_anywhere() -> None:
    """Assert that no forbidden cross-package import exists in the entire source tree."""
    violations = _collect_violations()
    assert not violations, "\n".join(
        f'"{f}" imports from forbidden package "{i}" (not allowed from "{s}")'
        for f, s, i in violations
    )
