# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto cache`` command group, which manages the local directory where the CLI and SDK cache data they download.

``roboto cache where`` prints the directory's path, ``roboto cache size`` prints the total size of its files in bytes,
and ``roboto cache clear`` deletes it. The directory is the one ``--cache-dir`` names, otherwise ``ROBOTO_CACHE_DIR``,
otherwise the profile's ``cache_dir`` in the Roboto config file, otherwise the operating system's per-user cache
directory. ``command_set`` holds the group, and ``roboto.cli.entry`` adds it to the ``roboto`` program.
"""

from .commands import command_set

__all__ = ["command_set"]
