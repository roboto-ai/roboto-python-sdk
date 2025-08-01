# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json

from ...domain import datasets
from ..command import (
    KeyValuePairsAction,
    RobotoCommand,
)
from ..common_args import add_org_arg
from ..context import CLIContext


def create(args, context: CLIContext, parser: argparse.ArgumentParser):
    dataset = datasets.Dataset.create(
        description=args.description,
        metadata=args.metadata,
        name=args.name,
        tags=args.tag,
        roboto_client=context.roboto_client,
        caller_org_id=args.org,
    )

    print(json.dumps(dataset.to_dict(), indent=2))


def create_setup_parser(parser):
    parser.add_argument(
        "-m",
        "--metadata",
        metavar="KEY=VALUE",
        nargs="*",
        action=KeyValuePairsAction,
        help="Zero or more ``<key>=<value>`` pairs to add to this dataset's metadata. "
        + "Metadata can be modified after creation.",
    )
    parser.add_argument(
        "-t",
        "--tag",
        type=str,
        nargs="*",
        help="One or more tags to add to this dataset. Tags can be modified after creation.",
        action="extend",
    )
    parser.add_argument(
        "-d",
        "--description",
        type=str,
        help="A human readable description of this dataset.",
    )
    parser.add_argument(
        "-n",
        "--name",
        type=str,
        help="A human readable name for this dataset.",
    )
    add_org_arg(parser=parser)


create_command = RobotoCommand(
    name="create",
    logic=create,
    setup_parser=create_setup_parser,
    command_kwargs={"help": "Create a new dataset."},
)
