# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json
import typing

from ...domain import actions
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


def search(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    conditions: list[typing.Union[Condition, ConditionGroup]] = []
    if args.name:
        conditions.append(
            Condition(
                field="name",
                comparator=Comparator.Equals,
                value=args.name,
            )
        )

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
    accessibility = (
        actions.Accessibility.ActionHub
        if args.actionhub
        else actions.Accessibility.Organization
    )
    matching_actions = actions.Action.query(
        query,
        accessibility=accessibility,
        owner_org_id=args.org,
        roboto_client=context.roboto_client,
    )
    print(json.dumps([action.to_dict() for action in matching_actions], indent=2))


def search_parser(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--name",
        required=False,
        action="store",
        help="If querying by action name, must provide an exact match; patterns are not accepted.",
    )
    parser.add_argument(
        "--actionhub",
        required=False,
        action="store_true",
        help="Search Actions published to the Roboto Action Hub",
    )
    parser.add_argument(
        "--metadata",
        required=False,
        metavar="KEY=VALUE",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``key=value`` pairs which represent action metadata. "
            "``value`` is parsed as JSON. E.g.: ``--metadata foo=bar --metadata baz.nested=200``"
        ),
    )
    parser.add_argument(
        "--tag",
        required=False,
        type=str,
        nargs="*",
        help="One or more tags associated with this action. E.g.: ``--tag foo --tag bar``",
        action="extend",
    )
    add_org_arg(parser=parser)


search_command = RobotoCommand(
    name="search",
    logic=search,
    setup_parser=search_parser,
    command_kwargs={"help": "Search for existing actions."},
)
