# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import warnings

from ...domain.collections import (
    Collection,
    CollectionResourceRef,
    CollectionResourceType,
)
from ..command import RobotoCommand
from ..common_args import add_org_arg
from ..context import CLIContext


def create(args, context: CLIContext, parser: argparse.ArgumentParser):
    has_datasets = bool(args.dataset_id)
    has_files = bool(args.file_id)

    # 1. Reject mixed resource types
    if has_datasets and has_files:
        parser.error("Cannot mix --dataset-id and --file-id in a single collection.")

    # 2. Infer resource_type from provided IDs
    if has_datasets:
        inferred_type: CollectionResourceType | None = CollectionResourceType.Dataset
    elif has_files:
        inferred_type = CollectionResourceType.File
    else:
        inferred_type = None

    # 3. Resolve explicit --resource-type
    if args.resource_type is not None:
        explicit_type = CollectionResourceType(args.resource_type)
        if inferred_type is not None and explicit_type != inferred_type:
            parser.error(
                f"--resource-type '{args.resource_type}' conflicts with the type inferred from "
                f"the provided IDs ('{inferred_type.value}')."
            )
        resource_type = explicit_type
    elif inferred_type is not None:
        resource_type = inferred_type
    else:
        warnings.warn(
            "No --resource-type specified and no IDs provided; defaulting to 'file'. "
            "Pass --resource-type explicitly to suppress this warning.",
            stacklevel=2,
        )
        resource_type = CollectionResourceType.File

    # 4. Build resource refs (only one type can be present at this point)
    resources: list[CollectionResourceRef] = []
    if has_datasets:
        resources.extend(
            CollectionResourceRef(resource_type=CollectionResourceType.Dataset, resource_id=d) for d in args.dataset_id
        )
    if has_files:
        resources.extend(
            CollectionResourceRef(resource_type=CollectionResourceType.File, resource_id=f) for f in args.file_id
        )

    collection = Collection.create(
        name=args.name,
        description=args.description,
        tags=args.tag,
        resource_type=resource_type,
        resources=None if len(resources) == 0 else resources,
        caller_org_id=args.org,
        roboto_client=context.roboto_client,
    )
    print(collection.record.model_dump_json(indent=2))


def create_setup_parser(parser):
    parser.add_argument(
        "--name",
        type=str,
        help="A human-readable name for this collection. " + "Does not need to be unique.",
    )
    parser.add_argument("--description", type=str, help="Information about what's in this collection")
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
        "--resource-type",
        choices=["file", "dataset"],
        help=(
            "The type of resources this collection holds. "
            "Inferred from --file-id or --dataset-id if not provided. "
            "Defaults to 'file' with a warning when neither is given."
        ),
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
    command_kwargs={"help": "Create a new collection."},
)
