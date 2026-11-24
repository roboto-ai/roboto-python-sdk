# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import logging

LOGGER_NAME = "roboto"
"""Name of the logger the SDK writes its log messages to.

Every SDK logger is this logger or one of its children, so setting this logger's level, for example with
``logging.getLogger("roboto").setLevel(logging.DEBUG)``, sets how much the whole SDK logs.
"""


def default_logger():
    """Return the logger named ``LOGGER_NAME``."""
    return logging.getLogger(LOGGER_NAME)


def maybe_pluralize(word: str, count: int) -> str:
    """Return ``word`` unchanged when ``count`` is 1, and with ``s`` appended otherwise.

    :py:meth:`~roboto.domain.files.FileSystem.download_files` and
    :py:meth:`~roboto.domain.files.FileSystem.upload_files` label their progress bars through it, as in "Downloading 3
    files", so most code never calls it.

    Args:
        word: Singular noun to pluralize.
        count: Number of things ``word`` describes.
    """
    return word if count == 1 else f"{word}s"
