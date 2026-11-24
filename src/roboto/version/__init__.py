# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Version of the installed Roboto SDK.

Use :py:func:`~roboto.version.roboto_version` to read it from the installed ``roboto`` package's metadata.
``roboto.version.__version__`` holds the same version, recorded when the package was built.
"""

import importlib.metadata

# The build generates autogen_version.py; source that has not been built lacks it and reports 0.0.0.
try:
    from .autogen_version import AUTOGEN_VERSION

    __version__ = AUTOGEN_VERSION
except ImportError:
    __version__ = "0.0.0"


def roboto_version() -> str:
    """Return the version of the installed ``roboto`` package, or ``"version_not_found"`` if none is installed.

    Reads the installed package's metadata, so SDK code imported from a source directory without being installed
    reports ``"version_not_found"``.
    """
    try:
        return importlib.metadata.version("roboto")
    except importlib.metadata.PackageNotFoundError:
        return "version_not_found"


__all__ = ["__version__", "roboto_version"]
