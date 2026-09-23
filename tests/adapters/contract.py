# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reusable ``DeviceAdapter`` contract suite.

Any concrete :class:`~vitals_on_fhir.adapters.base.DeviceAdapter` should satisfy
the same structural contract, regardless of how it acquires data. This module
provides :class:`DeviceAdapterContract`, a mixin test class a concrete adapter's
test module subclasses to inherit the full suite for free.

Third-party adapters can import this class from their own test suites::

    from tests.adapters.contract import DeviceAdapterContract
    from mypackage.adapters import MyStrapAdapter

    class TestMyStrapAdapter(DeviceAdapterContract):
        adapter_cls = MyStrapAdapter

        def make_adapter(self) -> MyStrapAdapter:
            return MyStrapAdapter()

The suite asserts, for a concrete adapter:

- The class is a concrete subclass of ``DeviceAdapter`` (no unimplemented
  abstract methods).
- ``supported_vitals`` is a non-empty tuple of ``VitalSign`` subclasses.
- ``device_info`` returns a ``DeviceInfo`` instance.
- ``state`` returns a ``ConnectionState`` value.
- ``vitals()`` returns an async iterator.
- The class does not import ``bleak`` at module level (AST check; skipped for
  ``hardware``-marked adapters).

The ``bleak``-import check parses the adapter's defining module with the ``ast``
module — it never imports or executes it — so the check is safe to run in the
fast, hardware-free suite.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from vitals_on_fhir.adapters.base import ConnectionState, DeviceAdapter
from vitals_on_fhir.vitals.base import DeviceInfo, VitalSign


def module_imports_bleak(module_path: Path) -> bool:
    """Return ``True`` if the Python file at ``module_path`` imports ``bleak`` at module level.

    Parses the file with :mod:`ast` and inspects only top-level ``import`` and
    ``from ... import`` statements. Imports nested inside functions, methods, or
    ``if`` blocks are not module-level and are therefore ignored — this is how
    BLE adapters are allowed to import ``bleak`` lazily inside method bodies.

    The module is never imported or executed.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    for node in tree.body:  # top level only — do not walk into function bodies
        if isinstance(node, ast.Import) and any(
            _root_package(alias.name) == "bleak" for alias in node.names
        ):
            return True
        if (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and _root_package(node.module) == "bleak"
        ):
            return True
    return False


def _root_package(dotted_name: str) -> str:
    """Return the top-level package of a possibly-dotted import name."""
    return dotted_name.split(".", 1)[0]


class DeviceAdapterContract:
    """Reusable contract suite every concrete ``DeviceAdapter`` must satisfy.

    Subclass this in a concrete adapter's test module and set ``adapter_cls`` to
    the adapter class, and implement :meth:`make_adapter` to return a ready
    instance. pytest collects the inherited ``test_*`` methods automatically.

    Set ``requires_hardware = True`` to skip the module-level ``bleak``-import
    check for adapters that legitimately import ``bleak`` (BLE adapters); the
    remaining structural checks still run.
    """

    adapter_cls: type[DeviceAdapter]
    requires_hardware: bool = False

    def make_adapter(self) -> DeviceAdapter:
        """Return a fresh, unconnected instance of ``adapter_cls`` for the suite.

        Subclasses override this to supply any constructor arguments the adapter
        needs. The default assumes a no-argument constructor.
        """
        return self.adapter_cls()

    def test_is_concrete_subclass_of_device_adapter(self) -> None:
        """The adapter is a concrete ``DeviceAdapter`` with no unimplemented abstracts."""
        assert issubclass(self.adapter_cls, DeviceAdapter)
        assert not inspect.isabstract(self.adapter_cls)
        assert getattr(self.adapter_cls, "__abstractmethods__", frozenset()) == frozenset()

    def test_supported_vitals_is_non_empty_tuple_of_vital_signs(self) -> None:
        """``supported_vitals`` is a non-empty tuple of ``VitalSign`` subclasses."""
        supported = self.adapter_cls.supported_vitals
        assert isinstance(supported, tuple)
        assert len(supported) > 0
        for vital_type in supported:
            assert isinstance(vital_type, type)
            assert issubclass(vital_type, VitalSign)

    def test_device_info_returns_device_info(self) -> None:
        """``device_info`` returns a ``DeviceInfo`` instance."""
        adapter = self.make_adapter()
        assert isinstance(adapter.device_info, DeviceInfo)

    def test_state_returns_connection_state(self) -> None:
        """``state`` returns a ``ConnectionState`` value."""
        adapter = self.make_adapter()
        assert isinstance(adapter.state, ConnectionState)

    def test_vitals_returns_async_iterator(self) -> None:
        """``vitals()`` returns an async iterator.

        The iterator is closed immediately without being consumed, so no
        connection or hardware is required.
        """
        adapter = self.make_adapter()
        iterator = adapter.vitals()
        assert isinstance(iterator, AsyncIterator)
        aclose = getattr(iterator, "aclose", None)
        if aclose is not None:
            coro = aclose()
            coro.close()  # never awaited; just release the un-started coroutine

    def test_no_module_level_bleak_import(self) -> None:
        """The adapter's defining module does not import ``bleak`` at module level.

        Skipped for hardware adapters, which import ``bleak`` lazily but are
        exempt from this static check per the testing steering.
        """
        if self.requires_hardware:
            pytest.skip("hardware adapter: bleak module-level import check skipped")
        source_file = inspect.getsourcefile(self.adapter_cls)
        assert source_file is not None
        assert not module_imports_bleak(Path(source_file))
