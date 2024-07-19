# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain.collections import (
    Collection,
    CollectionContentMode,
)
from ..command import RobotoCommand
from ..context import CLIContext
from .shared_helpdoc import (
    COLLECTION_ID_HELP,
    COLLECTION_VERSION_HELP,
    CONTENT_MODE_HELP,
)


def show(args, context: CLIContext, parser: argparse.ArgumentParser):
    content_mode = [x for x in CollectionContentMode if x.value == args.content_mode][0]

    collection = Collection.from_id(
        collection_id=args.collection_id,
        version=args.collection_version,
        roboto_client=context.roboto_client,
        content_mode=content_mode,
    )
    print(collection.record.model_dump_json(indent=2))


def show_setup_parser(parser):
    parser.add_argument("collection_id", type=str, help=COLLECTION_ID_HELP)
    parser.add_argument(
        "-v",
        "--collection-version",
        type=int,
        required=False,
        help=COLLECTION_VERSION_HELP,
    )
    parser.add_argument(
        "--content-mode",
        type=str,
        choices=[mode.value for mode in CollectionContentMode],
        help=CONTENT_MODE_HELP,
        default=CollectionContentMode.References.value,
    )


show_command = RobotoCommand(
    name="show",
    logic=show,
    setup_parser=show_setup_parser,
    command_kwargs={"help": "Show information about a specific collection."},
)
