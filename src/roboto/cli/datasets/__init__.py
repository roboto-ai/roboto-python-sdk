# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto datasets`` command group, which creates, searches, shows, updates, and deletes datasets.

A dataset is a container of files in a directory structure, usually from one robot activity such as a flight. The
group's other commands upload, download, list, rename, move, and delete a dataset's files, and
``roboto datasets import-external-file`` adds a file that is already in an S3 bucket registered with Roboto, without
copying it. ``command_set`` holds the group, and ``roboto.cli.entry`` adds it to the ``roboto`` program.
"""

from .commands import command_set

__all__ = ["command_set"]
