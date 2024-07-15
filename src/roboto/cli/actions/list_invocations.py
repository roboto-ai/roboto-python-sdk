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
    ConditionType,
    QuerySpecification,
    SortDirection,
)
from ..command import RobotoCommand
from ..common_args import (
    add_action_reference_arg,
    add_org_arg,
)
from ..context import CLIContext


def invocation_serializer(obj: typing.Any) -> typing.Any:
    if isinstance(obj, actions.Invocation):
        return {
            "invocation_id": obj.id,
            "created": obj.created.isoformat(),
            "status": str(obj.current_status),
        }

    # The default behavior for json.dumps(default=) is to throw a TypeError
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def list_invocations(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    conditions = [
        Condition(
            field="provenance.action.name",
            comparator=Comparator.Equals,
            value=args.action.name,
        ),
    ]
    if args.action.digest:
        conditions.append(
            Condition(
                field="provenance.action.digest",
                comparator=Comparator.Equals,
                value=args.action.digest,
            )
        )

    if args.action.owner:
        conditions.append(
            Condition(
                field="provenance.action.org_id",
                comparator=Comparator.Equals,
                value=args.action.owner,
            )
        )

    condition: typing.Optional[ConditionType] = None
    if len(conditions) == 1:
        condition = conditions[0]
    else:
        condition = ConditionGroup(
            operator=ConditionOperator.And,
            conditions=conditions,
        )

    query = QuerySpecification(
        condition=condition,
        sort_by="created",
        sort_direction=SortDirection.Descending,
    )
    matching_invocations = list(
        actions.Invocation.query(
            query,
            owner_org_id=args.org,
            roboto_client=context.roboto_client,
        )
    )
    print(json.dumps(matching_invocations, indent=2, default=invocation_serializer))


def list_invocations_parser(parser: argparse.ArgumentParser):
    add_action_reference_arg(parser)
    add_org_arg(parser=parser)


list_invocations_command = RobotoCommand(
    name="list-invocations",
    logic=list_invocations,
    setup_parser=list_invocations_parser,
    command_kwargs={"help": "List invocations for action."},
)
