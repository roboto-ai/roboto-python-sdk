# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json
import typing

from ...domain.datasets import Dataset
from ...query import (
    Comparator,
    Condition,
    ConditionGroup,
    ConditionOperator,
    QuerySpecification,
    SortDirection,
)
from ..command import (
    KeyValuePairsAction,
    RobotoCommand,
)
from ..common_args import add_org_arg
from ..context import CLIContext


def search(args, context: CLIContext, parser: argparse.ArgumentParser):
    conditions: list[typing.Union[Condition, ConditionGroup]] = []
    if args.metadata:
        for key, value in args.metadata.items():
            conditions.append(
                Condition(
                    field=f"metadata.{key}",
                    comparator=Comparator.Equals,
                    value=value,
                )
            )

    if args.tag:
        for tag in args.tag:
            conditions.append(
                Condition(
                    field="tags",
                    comparator=Comparator.Contains,
                    value=tag,
                )
            )

    query_args: dict[str, typing.Any] = {
        "sort_direction": SortDirection.Descending,
    }
    if conditions:
        if len(conditions) == 1:
            query_args["condition"] = conditions[0]
        else:
            query_args["condition"] = ConditionGroup(
                conditions=conditions, operator=ConditionOperator.And
            )

    query = QuerySpecification(**query_args)
    results = Dataset.query(
        spec=query,
        roboto_client=context.roboto_client,
        owner_org_id=args.org,
    )
    print(json.dumps([result.to_dict() for result in results], indent=2))


def search_setup_parser(parser):
    parser.add_argument(
        "--metadata",
        required=False,
        metavar="KEY=VALUE",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``<key>=<value>`` pairs which represent dataset metadata. "
            "`value` is parsed as JSON. E.g.: --metadata foo=bar --metadata baz.nested=200"
        ),
    )
    parser.add_argument(
        "--tag",
        required=False,
        type=str,
        nargs="*",
        help="One or more tags associated with this dataset. E.g.: ``--tag foo --tag bar``",
        action="extend",
    )
    add_org_arg(parser=parser)


search_command = RobotoCommand(
    name="search",
    logic=search,
    setup_parser=search_setup_parser,
    command_kwargs={"help": "Query dataset matching filter criteria."},
)
