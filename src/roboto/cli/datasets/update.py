# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json

from ...domain.datasets import Dataset
from ...updates import MetadataChangeset
from ..command import (
    KeyValuePairsAction,
    RobotoCommand,
)
from ..context import CLIContext
from .shared_helpdoc import DATASET_ID_HELP


def update(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    metadata_changeset = MetadataChangeset(
        put_tags=args.put_tags,
        remove_tags=args.remove_tags,
        put_fields=args.put_metadata,
        remove_fields=args.remove_metadata,
    )
    if metadata_changeset.is_empty() and not args.description:
        parser.error("No dataset changes specified.")

    dataset = Dataset.from_id(args.dataset_id, context.roboto_client)
    dataset.update(metadata_changeset=metadata_changeset, description=args.description)

    print(f"Successfully updated dataset '{dataset.dataset_id}'. Record: ")
    print(json.dumps(dataset.to_dict(), indent=2))


def update_parser(parser: argparse.ArgumentParser):
    parser.add_argument(
        "-d", "--dataset-id", type=str, required=True, help=DATASET_ID_HELP
    )

    parser.add_argument(
        "--description", help="A new description to add to this dataset"
    )

    parser.add_argument(
        "--put-tags",
        help="Add each tag in this sequence if it doesn't exist",
        nargs="*",  # 0 or more
    )

    parser.add_argument(
        "--remove-tags",
        help="Remove each tag in this sequence if it exists",
        nargs="*",  # 0 or more
    )

    parser.add_argument(
        "--put-metadata",
        required=False,
        metavar="KEY_PATH=VALUE",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``<key>=<value>`` formatted pairs. "
            "An attempt is made to parse ``value`` as JSON; if this fails, ``value`` is stored as a string. "
            "If ``key`` already exists, existing value will be overwritten. "
            "Dot notation is supported for nested keys. "
            "Examples: "
            "``--put-metadata 'key1=value1' 'key2.subkey1=value2' 'key3.sublist1=[\"a\",\"b\",\"c\"]'``"  # noqa: E501
        ),
    )

    parser.add_argument(
        "--remove-metadata",
        required=False,
        metavar="KEY_PATH",
        nargs="*",
        help=(
            "Remove each key from dataset metadata if it exists. "
            "Dot notation is supported for nested keys. E.g.: ``--remove-metadata key1 key2.subkey3``"
        ),
    )


update_command = RobotoCommand(
    name="update",
    logic=update,
    setup_parser=update_parser,
    command_kwargs={"help": "Update an existing dataset."},
)
