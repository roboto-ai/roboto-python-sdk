# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json
import typing

from ...domain import actions
from ...sentinels import NotSet, null
from ...updates import MetadataChangeset
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

RELEASE_ARGS = (
    "image",
    "payload",
    "substrate",
    "timeout",
    "put_parameters",
    "remove_parameters",
    "vcpu",
    "memory",
    "storage",
    "entry_point",
    "command",
    "workdir",
    "env",
    "grant",
    "egress",
    "requires_downloaded_inputs",
    "release_version",
)
"""The flags that change what the action runs, so that giving any of them publishes a release."""


def names_release_content(args: argparse.Namespace) -> bool:
    """Whether the command line changes anything a release holds."""
    return any(getattr(args, arg) not in (None, NotSet, []) for arg in RELEASE_ARGS)


def build_release(args: argparse.Namespace, latest: actions.ActionVersion) -> actions.CreateReleaseRequest:
    """Return ``latest`` with the command line's release flags laid over it.

    Exits with an error when the latest release runs Python code, which it holds only by reference, and
    ``--payload`` does not supply it again, or when ``--image`` is empty or only whitespace. A given image is
    sent without its surrounding whitespace.
    """
    if latest.executable.payload_ref is not None and args.payload is None:
        print_error_and_exit("The latest release runs Python code; pass --payload to publish a release of it.")
    if args.image is not None:
        args.image = args.image.strip()
        if not args.image:
            print_error_and_exit("image can neither be unset nor set to an empty (or whitespace-only) string")
    base = {
        **latest.model_dump(
            include={
                "substrate",
                "shape",
                "timeout_s_default",
                "grants",
                "parameters",
                "substrate_config",
                "requires_downloaded_inputs",
                "output",
                "egress",
                "launch_requirements",
            }
        ),
        "executable": {"image_ref": latest.executable.image_ref} if latest.executable.image_ref is not None else {},
    }
    return overlay_release_flags(args, base)


def discovery_changes(args: argparse.Namespace, action: actions.Action) -> dict[str, typing.Any]:
    """Return the ``Action.update`` keyword arguments for the command line's description, tag and metadata flags."""
    changes: dict[str, typing.Any] = dict()

    if args.description is null:
        changes["description"] = None
    elif args.description != NotSet:
        changes["description"] = args.description if args.description else None

    if args.short_description is null:
        changes["short_description"] = None
    elif args.short_description != NotSet:
        changes["short_description"] = args.short_description if args.short_description else None

    with pydantic_validation_handler("metadata updates"):
        changeset = MetadataChangeset(
            put_tags=args.put_tags,
            remove_tags=args.remove_tags,
            put_fields=args.put_metadata,
            remove_fields=args.remove_metadata,
        )
    if args.put_tags or args.remove_tags:
        changes["tags"] = list(changeset.apply_tag_updates(list(action.record.tags)))
    if args.put_metadata or args.remove_metadata:
        changes["metadata"] = changeset.apply_field_updates(dict(action.record.metadata))

    return changes


def update(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    """Update the ``--org`` organization's action with the given name, then print its record as JSON.

    Only the properties the options name change. A compute requirement or container parameter left out keeps the
    action's current value. An empty ``--description`` or ``--short-description`` clears it, as ``null`` does. Exits
    with status 1 when the options request no change.
    """
    action = actions.Action.from_name(
        name=args.action,
        owner_org_id=args.org,
        roboto_client=context.roboto_client,
    )

    changes = discovery_changes(args, action)
    if names_release_content(args):
        changes["release"] = build_release(args, action.get_version())
        changes["labels"] = args.label
    elif args.label:
        print_error_and_exit("--label moves a label to the release this command publishes; change the release too.")

    if not changes:
        print_error_and_exit("No updates specified. Nothing to do.")

    action.update(**changes)

    print(f"Successfully updated action '{action.name}'. Record: ")
    print(json.dumps(action.to_dict(), indent=2))


def update_parser(parser: argparse.ArgumentParser):
    parser.add_argument(
        "action",
        metavar="action_reference: <action_name>",
        help="Exact name of action to update.",
    )
    parser.add_argument(
        "--description",
        required=False,
        action="store",
        type=lambda s: s if s != "null" else null,
        default=NotSet,
        help="Optional description of action. Specify ``null`` to unset existing description.",
    )
    parser.add_argument(
        "--short-description",
        required=False,
        action="store",
        type=lambda s: s if s != "null" else null,
        default=NotSet,
        help="Optional short description of an action. Specify ``null`` to unset existing description.",
    )
    parser.add_argument(
        "--image",
        required=False,
        action="store",
        dest="image",
        help=(
            "Container image the new release runs. An image in Roboto's registry is pinned to the digest its tag "
            "names now. Without ``--image`` or ``--payload``, the new release runs what the latest one does."
        ),
    )
    parser.add_argument(
        "--timeout",
        required=False,
        action=ActionTimeoutArg,
        help="Default timeout for a run of the new release, in whole minutes.",
    )
    parser.add_argument(
        "--label",
        required=False,
        nargs="+",
        action="extend",
        metavar="LABEL",
        help="Point these labels, such as ``stable``, at the new release.",
    )
    parser.add_argument(
        "--put-parameter",
        dest="put_parameters",
        required=False,
        metavar=ActionParameterArg.METAVAR,
        nargs="*",
        action=ActionParameterArg,
        help=(
            "Add parameter(s) or overwrite existing parameter(s) with the same name. "
            "Argument values must be wrapped in quotes. e.g. "
            "``--put-parameter 'name=my_param|required=true|description=My description of my_param'``"
        ),
    )
    parser.add_argument(
        "--remove-parameter",
        dest="remove_parameters",
        required=False,
        metavar="PARAMETER_NAME",
        nargs="*",
        help="Remove parameter(s) with the given name(s).",
    )
    parser.add_argument(
        "--put-tags",
        help="Add each tag in this sequence if it doesn't exist",
        nargs="*",
    )

    parser.add_argument(
        "--remove-tags",
        help="Remove each tag in this sequence if it exists",
        nargs="*",
    )

    parser.add_argument(
        "--put-metadata",
        required=False,
        metavar="KEY_PATH=VALUE",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``key_path=value`` formatted pairs. "
            "An attempt is made to parse ``value`` as JSON; if this fails, ``value`` is stored as a string. "
            "If ``key_path`` already exists, existing value will be overwritten. "
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
            "Dot notation is supported for nested keys. e.g. ``--remove-metadata key1 key2.subkey3``"
        ),
    )
    add_org_arg(parser=parser)
    add_release_args(parser)
    add_compute_requirements_args(parser)
    add_container_parameters_args(parser)


update_command = RobotoCommand(
    name="update",
    logic=update,
    setup_parser=update_parser,
    command_kwargs={"help": "Publish a new release of an action, or edit its description, tags and metadata."},
)
