# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import collections.abc
import json
import pathlib
import typing

from ...domain import actions
from ...exceptions import RobotoConflictException
from ...updates import MetadataChangeset
from ..command import (
    KeyValuePairsAction,
    RobotoCommand,
)
from ..common_args import (
    ActionParameterArg,
    ActionTimeoutArg,
    add_action_reference_arg,
    add_compute_requirements_args,
    add_container_parameters_args,
    add_org_arg,
    parse_compute_requirements,
    parse_container_overrides,
)
from ..context import CLIContext
from ..terminal import print_error_and_exit
from ..validation import (
    pydantic_validation_handler,
)
from .action_config import ActionConfig


def determine_updates(
    action_config: ActionConfig, existing_action: actions.Action
) -> collections.abc.Mapping:
    """Create an updates dict matching Action::update kwargs from an ActionConfig and an existing Action."""

    updates: dict[str, typing.Any] = dict()
    if action_config.compute_requirements != existing_action.compute_requirements:
        updates["compute_requirements"] = action_config.compute_requirements

    if action_config.container_parameters != existing_action.container_parameters:
        updates["container_parameters"] = action_config.container_parameters

    if action_config.description != existing_action.record.description:
        updates["description"] = action_config.description

    if action_config.short_description != existing_action.record.short_description:
        updates["short_description"] = action_config.short_description

    if action_config.timeout != existing_action.record.timeout:
        updates["timeout"] = action_config.timeout

    metadata_changeset_builder = MetadataChangeset.Builder()
    existing_keys = existing_action.record.metadata.keys()
    new_keys = action_config.metadata.keys()

    # Remove keys that are in the existing metadata but not in the new metadata
    for key in existing_keys - new_keys:
        metadata_changeset_builder.remove_field(key)

    # Add/overwrite keys that are in the new metadata
    for key in new_keys:
        metadata_changeset_builder.put_field(key, action_config.metadata[key])

    existing_tags = set(existing_action.record.tags)
    new_tags = set(action_config.tags)

    # Remove tags that are in the existing tags but not in the new tags
    for tag in existing_tags - new_tags:
        metadata_changeset_builder.remove_tag(tag)

    # Add tags that are in the new tags
    for tag in new_tags:
        metadata_changeset_builder.put_tag(tag)

    metadata_changeset = metadata_changeset_builder.build()
    if not metadata_changeset.is_empty():
        updates["metadata_changeset"] = metadata_changeset

    parameter_changeset_builder = actions.ActionParameterChangeset.Builder()
    existing_params = {param.name for param in existing_action.record.parameters}
    new_params = {param.name for param in action_config.parameters}

    # Remove parameters that are in the existing parameters but not in the new parameters
    for param_name in existing_params - new_params:
        parameter_changeset_builder.remove_parameter(param_name)

    # Add/overwrite parameters that are in the new parameters
    for param in action_config.parameters:
        parameter_changeset_builder.put_parameter(param)

    parameter_changeset = parameter_changeset_builder.build()
    if not parameter_changeset.is_empty():
        updates["parameter_changeset"] = parameter_changeset

    if action_config.image_uri != existing_action.uri:
        updates["uri"] = action_config.image_uri

    if action_config.inherits:
        if not action_config.inherits.owner:
            action_config.inherits.owner = existing_action.record.org_id

    if action_config.inherits != existing_action.record.inherits:
        updates["inherits"] = action_config.inherits

    return updates


def create(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    config: typing.Optional[ActionConfig] = None
    if args.action_config_file:
        if not args.action_config_file.exists():
            print_error_and_exit(
                f"Action config file '{args.action_config_file}' does not exist."
            )
        with pydantic_validation_handler("Action config file"):
            config = ActionConfig.model_validate_json(
                args.action_config_file.read_text()
            )

    default_compute_reqs_from_file = config.compute_requirements if config else None
    compute_requirements = parse_compute_requirements(
        args, defaults=default_compute_reqs_from_file
    )

    default_container_parameters_from_file = (
        config.container_parameters if config else None
    )
    container_parameters = parse_container_overrides(
        args, defaults=default_container_parameters_from_file
    )

    metadata = config.metadata if config else dict()
    if args.metadata:
        metadata.update(args.metadata)

    tags = config.tags if config else list()
    if args.tag:
        tags.extend(args.tag)

    parameters = config.parameters if config else list()
    if args.parameter:
        cli_param_names = {param.name for param in args.parameter}
        # replace any existing parameters with the same name
        parameters = [
            param for param in parameters if param.name not in cli_param_names
        ]
        parameters.extend(args.parameter)

    if not args.name and not config:
        print_error_and_exit(
            "Action name is required. Please specify either the `--name` CLI argument or the `name` property in your "
            "Action config file.",
        )

    config_params = {
        "name": args.name,
        "description": args.description,
        "inherits": args.inherits_from,
        "compute_requirements": compute_requirements,
        "container_parameters": container_parameters,
        "metadata": metadata,
        "parameters": args.parameter,
        "tags": tags,
        "image_uri": args.image,
        "short_description": args.short_description,
        "timeout": args.timeout,
    }
    config_params = {k: v for k, v in config_params.items() if v is not None}

    with pydantic_validation_handler("Action configuration"):
        config_with_overrides = (
            ActionConfig.model_validate(config_params)
            if config is None
            else config.model_copy(update=config_params)
        )

    image_uri = None
    if config_with_overrides.docker_config:
        # Build docker image and push it to Roboto's Docker register
        print_error_and_exit(
            [
                "Support for building and pushing Docker images as part of Action creation is forthcoming.",
                "For now, please use the `docker` CLI to build and tag your image, and use `roboto images push` "
                "to push it to Roboto's Docker registry.",
                "Finally, use either the `--image` CLI argument or the `image_uri` property in your Action config file "
                "to associate your Action with the Docker image you just pushed.",
            ]
        )
    else:
        image_uri = config_with_overrides.image_uri

    try:
        action = actions.Action.create(
            name=config_with_overrides.name,
            parameters=config_with_overrides.parameters,
            uri=image_uri,
            inherits=config_with_overrides.inherits,
            description=config_with_overrides.description,
            compute_requirements=config_with_overrides.compute_requirements,
            container_parameters=config_with_overrides.container_parameters,
            metadata=config_with_overrides.metadata,
            tags=config_with_overrides.tags,
            short_description=config_with_overrides.short_description,
            timeout=config_with_overrides.timeout,
            caller_org_id=args.org,
            roboto_client=context.roboto_client,
        )

        print(f"Successfully created action '{action.name}'. Record: ")
        print(json.dumps(action.to_dict(), indent=2))
    except RobotoConflictException:
        action = actions.Action.from_name(
            name=config_with_overrides.name,
            owner_org_id=args.org,
            roboto_client=context.roboto_client,
        )

        if not args.yes:
            print(
                f"Action '{action.name}' already exists. Do you want to update it? [y/n]"
            )
            choice = input().lower()
            if choice not in ["y", "yes"]:
                return

        updates = determine_updates(config_with_overrides, action)

        if updates:
            action.update(**updates)
            print(f"Successfully updated action '{action.name}'. Record: ")
            print(json.dumps(action.to_dict(), indent=2))
        else:
            print(f"Action '{action.name}' is up-to-date. Record: ")
            print(json.dumps(action.to_dict(), indent=2))


def create_parser(parser: argparse.ArgumentParser):
    parser.add_argument(
        "--from-file",
        type=pathlib.Path,
        action="store",
        dest="action_config_file",
        help=(
            "Path to a file containing Action configuration. "
            "Other CLI arguments specified will override the values in the config file. "
        ),
    )
    parser.add_argument(
        "--name",
        required=False,
        action="store",
        help=(
            "Name of the action. Not modifiable after creation. "
            "An action is considered unique by its (name, docker_image_name, docker_image_tag) tuple."
        ),
    )

    parser.add_argument(
        "--description",
        required=False,
        action="store",
        help="Optional description of action. Modifiable after creation.",
    )

    parser.add_argument(
        "--short_description",
        required=False,
        action="store",
        help="Optional description of action. Modifiable after creation.",
    )

    add_action_reference_arg(
        parser=parser,
        arg_name="inherits_from",
        arg_help=(
            "Partially or fully qualified reference to action from which to inherit configuration. "
            "Inheriting from another action is mutually exclusive with specifying a container image (``--image``), "
            "entrypoint (``--entrypoint``), command (``--command``), working directory (``--workdir``), "
            "env vars (``--env``), or parameter(s) (``--parameter``). "
        ),
        positional=False,
        required=False,
    )
    parser.add_argument(
        "--image",
        required=False,
        action="store",
        dest="image",
        help="Associate a Docker image with this action. Modifiable after creation.",
    )
    parser.add_argument(
        "--parameter",
        required=False,
        metavar=ActionParameterArg.METAVAR,
        nargs="*",
        action=ActionParameterArg,
        help=(
            "Zero or more parameters (space-separated) accepted by this action. "
            "``name`` is the only required attribute. "
            "``default`` values, if provided, are JSON parsed. "
            "This argument can be specified multiple times. "
            "Parameters can be modified after creation. "
            "Argument values must be wrapped in quotes. E.g.: "
            "``--put-parameter 'name=my_param|required=true|description=My description of my_param'``"
        ),
    )
    parser.add_argument(
        "--metadata",
        required=False,
        metavar="KEY=VALUE",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``<key>=<value>`` format key/value pairs which represent action metadata. "
            "``value`` is parsed as JSON. "
            "Metadata can be modified after creation."
        ),
    )
    parser.add_argument(
        "--tag",
        required=False,
        type=str,
        nargs="*",
        help="One or more tags to annotate this action. Modifiable after creation.",
        action="extend",
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
        "--yes",
        required=False,
        help="If action with same name already exists, update the existing action without prompting for confirmation.",
        action="store_true",
    )


create_command = RobotoCommand(
    name="create",
    logic=create,
    setup_parser=create_parser,
    command_kwargs={"help": "Create a new action."},
)
