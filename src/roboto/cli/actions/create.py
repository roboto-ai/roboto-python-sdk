# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json
import pathlib
import sys
import typing

from ...domain import actions
from ...domain.actions.action_config import CPU_UNITS_PER_VCPU
from ...exceptions import RobotoConflictException
from ..command import (
    KeyValuePairsAction,
    RobotoCommand,
)
from ..common_args import (
    ActionParameterArg,
    ActionTimeoutArg,
    add_compute_requirements_args,
    add_container_parameters_args,
    add_org_arg,
    add_release_args,
)
from ..context import CLIContext
from ..terminal import print_error_and_exit
from ..validation import (
    pydantic_validation_handler,
)
from .release_flags import overlay_release_flags

LEGACY_FARGATE_COMPUTE = actions.ComputeRequirements()
"""The compute a new Fargate action gets for any dimension the command line leaves unset: 0.5 vCPU,
1024 MiB and 21 GiB, as actions created by this command always have."""

ACTION_JSON_DOCS_URL = "https://docs.roboto.ai/reference/action-json.html"


def base_release(
    args: argparse.Namespace, config: typing.Optional[actions.ActionConfig], config_dir: pathlib.Path
) -> dict[str, typing.Any]:
    """Return the release a ``create`` invocation starts from, before its flags are laid over it.

    That is the config file's release, translated from the legacy schema for a v1 file, or for a command
    line without a file, a new action's defaults: Fargate unless ``--substrate`` says otherwise, the legacy
    compute on Fargate and 1024 MiB elsewhere, and the API's default grants. Exits with an error when the
    release would run nothing, or when the Python file the config file names cannot be read.

    Args:
        args: The parsed command line of ``roboto actions create``.
        config: The ``--from-file`` config file, or ``None`` without one.
        config_dir: The directory the config file's relative paths resolve against.
    """
    if config is None:
        substrate = actions.Substrate(args.substrate) if args.substrate is not None else actions.Substrate.Fargate
        compute = LEGACY_FARGATE_COMPUTE
        shape = (
            {"vcpu": compute.vCPU / CPU_UNITS_PER_VCPU, "memory_mib": compute.memory, "storage_gib": compute.storage}
            if substrate is actions.Substrate.Fargate
            else {"memory_mib": compute.memory}
        )
        return {"substrate": substrate, "shape": shape, "executable": None}

    if config.effective_schema_version == 1:
        if args.payload is not None:
            print_error_and_exit("--payload needs a schema_version 2 action.json; a legacy one runs an image.")
        if args.image is not None:
            config = config.model_copy(update={"image_uri": args.image})
        if config.image_uri is None:
            print_error_and_exit("A release must run something: pass --image, or set image_uri in the file.")

    elif config.release is not None:
        executable = config.release.executable
        if args.image is not None or args.payload is not None:
            # The flags replace the file's executable before it is translated, so a file whose image is
            # pushed at deploy time need not name one.
            executable = actions.ActionConfigExecutable(
                image_ref=args.image, python=str(args.payload.resolve()) if args.payload is not None else None
            )
            config = config.model_copy(update={"release": config.release.model_copy(update={"executable": executable})})
        if executable.image_ref is None and executable.python is None:
            print_error_and_exit(
                "A release must run something: pass --image or --payload, or name release.executable in the file."
            )

    with pydantic_validation_handler("Action config file"):
        try:
            release = config.to_create_request(config_dir).release
        except OSError as error:
            print_error_and_exit(f"Could not read the Python file the action.json names: {error}")
    return release.model_dump()


def _discovery_changes(action_config: actions.ActionConfig, existing_action: actions.Action) -> dict[str, typing.Any]:
    """Return the ``Action.update`` keyword arguments that make the action's description, tags and metadata match.

    These fields belong to the action, not to any release, so changing them publishes nothing.
    """
    record = existing_action.record
    wanted = {
        "description": (action_config.description, record.description),
        "short_description": (action_config.short_description, record.short_description),
        "tags": (sorted(action_config.tags), sorted(record.tags)),
        "metadata": (action_config.metadata, record.metadata),
    }
    return {field: new for field, (new, existing) in wanted.items() if new != existing}


def create(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    config: typing.Optional[actions.ActionConfig] = None
    if args.action_config_file:
        with pydantic_validation_handler("Action config file"):
            config = actions.ActionConfig.from_file(args.action_config_file)

    if config is not None and config.effective_schema_version == 1:
        print(
            f"[warning] This action.json uses the legacy (v1) schema; see {ACTION_JSON_DOCS_URL} for schema_version 2. "
            "A command to migrate it is coming.",
            file=sys.stderr,
        )

    if config is not None and config.inherits is not None:
        print_error_and_exit(
            "Action inheritance is no longer supported. Remove 'inherits' from the config file and state the "
            "configuration directly."
        )

    if config is not None and config.docker_config:
        print_error_and_exit(
            [
                "Support for building and pushing Docker images as part of Action creation is forthcoming.",
                "For now, please use the `docker` CLI to build and tag your image, and use `roboto images push` "
                "to push it to Roboto's Docker registry.",
                "Finally, use either the `--image` CLI argument or the `image_uri` property in your Action config file "
                "to associate your Action with the Docker image you just pushed.",
            ]
        )

    metadata = config.metadata if config else dict()
    if args.metadata:
        metadata.update(args.metadata)

    tags = config.tags if config else list()
    if args.tag:
        tags.extend(args.tag)

    if not args.name and not config:
        print_error_and_exit(
            "Action name is required. Please specify either the `--name` CLI argument or the `name` property in your "
            "Action config file.",
        )

    discovery_params = {
        "name": args.name,
        "description": args.description,
        "short_description": args.short_description,
        "metadata": metadata,
        "tags": tags,
    }
    discovery_params = {k: v for k, v in discovery_params.items() if v is not None}
    with pydantic_validation_handler("Action configuration"):
        action_config = (
            actions.ActionConfig.model_validate(discovery_params)
            if config is None
            else config.model_copy(update=discovery_params)
        )

    config_dir = args.action_config_file.parent if args.action_config_file else pathlib.Path.cwd()
    release = overlay_release_flags(args, base_release(args, config, config_dir))
    config_version = config.effective_schema_version if config is not None else None

    try:
        action = actions.Action.create(
            name=action_config.name,
            release=release,
            description=action_config.description,
            short_description=action_config.short_description,
            metadata=action_config.metadata,
            tags=action_config.tags,
            caller_org_id=args.org,
            roboto_client=context.roboto_client,
            action_config_version=config_version,
        )

        print(f"Successfully created action '{action.name}'. Record: ")
        print(json.dumps(action.to_dict(), indent=2))
        return
    except RobotoConflictException:
        action = actions.Action.from_name(
            name=action_config.name,
            owner_org_id=args.org,
            roboto_client=context.roboto_client,
        )

    if not args.yes:
        print(f"Action '{action.name}' already exists. Do you want to publish this as a new release of it? [y/n]")
        choice = input().lower()
        if choice not in ["y", "yes"]:
            return

    discovery_changes = _discovery_changes(action_config, action)
    if discovery_changes:
        action.update(**discovery_changes, action_config_version=config_version)

    try:
        version = action.create_release(release, action_config_version=config_version)
    except RobotoConflictException as conflict:
        # The platform compares the release after pinning its image, so an unchanged tag is no change.
        print(f"Action '{action.name}' already runs this release ({conflict}).")
        return

    action = actions.Action.from_name(name=action.name, owner_org_id=action.org_id, roboto_client=context.roboto_client)
    print(f"Published version {version.version} of action '{action.name}'. Record: ")
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
        help="Name of the action, unique within its organization. Not modifiable after creation.",
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
        help="Optional short description of action, at most 140 characters. Modifiable after creation.",
    )

    parser.add_argument(
        "--image",
        required=False,
        action="store",
        dest="image",
        help=(
            "Container image the release runs. An image in Roboto's registry is pinned to the digest its tag "
            "names now, so pushing the tag again does not change what the release runs. "
            "A release needs ``--image``, ``--payload``, or both."
        ),
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
            "A parameter replaces one of the same name in the config file. "
            "Argument values must be wrapped in quotes. e.g. "
            "``--parameter 'name=my_param|required=true|description=My description of my_param'``"
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
        help=(
            "Default timeout for a run, in whole minutes; an invocation may set its own. Unset here and in the "
            "config file, each run gets the organization's default: 30 minutes on the free tier, 12 hours otherwise."
        ),
    )
    add_org_arg(parser=parser)

    add_release_args(parser)
    add_compute_requirements_args(parser)
    add_container_parameters_args(parser)

    parser.add_argument(
        "--yes",
        required=False,
        help=(
            "If an action with this name already exists, publish this as a new release of it, and update its "
            "description, tags and metadata, without prompting. Nothing is published when the action already runs "
            "this release."
        ),
        action="store_true",
    )


create_command = RobotoCommand(
    name="create",
    logic=create,
    setup_parser=create_parser,
    command_kwargs={"help": "Create an action and its first release."},
)
