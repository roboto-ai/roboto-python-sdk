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


def delete_files(args, context: CLIContext, parser: argparse.ArgumentParser):
    """Delete the files of the ``--dataset-id`` dataset that ``--include`` selects and ``--exclude`` does not."""
    dataset = Dataset.from_id(args.dataset_id, context.roboto_client)

    # Without `--include`, every file in the dataset not matched by `--exclude` is deleted.
    dataset.delete_files(include_patterns=args.include, exclude_patterns=args.exclude)


def delete_files_setup_parser(parser):
    parser.add_argument("-d", "--dataset-id", type=str, required=True, help=DATASET_ID_HELP)
    parser.add_argument(
        "-i",
        "--include",
        type=str,
        nargs="*",
        help="Zero or more include filters",
    )
    parser.add_argument(
        "-x",
        "--exclude",
        type=str,
        nargs="*",
        help="Zero or more exclude filters",
    )


delete_files_command = RobotoCommand(
    name="delete-files",
    logic=delete_files,
    setup_parser=delete_files_setup_parser,
    command_kwargs={"help": "Delete files from a dataset."},
)
