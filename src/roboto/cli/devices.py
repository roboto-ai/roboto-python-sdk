# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import pathlib
import sys

from ..config import (
    RobotoConfig,
    RobotoConfigFileV1,
)
from ..domain import devices
from ..exceptions import RobotoConflictException
from ..logging import default_logger
from .command import (
    RobotoCommand,
    RobotoCommandSet,
)
from .common_args import (
    add_org_arg,
    get_defaulted_org_id,
)
from .context import CLIContext

logger = default_logger()


def __add_device_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "device_id",
        type=str,
        help="The device ID of the target device.",
    )


def delete_device(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    org_id = get_defaulted_org_id(args.org)

    device = devices.Device.from_id(
        device_id=args.device_id,
        org_id=org_id,
        roboto_client=context.roboto_client,
    )

    device.delete()


def delete_device_setup_parser(parser: argparse.ArgumentParser) -> None:
    __add_device_arg(parser)
    add_org_arg(parser)


def disable_device_access(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    org_id = get_defaulted_org_id(args.org)

    device = devices.Device.from_id(
        device_id=args.device_id,
        org_id=org_id,
        roboto_client=context.roboto_client,
    )

    for token in device.tokens():
        token.disable()


def disable_device_access_setup_parser(parser: argparse.ArgumentParser) -> None:
    __add_device_arg(parser)
    add_org_arg(parser)


def enable_device_access(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    org_id = get_defaulted_org_id(args.org)

    device = devices.Device.from_id(
        device_id=args.device_id,
        org_id=org_id,
        roboto_client=context.roboto_client,
    )

    for token in device.tokens():
        token.enable()


def enable_device_access_setup_parser(parser: argparse.ArgumentParser) -> None:
    __add_device_arg(parser)
    add_org_arg(parser)


def generate_device_creds(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    config_file: pathlib.Path = args.config_file
    if config_file.is_file():
        parser.error(
            f"Specified config file {args.config_file} already exists and would be overwritten. "
            + "Please provide a different --config-file, or delete the existing one."
        )

    org_id = get_defaulted_org_id(args.org)

    device = devices.Device.from_id(
        device_id=args.device_id,
        roboto_client=context.roboto_client,
        org_id=org_id,
    )

    generate_device_creds_common_logic(device, config_file, context)


def generate_device_creds_common_logic(
    device: devices.Device,
    config_file: pathlib.Path,
    context: CLIContext,
):
    """
    Used in `generate-creds` and `register`
    """
    device_token, device_secret = device.create_token()

    profiles: dict[str, RobotoConfig] = {}

    # Name the default profile after the fully qualified device ID
    default_profile = f"{device.org_id}_{device.device_id}"
    profiles[default_profile] = RobotoConfig(
        api_key=device_secret,
        endpoint=context.roboto_client.endpoint,
    )

    config_file_content = RobotoConfigFileV1(
        version="v1", profiles=profiles, default_profile=default_profile
    )

    config_file.write_text(config_file_content.model_dump_json())

    print(
        (
            f"Saved Roboto credentials for device {device.device_id} to {config_file.resolve()}\n\n"
            "This file should be copied to '$HOME/.roboto/config.json' on the device's operating system.\n\n"
            "You can also store this file in a different location, and use the environment variable "
            "ROBOTO_CONFIG_FILE to point to its location.\n\n"
            "Any first-party Roboto software, including `roboto` and "
            "`roboto-agent`, will use this file to authenticate with Roboto."
        ),
        file=sys.stderr,
    )


def generate_device_creds_setup_parser(parser: argparse.ArgumentParser) -> None:
    __add_device_arg(parser)
    add_org_arg(parser)
    parser.add_argument(
        "-f",
        "--config-file",
        type=pathlib.Path,
        default="config.json",
        help="Where on local disk to save the config file containing the device's generated Roboto credentials. "
        + "Defaults to 'config.json' in the current directory.",
    )


def list_devices(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    org_id = get_defaulted_org_id(args.org)
    for device in devices.Device.for_org(org_id):
        print(device)


def list_devices_setup_parser(parser: argparse.ArgumentParser) -> None:
    add_org_arg(parser)


def register_device(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    config_file: pathlib.Path = args.config_file
    if config_file.is_file():
        parser.error(
            f"Specified config file {args.config_file} already exists and would be overwritten. "
            + "Please provide a different --config-file, or delete the existing one."
        )

    org_id = get_defaulted_org_id(args.org)

    try:
        device = devices.Device.create(
            device_id=args.device_id,
            caller_org_id=org_id,
            roboto_client=context.roboto_client,
        )
    except RobotoConflictException:
        device = devices.Device.from_id(
            device_id=args.device_id,
            org_id=org_id,
            roboto_client=context.roboto_client,
        )

        print(
            f"Device {device.device_id} already exists, generating new credentials for it.\n",
            file=sys.stderr,
        )

    generate_device_creds_common_logic(device, config_file, context)


def register_device_setup_parser(parser: argparse.ArgumentParser) -> None:
    __add_device_arg(parser)
    parser.add_argument(
        "-f",
        "--config-file",
        type=pathlib.Path,
        default="config.json",
        help="Where on local disk to save the config file containing the newly registered device's Roboto credentials. "
        + "Defaults to 'config.json' in the current directory.",
    )
    add_org_arg(parser)


def show_device(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    org_id = get_defaulted_org_id(args.org)

    print(
        devices.Device.from_id(
            device_id=args.device_id,
            roboto_client=context.roboto_client,
            org_id=org_id,
        )
    )


def show_device_setup_parser(parser: argparse.ArgumentParser) -> None:
    __add_device_arg(parser)
    add_org_arg(parser)


delete_command = RobotoCommand(
    name="delete",
    logic=delete_device,
    setup_parser=delete_device_setup_parser,
    command_kwargs={"help": "Deletes a device"},
)

disable_access_command = RobotoCommand(
    name="disable",
    logic=disable_device_access,
    setup_parser=disable_device_access_setup_parser,
    command_kwargs={
        "help": "Disables a device's access tokens without deleting them. "
        + "This is useful if a device is acting odd, and you want to temporarily "
        + "cut it off from uploading datasets, but you don't want to have to re-provision its Roboto access."
    },
)

enable_access_command = RobotoCommand(
    name="enable",
    logic=enable_device_access,
    setup_parser=enable_device_access_setup_parser,
    command_kwargs={
        "help": "Re-enables all of a device's access tokens. "
        + "They start enabled, so this is only needed if they've been explicitly disabled."
    },
)

generate_creds_command = RobotoCommand(
    name="generate-creds",
    logic=generate_device_creds,
    setup_parser=generate_device_creds_setup_parser,
    command_kwargs={
        "help": "Generates a new access credentials file for an existing device."
    },
)

list_command = RobotoCommand(
    name="list",
    logic=list_devices,
    setup_parser=list_devices_setup_parser,
    command_kwargs={
        "help": "Lists devices which have been registered for a given org."
    },
)

register_command = RobotoCommand(
    name="register",
    logic=register_device,
    setup_parser=register_device_setup_parser,
    command_kwargs={"help": "Registers a device with Roboto."},
)

show_command = RobotoCommand(
    name="show",
    logic=show_device,
    setup_parser=show_device_setup_parser,
    command_kwargs={"help": "Gets info about an individual device."},
)

commands = [
    enable_access_command,
    disable_access_command,
    delete_command,
    generate_creds_command,
    list_command,
    register_command,
    show_command,
]

command_set = RobotoCommandSet(
    name="devices",
    help="Manage the robots and other devices which have Roboto access within your org.",
    commands=commands,
)
