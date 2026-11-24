# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Building blocks of the ``roboto`` command-line program: its commands, the groups that hold them, and flag parsers.

A ``RobotoCommand`` is one command, such as ``roboto auth login``, and a ``RobotoCommandSet`` is a group of commands,
such as ``roboto auth``; ``roboto.cli`` adds each group to the ``roboto`` program. ``ExistingPathlibPath``,
``JsonFileOrStrType`` and ``NonBlankString`` are argparse ``type`` functions that check or convert one flag value, and
``KeyValuePairsAction`` collects ``KEY=VALUE`` flag values into a dictionary.
"""

from .args import (
    ExistingPathlibPath,
    JsonFileOrStrType,
    KeyValuePairsAction,
    NonBlankString,
)
from .roboto_command import (
    RobotoCommand,
    RobotoCommandSet,
)

__all__ = [
    "ExistingPathlibPath",
    "JsonFileOrStrType",
    "KeyValuePairsAction",
    "NonBlankString",
    "RobotoCommand",
    "RobotoCommandSet",
]
