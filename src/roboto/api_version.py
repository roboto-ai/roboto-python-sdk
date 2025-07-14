# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import enum


class RobotoApiVersion(str, enum.Enum):
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

    @staticmethod
    def latest() -> RobotoApiVersion:
        """Get the latest available API version.

        Returns:
            The most recent API version supported by the platform.
        """
        return RobotoApiVersion.v2025_07_14

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
