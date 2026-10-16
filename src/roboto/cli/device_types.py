# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import typing

from ..domain import device_types
from ..sentinels import NotSet, is_set, maybe_null, null
from ..updates import MetadataChangeset
from .command import (
    KeyValuePairsAction,
    RobotoCommand,
    RobotoCommandSet,
)
from .common_args import (
    add_org_arg,
    get_defaulted_org_id,
)
from .context import CLIContext


def __add_device_type_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "device_type_id",
        type=str,
        help="The ID (dt_...) of the target device type.",
    )


def __load_device_type(args: argparse.Namespace, context: CLIContext) -> device_types.DeviceType:
    return device_types.DeviceType.from_id(
        device_type_id=args.device_type_id,
        org_id=get_defaulted_org_id(args.org),
        roboto_client=context.roboto_client,
    )


def create_device_type(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    print(
        device_types.DeviceType.create(
            name=args.name,
            description=args.description,
            metadata=args.metadata,
            tags=args.tag,
            caller_org_id=get_defaulted_org_id(args.org),
            roboto_client=context.roboto_client,
        )
    )


def create_device_type_setup_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", type=str, help="The name of the device type, unique within the org.")
    parser.add_argument("-d", "--description", type=str, help="A free-text description of the device type.")
    parser.add_argument(
        "-m",
        "--metadata",
        metavar="KEY=VALUE",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``<key>=<value>`` pairs to add to the device type's metadata. "
            "Each value is parsed as JSON when it can be, and is otherwise stored as a string."
        ),
    )
    parser.add_argument(
        "-t",
        "--tag",
        type=str,
        nargs="*",
        action="extend",
        help="One or more tags to add to the device type.",
    )
    add_org_arg(parser)


def delete_device_type(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    __load_device_type(args, context).delete()


def delete_device_type_setup_parser(parser: argparse.ArgumentParser) -> None:
    __add_device_type_arg(parser)
    add_org_arg(parser)


def list_device_types(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    for device_type in device_types.DeviceType.for_org(get_defaulted_org_id(args.org), context.roboto_client):
        print(device_type)


def list_device_types_setup_parser(parser: argparse.ArgumentParser) -> None:
    add_org_arg(parser)


def list_devices_of_device_type(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    for device in __load_device_type(args, context).devices():
        print(device)


def list_devices_of_device_type_setup_parser(parser: argparse.ArgumentParser) -> None:
    __add_device_type_arg(parser)
    add_org_arg(parser)


def show_device_type(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    print(__load_device_type(args, context))


def show_device_type_setup_parser(parser: argparse.ArgumentParser) -> None:
    __add_device_type_arg(parser)
    add_org_arg(parser)


def update_device_type(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    update_kwargs: dict[str, typing.Any] = {}
    if is_set(args.name):
        update_kwargs["name"] = args.name
    if args.description is null:
        update_kwargs["description"] = None
    elif is_set(args.description):
        update_kwargs["description"] = args.description
    metadata_changeset = MetadataChangeset(
        put_tags=args.put_tags,
        remove_tags=args.remove_tags,
        put_fields=args.put_metadata,
        remove_fields=args.remove_metadata,
    )
    if not metadata_changeset.is_empty():
        update_kwargs["metadata_changeset"] = metadata_changeset

    if not update_kwargs:
        parser.error("No device type changes specified.")

    device_type = __load_device_type(args, context)
    print(device_type.update(device_types.UpdateDeviceTypeRequest(**update_kwargs)))


def update_device_type_setup_parser(parser: argparse.ArgumentParser) -> None:
    __add_device_type_arg(parser)
    parser.add_argument(
        "--name",
        type=str,
        default=NotSet,
        help="A new name for the device type, unique within the org.",
    )
    parser.add_argument(
        "--description",
        type=maybe_null,
        default=NotSet,
        help="A new description for the device type. Specify ``null`` to clear the description.",
    )
    parser.add_argument("--put-tags", nargs="*", help="Add each listed tag the device type does not already have.")
    parser.add_argument("--remove-tags", nargs="*", help="Remove each listed tag the device type has.")
    parser.add_argument(
        "--put-metadata",
        metavar="KEY_PATH=VALUE",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``<key>=<value>`` pairs to add to the device type's metadata, overwriting existing keys. "
            "Each value is parsed as JSON when it can be, and is otherwise stored as a string. "
            "Dot notation is supported for nested keys."
        ),
    )
    parser.add_argument(
        "--remove-metadata",
        metavar="KEY_PATH",
        nargs="*",
        help="Remove each key from the device type's metadata if it exists. Dot notation is supported for nested keys.",
    )
    add_org_arg(parser)


create_command = RobotoCommand(
    name="create",
    logic=create_device_type,
    setup_parser=create_device_type_setup_parser,
    command_kwargs={"help": "Creates a device type."},
)

delete_command = RobotoCommand(
    name="delete",
    logic=delete_device_type,
    setup_parser=delete_device_type_setup_parser,
    command_kwargs={"help": "Deletes a device type and its configurations. Refused while any device has that type."},
)

devices_command = RobotoCommand(
    name="devices",
    logic=list_devices_of_device_type,
    setup_parser=list_devices_of_device_type_setup_parser,
    command_kwargs={"help": "Lists the devices of a device type."},
)

list_command = RobotoCommand(
    name="list",
    logic=list_device_types,
    setup_parser=list_device_types_setup_parser,
    command_kwargs={"help": "Lists the device types of an org."},
)

show_command = RobotoCommand(
    name="show",
    logic=show_device_type,
    setup_parser=show_device_type_setup_parser,
    command_kwargs={"help": "Gets info about an individual device type."},
)

update_command = RobotoCommand(
    name="update",
    logic=update_device_type,
    setup_parser=update_device_type_setup_parser,
    command_kwargs={"help": "Updates a device type's name, description, metadata or tags."},
)

commands = [
    create_command,
    delete_command,
    devices_command,
    list_command,
    show_command,
    update_command,
]

command_set = RobotoCommandSet(
    name="device-types",
    help=(
        "Manage device types: named kinds of device within your org, such as one robot model. "
        "Every device of a type inherits the type's configurations."
    ),
    commands=commands,
)
