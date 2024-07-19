# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain.datasets import Dataset
from ..command import RobotoCommand
from ..context import CLIContext
from .shared_helpdoc import DATASET_ID_HELP


def list_files(args, context: CLIContext, parser: argparse.ArgumentParser):
    dataset = Dataset.from_id(args.dataset_id, context.roboto_client)

    for f in dataset.list_files(args.include, args.exclude):
        print(f"{f.relative_path}")


def list_files_setup_parser(parser):
    parser.add_argument(
        "-d", "--dataset-id", type=str, required=True, help=DATASET_ID_HELP
    )
    parser.add_argument(
        "-i",
        "--include",
        type=str,
        nargs="*",
        help="Zero or more include filters (if path points to a directory)",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        type=str,
        nargs="*",
        help="Zero or more exclude filters (if path points to a directory)",
    )


list_files_command = RobotoCommand(
    name="list-files",
    logic=list_files,
    setup_parser=list_files_setup_parser,
    command_kwargs={"help": "Lists files for a specific dataset."},
)
