# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import pathlib

from ...domain.datasets import Dataset
from ..command import (
    ExistingPathlibPath,
    RobotoCommand,
)
from ..context import CLIContext
from .shared_helpdoc import DATASET_ID_HELP


def upload_files(args, context: CLIContext, parser: argparse.ArgumentParser):
    path: pathlib.Path = args.path
    if args.exclude is not None and not path.is_dir():
        parser.error(
            "Exclude filters are only supported for directory uploads, not single files."
        )

    dataset = Dataset.from_id(args.dataset_id, context.roboto_client)

    if path.is_dir():
        dataset.upload_directory(
            directory_path=path,
            exclude_patterns=args.exclude,
        )
    else:
        dataset.upload_files(
            files=[path],
        )


def upload_files_setup_parser(parser):
    parser.add_argument(
        "-d", "--dataset-id", type=str, required=True, help=DATASET_ID_HELP
    )
    parser.add_argument(
        "-p",
        "--path",
        type=ExistingPathlibPath,
        required=True,
        help="The path to a file or directory to upload.",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        type=str,
        nargs="*",
        help="Zero or more exclude filters (if path points to a directory)",
    )


upload_files_command = RobotoCommand(
    name="upload-files",
    logic=upload_files,
    setup_parser=upload_files_setup_parser,
    command_kwargs={"help": "Uploads a file or directory to a specific dataset."},
)
