# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import sys

from ..command import RobotoCommand
from ..context import CLIContext


def get_directory_size(path) -> int:
    """Compute the total size, in bytes, of every file under ``path``, at any depth."""
    total = 0
    for entry in path.rglob("*"):
        if entry.is_file():
            total += entry.stat().st_size
    return total


def size(args, context: CLIContext, parser: argparse.ArgumentParser):
    """Print the total size, in bytes, of the files in the local Roboto cache directory.

    When the cache directory does not exist, prints ``0`` and reports the missing directory on standard error.
    """
    cache_dir = context.roboto_config.get_cache_dir()

    if not cache_dir.exists():
        print(f"Cache directory does not exist: {cache_dir}", file=sys.stderr)
        print(0)
        return

    total_bytes = get_directory_size(cache_dir)
    print(total_bytes)


def size_setup_parser(parser):
    pass


size_command = RobotoCommand(
    name="size",
    logic=size,
    setup_parser=size_setup_parser,
    command_kwargs={"help": "Returns the total size in bytes of the Roboto cache directory."},
)
