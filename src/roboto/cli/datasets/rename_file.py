# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain.datasets import Dataset
from ..command import RobotoCommand
from ..context import CLIContext
from .shared_helpdoc import DATASET_ID_HELP


def rename_file(args, context: CLIContext, parser: argparse.ArgumentParser):
    dataset = Dataset.from_id(args.dataset_id, context.roboto_client)
    record = dataset.rename_file(args.file_id, args.new_path)
    print(record.model_dump_json(indent=2))


def rename_file_setup_parser(parser):
    parser.add_argument("-d", "--dataset-id", type=str, required=True, help=DATASET_ID_HELP)
    parser.add_argument("-f", "--file-id", type=str, required=True, help="ID of the file to rename or move.")
    parser.add_argument(
        "-p",
        "--new-path",
        type=str,
        required=True,
        help=(
            "New path for the file, relative to the dataset root. "
            "Use a path with fewer components to move the file up the directory tree, "
            "a different name at the same depth to rename in place, "
            "or a path under a different directory to move sideways. "
            "Example: 'logs/session1.bag' or 'session1.bag'."
        ),
    )


rename_file_command = RobotoCommand(
    name="rename-file",
    logic=rename_file,
    setup_parser=rename_file_setup_parser,
    command_kwargs={"help": "Rename or move a file within a dataset."},
)
