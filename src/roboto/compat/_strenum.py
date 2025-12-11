# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum
import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:

    class StrEnum(str, enum.Enum):
        """Compatibility StrEnum for Python < 3.11"""

        def __str__(self) -> str:
            return self.value
