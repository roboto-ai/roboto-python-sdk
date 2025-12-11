# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ..command import RobotoCommand
from ..context import CLIContext


def where(args, context: CLIContext, parser: argparse.ArgumentParser):
    cache_dir = context.roboto_config.get_cache_dir()
    print(cache_dir)


def where_setup_parser(parser):
    pass


where_command = RobotoCommand(
    name="where",
    logic=where,
    setup_parser=where_setup_parser,
    command_kwargs={"help": "Prints the path to the Roboto cache directory."},
)
