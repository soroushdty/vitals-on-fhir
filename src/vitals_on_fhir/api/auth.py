# SPDX-License-Identifier: AGPL-3.0-or-later
"""Authenticator ABC and StaticTokenAuthenticator.

Authentication for all HTTP API requests and WebSocket connections is enforced
here.  The MVP implementation compares a single static bearer token using
constant-time comparison so that the secret is not leaked through timing side
channels.

SMART on FHIR is a roadmap item; do not reference or stub it here.

Allowed imports: stdlib only.
Must NOT import from ``adapters``, ``validation``, ``pipeline``, ``dashboard``,
or ``cli``.
"""

from __future__ import annotations

import abc
import hmac


class Authenticator(abc.ABC):
    """Abstract base for components that authenticate API requests.

    Implementations receive raw credentials (typically a bearer token string)
    and return a boolean indicating whether the credentials are valid.
    """

    @abc.abstractmethod
    def authenticate(self, credentials: str) -> bool:
        """Validate the supplied credentials.

        Args:
            credentials: The bearer token string extracted from the request.

        Returns:
            ``True`` if the credentials are valid; ``False`` otherwise.
        """
        ...


class StaticTokenAuthenticator(Authenticator):
    """Authenticator that accepts a single static bearer token.

    The comparison is performed with :func:`hmac.compare_digest` to prevent
    timing-based token leakage.  ``VOF_API_TOKEN`` must never appear in logs,
    exception messages, or error response bodies.

    Args:
        token: The expected bearer token value (``VOF_API_TOKEN``).
    """

    def __init__(self, token: str) -> None:
        self._token = token

    def authenticate(self, credentials: str) -> bool:
        """Return ``True`` iff *credentials* matches the configured token.

        Uses :func:`hmac.compare_digest` for a constant-time comparison so the
        configured token is not revealed through timing side channels.  The
        token is never logged, raised, or otherwise disclosed.

        Args:
            credentials: The bearer token string to check.

        Returns:
            ``True`` if *credentials* equals the configured token.
        """
        return hmac.compare_digest(credentials, self._token)
