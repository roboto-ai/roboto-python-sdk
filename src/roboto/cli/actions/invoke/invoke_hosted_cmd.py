# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Hosted action invocation command."""

import argparse
import typing

from ....domain import actions
from ....env import RobotoEnvKey
from ...command import RobotoCommand
from ...common_args import (
    ActionTimeoutArg,
    add_action_reference_arg,
    add_compute_requirements_args,
    add_container_parameters_args,
    add_org_arg,
    parse_compute_requirements,
    parse_container_overrides,
)
from ...context import CLIContext
from .cli_args import (
    add_input_specification_args,
    add_parameter_args,
)
from .input_parsing import (
    parse_input_spec,
    validate_input_specification,
)


def invoke_hosted(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    """Queue an invocation of a platform-hosted action and print the new invocation's ID.

    Runs when a user invokes ``roboto actions invoke``. Returns once the platform accepts the invocation,
    not when the action finishes running. Input flags that conflict, or that name a file path without a
    dataset, abort with a usage error before anything is submitted.
    """
    validate_input_specification(args, parser)

    owner_org_id = args.action.owner if args.action.owner else args.org
    action = actions.Action.from_name(
        name=args.action.name,
        digest=args.action.digest,
        owner_org_id=owner_org_id,
        roboto_client=context.roboto_client,
    )

    compute_requirements = parse_compute_requirements(args, action.compute_requirements)
    container_parameters = parse_container_overrides(args, action.container_parameters)

    # Every invocation carries the CLI's --log-level (default ERROR) into the action container as
    # ROBOTO_LOG_LEVEL, overwriting whatever the action or --env set. parse_container_overrides returns
    # None when no container flag was given, so there may be no ContainerParameters yet to hold it.
    if container_parameters is None:
        container_parameters = actions.ContainerParameters()

    env_vars = container_parameters.env_vars or {}
    env_vars[RobotoEnvKey.LogLevel.value] = args.log_level
    container_parameters.env_vars = env_vars

    upload_destination: typing.Optional[actions.InvocationUploadDestination] = None
    if args.output_dataset_id:
        upload_destination = actions.InvocationUploadDestination.dataset(args.output_dataset_id)

    invocation_input = parse_input_spec(args)

    # --dataset is also recorded in the data source fields, which are the invocation's only record of
    # the dataset when --file-path is omitted and parse_input_spec returns None.
    data_source_id: typing.Optional[str] = None
    data_source_type: typing.Optional[actions.InvocationDataSourceType] = None
    if args.dataset_id:
        data_source_id = args.dataset_id
        data_source_type = actions.InvocationDataSourceType.Dataset

    invocation = action.invoke(
        input_data=invocation_input,
        data_source_id=data_source_id,
        data_source_type=data_source_type,
        invocation_source=actions.InvocationSource.Manual,
        parameter_values=args.params,
        compute_requirement_overrides=compute_requirements,
        container_parameter_overrides=container_parameters,
        idempotency_id=args.idempotency_id,
        timeout=args.timeout,
        upload_destination=upload_destination,
        caller_org_id=args.org,
    )

    print(f"Queued invocation of '{action.record.reference}'. Invocation ID: '{invocation.id}'")


def invoke_parser(parser: argparse.ArgumentParser) -> None:
    """Setup parser for hosted invocation command."""

    # Required action reference
    add_action_reference_arg(parser, required=True)

    # Arguments shared with local invocation
    add_input_specification_args(parser)
    add_org_arg(parser)
    add_parameter_args(parser)

    # Hosted-specific arguments
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

    parser.add_argument(
        "--output-dataset-id",
        help=(
            "Unique identifier for a dataset to which any files written to the "
            "invocation's output directory will be uploaded."
        ),
    )

    add_compute_requirements_args(parser)
    add_container_parameters_args(parser)


invoke_hosted_command = RobotoCommand(
    name="invoke",
    logic=invoke_hosted,
    setup_parser=invoke_parser,
    command_kwargs={"help": "Invoke an action on the hosted platform."},
)
