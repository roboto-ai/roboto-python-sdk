# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json
from typing import Any, Optional

from ...domain import actions
from ...query import (
    Comparator,
    Condition,
    ConditionGroup,
    ConditionOperator,
    ConditionType,
    QuerySpecification,
)
from ...sentinels import (
    NotSet,
    is_set,
    value_or_not_set,
)
from ..command import (
    JsonFileOrStrType,
    KeyValuePairsAction,
    RobotoCommand,
    RobotoCommandSet,
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

NAME_PARAM_HELP = "The unique name used to reference a trigger."
ACTION_PARAM_HELP = (
    "Partially or fully qualified reference to the action to be triggered."
)


def parse_condition(
    args, context: CLIContext, parser: argparse.ArgumentParser
) -> Optional[ConditionType]:
    if args.condition_json and (args.required_tag or args.required_metadata):
        parser.error(
            "Can only specify '--condition-json' or a combination of '--required-tag' and "
            + "'--required-metadata' expressions, providing both does not work."
        )

    if args.condition_json:
        condition_json: dict[str, Any] = args.condition_json
        if "operator" in condition_json.keys():
            return ConditionGroup.model_validate(condition_json)
        elif "comparator" in condition_json.keys():
            return Condition.model_validate(condition_json)
        else:
            parser.error(
                "Provided '--condition-json' could not be parsed as a Condition or a ConditionGroup."
            )

    if args.required_tag or args.required_metadata:
        conditions = []
        if args.required_tag:
            for tag in args.required_tag:
                conditions.append(
                    Condition(field="tags", comparator=Comparator.Contains, value=tag)
                )

        if args.required_metadata:
            for key, value in args.required_metadata.items():
                conditions.append(
                    Condition(
                        field=f"metadata.{key}",
                        comparator=Comparator.Equals,
                        value=value,
                    )
                )

        return ConditionGroup(operator=ConditionOperator.And, conditions=conditions)

    return None


def parse_overrides(
    args, context: CLIContext, parser: argparse.ArgumentParser
) -> tuple[
    Optional[actions.ComputeRequirements], Optional[actions.ContainerParameters]
]:
    if args.action is None:
        return None, None

    owner_org_id = args.action.owner if args.action.owner else args.org
    action = actions.Action.from_name(
        name=args.action.name,
        digest=args.action.digest,
        owner_org_id=owner_org_id,
        roboto_client=context.roboto_client,
    )

    compute_requirement_overrides = parse_compute_requirements(
        args, action.compute_requirements
    )

    container_overrides = parse_container_overrides(args, action.container_parameters)

    return compute_requirement_overrides, container_overrides


def create(args, context: CLIContext, parser: argparse.ArgumentParser):
    condition = parse_condition(args, context, parser)

    compute_requirement_overrides, container_overrides = parse_overrides(
        args, context, parser
    )

    trigger = actions.Trigger.create(
        name=args.name,
        action_name=args.action.name,
        action_owner_id=args.action.owner,
        action_digest=args.action.digest,
        additional_inputs=args.additional_inputs,
        compute_requirement_overrides=compute_requirement_overrides,
        container_parameter_overrides=container_overrides,
        condition=condition,
        for_each=args.for_each,
        parameter_values=args.parameter_value,
        required_inputs=args.input_data,
        timeout=args.timeout,
        caller_org_id=args.org,
        roboto_client=context.roboto_client,
    )
    print(json.dumps(trigger.to_dict(), indent=2))


def create_setup_parser(parser):
    parser.add_argument("--name", type=str, required=True, help=NAME_PARAM_HELP)
    add_action_reference_arg(
        parser,
        positional=False,
        required=True,
        arg_help=ACTION_PARAM_HELP,
    )
    parser.add_argument(
        "--required-inputs",
        required=True,
        dest="input_data",
        type=str,
        nargs="+",
        action="extend",
        help="""\
        One or many file patterns for data to download from the data source. Examples:
        front camera images, ``--required-inputs '**/cam_front/*.jpg'``;
        front and rear camera images, ``--required-inputs'**/cam_front/*.jpg' --required-inputs '**/cam_rear/*.jpg'``;
        all data, ``--required-inputs '**/*'``.
        """,
    )
    parser.add_argument(
        "--additional-inputs",
        dest="additional_inputs",
        type=str,
        nargs="+",
        action="extend",
        help="""\
        One or many file patterns for data to download from the data source which is NOT considered as part of
        trigger evaluation. Example: front camera images, ``--additional-inputs '**/cam_front/*.jpg'``.""",
    )
    parser.add_argument(
        "--parameter-value",
        required=False,
        metavar="<PARAMETER_NAME>=<PARAMETER_VALUE>",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``<parameter_name>=<parameter_value>`` pairs to pass to the invocation. "
            "``parameter_value`` is parsed as JSON."
        ),
    )
    parser.add_argument(
        "--timeout",
        required=False,
        action=ActionTimeoutArg,
        help="Optional timeout for an action in minutes, defaults to 30 minutes or 12 hours depending on tier.",
    )
    add_org_arg(parser=parser)
    add_compute_requirements_args(parser)
    add_container_parameters_args(parser)
    parser.add_argument(
        "--for-each",
        type=actions.TriggerForEachPrimitive,
        help="Primitive against which this trigger will spawn invocations.",
        default=actions.TriggerForEachPrimitive.Dataset,
        choices=[x.value for x in actions.TriggerForEachPrimitive],
    )
    parser.add_argument(
        "--condition-json",
        type=JsonFileOrStrType,
        help="Inline JSON or a reference to a JSON file "
        + "which expresses a dataset metadata and tag condition which must be met for this trigger "
        + "to run against a given dataset. If provided, 'required-tag' and 'required-metadata' cannot "
        + "be provided.",
    )
    parser.add_argument(
        "--required-tag",
        nargs="*",
        action="extend",
        help="Dataset tags which must be present for "
        + "this trigger to run against a given dataset. If provided, these are used to construct a "
        + "trigger condition, and as such they cannot be used if 'condition-json' is specified.",
    )
    parser.add_argument(
        "--required-metadata",
        nargs="*",
        action=KeyValuePairsAction,
        help="Dataset metadata "
        + "``key=value`` conditions which all must be met for this trigger to run against a given dataset. "
        + "If provided, these are used to construct a trigger condition, and as such they cannot be "
        + "used if ``condition-json`` is specified.",
    )


def update(args, context: CLIContext, parser: argparse.ArgumentParser):
    if args.enabled and args.disabled:
        parser.error("Cannot set both --enabled and --disabled!")

    if (
        args.condition_json or args.required_tag or args.required_metadata
    ) and args.clear_condition:
        parser.error(
            "Cannot specify a condition via '--required-tag', '--required-metadata', or '--condition-json', and "
            + "also clear the condition with '--clear-condition'."
        )

    condition = parse_condition(args, context, parser)

    compute_requirement_overrides, container_overrides = parse_overrides(
        args, context, parser
    )

    trigger = actions.Trigger.from_name(
        name=args.trigger_name,
        owner_org_id=args.org,
        roboto_client=context.roboto_client,
    )

    action_name = args.action.name if args.action else None
    action_owner_id = args.action.owner if args.action else None
    action_digest = args.action.digest if args.action else None
    updates: dict[str, Any] = {
        "action_name": value_or_not_set(action_name),
        "action_owner_id": value_or_not_set(action_owner_id),
        "action_digest": value_or_not_set(action_digest),
        "required_inputs": value_or_not_set(args.required_inputs),
        "condition": None if args.clear_condition else value_or_not_set(condition),
        "additional_inputs": value_or_not_set(args.additional_inputs),
        "parameter_values": value_or_not_set(args.parameter_value),
        "compute_requirement_overrides": value_or_not_set(
            compute_requirement_overrides
        ),
        "container_parameter_overrides": value_or_not_set(container_overrides),
        "for_each": value_or_not_set(args.for_each),
        "timeout": args.timeout,
    }

    if args.enabled:
        updates["enabled"] = True
    elif args.disabled:
        updates["enabled"] = False
    else:
        updates["enabled"] = NotSet

    compacted_updates: dict[str, Any] = {k: v for k, v in updates.items() if is_set(v)}
    update_trigger_request = actions.UpdateTriggerRequest.model_validate(
        compacted_updates
    )
    trigger.update(**update_trigger_request.model_dump(exclude_unset=True))
    print(json.dumps(trigger.to_dict(), indent=2))


def update_setup_parser(parser):
    parser.add_argument("trigger_name", type=str, help=NAME_PARAM_HELP)
    add_action_reference_arg(
        parser,
        positional=False,
        required=False,
        arg_help=ACTION_PARAM_HELP,
    )
    parser.add_argument(
        "--required-inputs",
        dest="required_inputs",
        type=str,
        nargs="+",
        action="extend",
        help="""\
        One or many file patterns for data to download from the data source. Examples:
        front camera images, ``--required-inputs '**/cam_front/*.jpg'``;
        front and rear camera images, ``--required-inputs '**/cam_front/*.jpg' --required-inputs '**/cam_rear/*.jpg'``;
        all data, ``--required-inputs '**/*'``.
        """,
    )
    parser.add_argument(
        "--additional-inputs",
        dest="additional_inputs",
        type=str,
        nargs="+",
        action="extend",
        help="""\
        One or many file patterns for data to download from the data source which is NOT considered as part of
        trigger evaluation. Example:
        front camera images, ``--additional-inputs '**/cam_front/*.jpg'``.""",
    )

    parser.add_argument(
        "--timeout",
        required=False,
        action=ActionTimeoutArg,
        type=lambda s: s if s != "null" else None,
        default=NotSet,
        help="Optional timeout for an action in minutes, defaults to 30 minutes or 12 hours depending on tier.",
    )
    add_org_arg(parser=parser)
    add_compute_requirements_args(parser)
    add_container_parameters_args(parser)
    parser.add_argument(
        "--condition-json",
        type=JsonFileOrStrType,
        help="Inline JSON or a reference to a JSON file "
        + "which expresses a dataset metadata and tag condition which must be met for this trigger "
        + "to run against a given dataset. If provided, 'required-tag' and 'required-metadata' cannot "
        + "be provided.",
    )
    parser.add_argument(
        "--required-tag",
        nargs="*",
        action="extend",
        help="Dataset tags which must be present for "
        + "this trigger to run against a given dataset. If provided, these are used to construct a "
        + "trigger condition, and as such they cannot be used if 'condition-json' is specified.",
    )
    parser.add_argument(
        "--required-metadata",
        nargs="*",
        action=KeyValuePairsAction,
        help="Dataset metadata "
        + "key=value conditions which all must be met for this trigger to run against a given dataset. "
        + "If provided, these are used to construct a trigger condition, and as such they cannot be "
        + "used if 'condition-json' is specified.",
    )
    parser.add_argument(
        "--for-each",
        type=actions.TriggerForEachPrimitive,
        help="Primitive against which this trigger will spawn invocations.",
        choices=[x.value for x in actions.TriggerForEachPrimitive],
    )
    parser.add_argument("--enabled", action="store_true", help="Enables this trigger")
    parser.add_argument("--disabled", action="store_true", help="Disables this trigger")
    parser.add_argument(
        "--clear-condition", action="store_true", help="Sets the condition to None"
    )
    parser.add_argument(
        "--parameter-value",
        required=False,
        metavar="<PARAMETER_NAME>=<PARAMETER_VALUE>",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``<parameter_name>=<parameter_value>`` pairs to pass to the invocation. "
            "``parameter_value`` is parsed as JSON. "
        ),
    )


def get(args, context: CLIContext, parser: argparse.ArgumentParser):
    trigger = actions.Trigger.from_name(
        name=args.trigger_name,
        owner_org_id=args.org,
        roboto_client=context.roboto_client,
    )
    print(json.dumps(trigger.to_dict(), indent=2))


def get_setup_parser(parser):
    parser.add_argument("trigger_name", type=str, help=NAME_PARAM_HELP)
    add_org_arg(parser=parser)


def search(args, context: CLIContext, parser: argparse.ArgumentParser):
    conditions: list[Condition] = []
    if args.name:
        conditions.append(
            Condition(
                field="name",
                comparator=Comparator.Equals,
                value=args.name,
            )
        )

    if args.action:
        if args.action.name:
            conditions.append(
                Condition(
                    field="action.name",
                    comparator=Comparator.Equals,
                    value=args.action.name,
                )
            )

        if args.action.digest:
            conditions.append(
                Condition(
                    field="action.digest",
                    comparator=Comparator.Equals,
                    value=args.action.digest,
                )
            )

        if args.action.owner:
            conditions.append(
                Condition(
                    field="action.owner",
                    comparator=Comparator.Equals,
                    value=args.action.owner,
                )
            )

    condition = (
        None
        if len(conditions) == 0
        else ConditionGroup(
            conditions=conditions,
            operator=ConditionOperator.And,
        )
    )

    query = QuerySpecification(condition=condition)

    results = actions.Trigger.query(
        query,
        owner_org_id=args.org,
        roboto_client=context.roboto_client,
    )
    for trigger in results:
        print(json.dumps(trigger.to_dict(), indent=2))


def search_setup_parser(parser):
    parser.add_argument(
        "--name",
        required=False,
        action="store",
        help="Query by trigger name. Must provide an exact match; patterns are not accepted.",
    )

    add_action_reference_arg(
        parser,
        positional=False,
        required=False,
        arg_help="Query by partially or fully qualified reference to the action to be triggered.",
    )

    add_org_arg(parser=parser)


def delete(args, context: CLIContext, parser: argparse.ArgumentParser):
    trigger = actions.Trigger.from_name(
        name=args.trigger_name,
        owner_org_id=args.org,
        roboto_client=context.roboto_client,
    )
    trigger.delete()
    print(f"Successfully deleted trigger '{args.trigger_name}'")


def delete_setup_parser(parser):
    parser.add_argument("trigger_name", type=str, help=NAME_PARAM_HELP)
    add_org_arg(parser=parser)


create_command = RobotoCommand(
    name="create",
    logic=create,
    setup_parser=create_setup_parser,
    command_kwargs={
        "help": "Creates a trigger to automatically invoke an action on datasets when certain criteria are met"
    },
)

get_command = RobotoCommand(
    name="get",
    logic=get,
    setup_parser=get_setup_parser,
    command_kwargs={"help": "Looks up a specific trigger by name"},
)

delete_command = RobotoCommand(
    name="delete",
    logic=delete,
    setup_parser=delete_setup_parser,
    command_kwargs={"help": "Deletes a trigger with a given name"},
)

search_command = RobotoCommand(
    name="search",
    logic=search,
    setup_parser=search_setup_parser,
    command_kwargs={
        "help": "Searches for triggers that match a given condition. Constrained to a single org."
    },
)

update_command = RobotoCommand(
    name="update",
    logic=update,
    setup_parser=update_setup_parser,
    command_kwargs={"help": "Updates one or more fields of an existing trigger."},
)

commands = [create_command, get_command, delete_command, search_command, update_command]

command_set = RobotoCommandSet(
    name="triggers",
    help="Create and edit triggers to automatically invoke actions on datasets.",
    commands=commands,
)
