# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain import actions
from ..command import (
    KeyValuePairsAction,
    RobotoCommand,
)
from ..common_args import (
    ActionTimeoutArg,
    add_action_reference_arg,
    add_compute_requirements_args,
    add_container_parameters_args,
    add_org_arg,
    parse_compute_requirements,
    parse_container_overrides,
)
from ..context import CLIContext


def invoke(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    owner_org_id = args.action.owner if args.action.owner else args.org
    action = actions.Action.from_name(
        name=args.action.name,
        digest=args.action.digest,
        owner_org_id=owner_org_id,
        roboto_client=context.roboto_client,
    )

    compute_requirements = parse_compute_requirements(args, action.compute_requirements)
    container_parameters = parse_container_overrides(args, action.container_parameters)

    invocation = action.invoke(
        input_data=args.input_data,
        data_source_id=args.dataset_id,
        data_source_type=actions.InvocationDataSourceType.Dataset,
        invocation_source=actions.InvocationSource.Manual,
        parameter_values=args.parameter_value,
        compute_requirement_overrides=compute_requirements,
        container_parameter_overrides=container_parameters,
        idempotency_id=args.idempotency_id,
        timeout=args.timeout,
        caller_org_id=args.org,
    )
    print(
        f"Queued invocation of '{action.record.reference!r}'. Invocation ID: '{invocation.id}'"
    )


def invoke_parser(parser: argparse.ArgumentParser) -> None:
    add_action_reference_arg(parser)
    add_org_arg(parser)
    parser.add_argument(
        "--input-data",
        required=True,
        dest="input_data",
        type=str,
        nargs="+",
        action="extend",
        help=(
            "One or many file patterns for data to download from the data source. Examples: "
            "front camera images, ``--input-data '**/cam_front/*.jpg'``; "
            "front and rear camera images, ``--input-data '**/cam_front/*.jpg' --input-data '**/cam_rear/*.jpg'``; "
            "all data, ``--input-data '**/*'``."
        ),
    )

    parser.add_argument(
        "--timeout",
        required=False,
        action=ActionTimeoutArg,
        help="Optional timeout for an action in minutes, defaults to 30 minutes or 12 hours depending on tier.",
    )

    parser.add_argument(
        "--idempotency_id",
        dest="idempotency_id",
        type=str,
        help="Optional unique ID which ensures that an invocation is run exactly once.",
    )

    # As more InvocationDataSourceTypes are supported,
    # additional, mutually-exclusive argument groups should be added
    dataset_source_group = parser.add_argument_group(
        "Dataset",
        "Use a dataset as the data source for this invocation. This is currently the only option.",
    )
    dataset_source_group.add_argument(
        "--dataset-id",
        required=True,
        action="store",
        dest="dataset_id",
        help="Unique identifier for dataset to use as data source for this invocation.",
    )

    parser.add_argument(
        "--parameter-value",
        required=False,
        metavar="<PARAMETER_NAME>=<PARAMETER_VALUE>",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``<parameter_name>=<parameter_value>`` pairs. "
            "``parameter_value`` is parsed as JSON. "
        ),
    )

    add_compute_requirements_args(parser)
    add_container_parameters_args(parser)


invoke_command = RobotoCommand(
    name="invoke",
    logic=invoke,
    setup_parser=invoke_parser,
    command_kwargs={"help": "Invoke an action by name."},
)
