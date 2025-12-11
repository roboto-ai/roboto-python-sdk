# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import shutil
import sys

from ..command import RobotoCommand
from ..context import CLIContext


def clear(args, context: CLIContext, parser: argparse.ArgumentParser):
    cache_dir = context.roboto_config.get_cache_dir()

    if not cache_dir.exists():
        print(f"Cache directory does not exist: {cache_dir}", file=sys.stderr)
        return

    if args.dry_run:
        print(f"Would clear cache directory: {cache_dir}", file=sys.stderr)
        return

    shutil.rmtree(cache_dir)
    print(f"Cleared cache directory: {cache_dir}", file=sys.stderr)


def clear_setup_parser(parser):
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print location of cache directory that would be deleted, without performing the delete.",
    )


clear_command = RobotoCommand(
    name="clear",
    logic=clear,
    setup_parser=clear_setup_parser,
    command_kwargs={"help": "Clears the local Roboto cache directory."},
)
