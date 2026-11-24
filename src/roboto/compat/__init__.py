# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Compatibility helpers the SDK uses on Python versions before 3.11 and when an optional extra is not installed.

The SDK's own code uses them. ``StrEnum`` is ``enum.StrEnum`` on Python 3.11 and later, and on earlier versions a
``str`` enum whose ``str()`` is the member's value. ``import_optional_dependency`` imports a module that an optional
extra, such as ``roboto[analytics]``, installs; when the module is missing, it raises ``ImportError`` by default, with a
message built from ``IMPORT_ERROR_MSG_TEMPLATE`` that names the extra to install.
"""

from ._optional import (
    IMPORT_ERROR_MSG_TEMPLATE,
    import_optional_dependency,
)
from ._strenum import StrEnum

__all__ = (
    "IMPORT_ERROR_MSG_TEMPLATE",
    "import_optional_dependency",
    "StrEnum",
)
