# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import pathlib

from ...domain.datasets import Dataset
from ..command import RobotoCommand
from ..context import CLIContext
from .shared_helpdoc import DATASET_ID_HELP


def download_files(args, context: CLIContext, parser: argparse.ArgumentParser):
    record = Dataset.from_id(args.dataset_id, context.roboto_client)

    record.download_files(
        out_path=args.path, include_patterns=args.include, exclude_patterns=args.exclude
    )


def download_files_setup_parser(parser):
    parser.add_argument(
        "-d", "--dataset-id", type=str, required=True, help=DATASET_ID_HELP
    )
    parser.add_argument(
        "-p",
        "--path",
        type=pathlib.Path,
        required=True,
        help="The download destination for this operation.",
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


download_files_command = RobotoCommand(
    name="download-files",
    logic=download_files,
    setup_parser=download_files_setup_parser,
    command_kwargs={"help": "Downloads a file or directory from a specific dataset."},
)
