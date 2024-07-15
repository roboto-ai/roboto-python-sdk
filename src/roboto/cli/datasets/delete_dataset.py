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


def delete_dataset(args, context: CLIContext, parser: argparse.ArgumentParser):
    dataset = Dataset.from_id(args.dataset_id, context.roboto_client)
    dataset.delete()
    print(f"Deleted dataset {args.dataset_id}")


def delete_dataset_setup_parser(parser):
    parser.add_argument(
        "-d", "--dataset-id", type=str, required=True, help=DATASET_ID_HELP
    )


delete_dataset_command = RobotoCommand(
    name="delete",
    logic=delete_dataset,
    setup_parser=delete_dataset_setup_parser,
    command_kwargs={"help": "Delete dataset (and all related subresources) by id."},
)
