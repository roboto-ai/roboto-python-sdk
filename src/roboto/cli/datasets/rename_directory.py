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


def rename_directory(args, context: CLIContext, parser: argparse.ArgumentParser):
    dataset = Dataset.from_id(args.dataset_id, context.roboto_client)
    record = dataset.rename_directory(args.old_path, args.new_path)
    print(record.model_dump_json(indent=2))


def rename_directory_setup_parser(parser):
    parser.add_argument("-d", "--dataset-id", type=str, required=True, help=DATASET_ID_HELP)
    parser.add_argument(
        "-o",
        "--old-path",
        type=str,
        required=True,
        help="Current path of the directory, relative to the dataset root. Example: 'logs/session1'.",
    )
    parser.add_argument(
        "-p",
        "--new-path",
        type=str,
        required=True,
        help=(
            "New path for the directory, relative to the dataset root. "
            "Use a path with fewer components to move the directory up the tree, "
            "a different name at the same depth to rename in place, "
            "or a path under a different parent to move sideways. "
            "Example: 'session1' to move 'logs/session1' up one level."
        ),
    )


rename_directory_command = RobotoCommand(
    name="rename-directory",
    logic=rename_directory,
    setup_parser=rename_directory_setup_parser,
    command_kwargs={"help": "Rename or move a directory within a dataset."},
)
