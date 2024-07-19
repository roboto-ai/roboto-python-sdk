# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain.collections import (
    Collection,
    CollectionResourceRef,
    CollectionResourceType,
)
from ..command import RobotoCommand
from ..common_args import add_org_arg
from ..context import CLIContext


def create(args, context: CLIContext, parser: argparse.ArgumentParser):
    resources: list[CollectionResourceRef] = []

    if args.dataset_id is not None:
        resources.extend(
            [
                CollectionResourceRef(
                    resource_type=CollectionResourceType.Dataset, resource_id=dataset_id
                )
                for dataset_id in args.dataset_id
            ]
        )

    if args.file_id is not None:
        resources.extend(
            [
                CollectionResourceRef(
                    resource_type=CollectionResourceType.File, resource_id=file_id
                )
                for file_id in args.file_id
            ]
        )

    collection = Collection.create(
        name=args.name,
        description=args.description,
        tags=args.tag,
        resources=None if len(resources) == 0 else resources,
        caller_org_id=args.org,
        roboto_client=context.roboto_client,
    )
    print(collection.record.model_dump_json(indent=2))


def create_setup_parser(parser):
    parser.add_argument(
        "--name",
        type=str,
        help="A human-readable name for this collection. "
        + "Does not need to be unique.",
    )
    parser.add_argument(
        "--description", type=str, help="Information about what's in this collection"
    )
    parser.add_argument(
        "--dataset-id",
        nargs="*",
        help="Initial datasets to add to this collection.",
        action="extend",
    )
    parser.add_argument(
        "--file-id",
        nargs="*",
        help="Initial files to add to this collection.",
        action="extend",
    )
    parser.add_argument(
        "--tag",
        type=str,
        nargs="*",
        help="Tags that make it easier to discover this collection.",
        action="extend",
    )
    add_org_arg(parser)


create_command = RobotoCommand(
    name="create",
    logic=create,
    setup_parser=create_setup_parser,
    command_kwargs={"help": "Creates a new collection."},
)
