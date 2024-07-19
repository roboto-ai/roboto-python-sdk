# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from roboto.sentinels import (
    NotSet,
    value_or_not_set,
)

from ...domain.collections import (
    Collection,
    CollectionResourceRef,
    CollectionResourceType,
)
from ..command import RobotoCommand
from ..context import CLIContext
from .shared_helpdoc import COLLECTION_ID_HELP


def update(args, context: CLIContext, parser: argparse.ArgumentParser):
    collection = Collection.from_id(
        collection_id=args.collection_id,
        roboto_client=context.roboto_client,
    )

    add_resources: list[CollectionResourceRef] = []
    if args.add_dataset_id:
        add_resources.extend(
            [
                CollectionResourceRef(
                    resource_type=CollectionResourceType.Dataset, resource_id=dataset_id
                )
                for dataset_id in args.add_dataset_id
            ]
        )

    if args.add_file_id:
        add_resources.extend(
            [
                CollectionResourceRef(
                    resource_type=CollectionResourceType.File, resource_id=file_id
                )
                for file_id in args.add_file_id
            ]
        )

    remove_resources: list[CollectionResourceRef] = []
    if args.remove_dataset_id:
        remove_resources.extend(
            [
                CollectionResourceRef(
                    resource_type=CollectionResourceType.Dataset, resource_id=dataset_id
                )
                for dataset_id in args.remove_dataset_id
            ]
        )

    if args.remove_file_id:
        remove_resources.extend(
            [
                CollectionResourceRef(
                    resource_type=CollectionResourceType.File, resource_id=file_id
                )
                for file_id in args.remove_file_id
            ]
        )

    collection.update(
        name=value_or_not_set(args.name),
        description=value_or_not_set(args.description),
        add_tags=value_or_not_set(args.add_tag),
        remove_tags=value_or_not_set(args.remove_tag),
        add_resources=NotSet if len(add_resources) == 0 else add_resources,
        remove_resources=NotSet if len(remove_resources) == 0 else remove_resources,
    )

    print(collection.record.model_dump_json(indent=2))


def update_setup_parser(parser):
    parser.add_argument("collection_id", type=str, help=COLLECTION_ID_HELP)
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
        "--add-dataset-id",
        nargs="*",
        help="Datasets to add to this collection.",
        action="extend",
    )
    parser.add_argument(
        "--add-file-id",
        nargs="*",
        help="Files to add to this collection.",
        action="extend",
    )
    parser.add_argument(
        "--remove-dataset-id",
        nargs="*",
        help="Datasets to remove from this collection.",
        action="extend",
    )
    parser.add_argument(
        "--remove-file-id",
        nargs="*",
        help="Files to remove from this collection.",
        action="extend",
    )
    parser.add_argument(
        "--add-tag",
        type=str,
        nargs="*",
        help="Tags to add to this collection.",
        action="extend",
    )
    parser.add_argument(
        "--remove-tag",
        type=str,
        nargs="*",
        help="Tags to remove from this collection.",
        action="extend",
    )


update_command = RobotoCommand(
    name="update",
    logic=update,
    setup_parser=update_setup_parser,
    command_kwargs={
        "help": "Updates the resources and metadata of a given collection."
    },
)
