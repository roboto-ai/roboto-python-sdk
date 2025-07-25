# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

try:
    from .autogen_version import AUTOGEN_VERSION
    __version__ = AUTOGEN_VERSION
except ImportError:
    __version__ = "0.0.0"

__all__ = ["__version__"]

