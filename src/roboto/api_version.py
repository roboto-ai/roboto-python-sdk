# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from .compat import StrEnum


class RobotoApiVersion(StrEnum):
    """Enumeration of supported Roboto API versions.

    This enum defines the available API versions for the Roboto platform. Each version
    represents a specific date-based API version that may include breaking changes,
    new features, or deprecations compared to previous versions.

    API versions follow the YYYY-MM-DD format and are used to ensure backward
    compatibility while allowing the platform to evolve. Clients should specify
    the API version they were designed for to ensure consistent behavior.
    """

    v2025_01_01 = "2025-01-01"
    v2025_07_14 = "2025-07-14"

    v2026_01_02 = "2026-01-02"
    """Release date for v0.35.0 of the Roboto Python SDK"""

    v2026_02_02 = "2026-02-02"
    """Content mode introduced for query APIs."""

    v2026_02_11 = "2026-02-11"
    """path_in_schema is now a required field on AddMessagePathRequest"""

    v2026_03_13 = "2026-03-13"
    """Query endpoints are now eventually consistent when using v2026_03_13 or later.
    Clients on older API versions maintain strong consistency for backward compatibility."""

    v2026_05_20 = "2026-05-20"
    """AgentSession and AI Chat are renamed to AgentThread across the SDK and REST API:
    ``chat_id`` / ``session_id`` become ``thread_id`` on the wire, ``/v1/ai/chats`` becomes
    ``/v1/ai/threads``, and agent ``invoke`` becomes ``launch`` (``POST /v1/ai/agents/{id}/launch``;
    the previous developer-only ``…/invoke`` URL was removed outright). Clients on older API
    versions continue to receive ``session_id`` in response bodies and can keep calling the
    legacy ``/v1/ai/chats`` paths, which are soft-deprecated aliases on the same handlers."""

    @staticmethod
    def latest() -> RobotoApiVersion:
        """Get the latest available API version.

        Returns:
            The most recent API version supported by the platform.
        """
        return RobotoApiVersion.v2026_05_20

    def is_latest(self) -> bool:
        """Check if this API version is the latest available version.

        Returns:
            True if this version matches the latest API version, False otherwise.
        """
        return self == RobotoApiVersion.latest()

    def __str__(self) -> str:
        """Return the string representation of the API version.

        Returns:
            The API version string in YYYY-MM-DD format.
        """
        return self.value
