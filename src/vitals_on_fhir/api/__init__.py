# SPDX-License-Identifier: AGPL-3.0-or-later
"""Public API for the ``api`` package — HTTP routes and authentication."""

from vitals_on_fhir.api.app import create_app
from vitals_on_fhir.api.auth import Authenticator, StaticTokenAuthenticator

__all__ = [
    # ABCs
    "Authenticator",
    # Concrete defaults
    "StaticTokenAuthenticator",
    "create_app",
]
