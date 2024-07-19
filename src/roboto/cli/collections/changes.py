# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain.collections import Collection
from ..command import RobotoCommand
from ..context import CLIContext
from .shared_helpdoc import COLLECTION_ID_HELP


def show(args, context: CLIContext, parser: argparse.ArgumentParser):
    collection = Collection.from_id(
        collection_id=args.collection_id,
        roboto_client=context.roboto_client,
    )
    for change in collection.changes(
        from_version=args.from_version, to_version=args.to_version
    ):
        print(change.model_dump_json(indent=2))


def show_setup_parser(parser):
    parser.add_argument("collection_id", type=str, help=COLLECTION_ID_HELP)
    parser.add_argument(
        "--from-version",
        type=int,
        required=False,
        help="A collection version to use as the starting point in change-set listing. Defaults to initial.",
    )
    parser.add_argument(
        "--to-version",
        type=int,
        required=False,
        help="A collection version to use as the end point in change-set listing. Defaults to latest.",
    )


changes_command = RobotoCommand(
    name="changelog",
    logic=show,
    setup_parser=show_setup_parser,
    command_kwargs={
        "help": "Provides a changelog for the revisions of a given collection."
    },
)
