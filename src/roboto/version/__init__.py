# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import importlib.metadata

try:
    from .autogen_version import AUTOGEN_VERSION

    __version__ = AUTOGEN_VERSION
except ImportError:
    __version__ = "0.0.0"


def roboto_version() -> str:
    try:
        return importlib.metadata.version("roboto")
    except importlib.metadata.PackageNotFoundError:
        return "version_not_found"


__all__ = ["__version__", "roboto_version"]
