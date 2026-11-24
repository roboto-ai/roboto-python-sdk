# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import logging
import pathlib
import sys
import typing
import warnings

from ..config import RobotoConfig
from ..version import __version__
from . import setup as setup_command
from . import upgrade as upgrade_command
from .actions import (
    command_set as actions_command_set,
)
from .argparse import SortingHelpFormatter
from .auth import command_set as auth_command_set
from .cache import (
    command_set as cache_command_set,
)
from .chat import command_set as chat_command_set
from .collections import (
    command_set as collections_command_set,
)
from .common_args import apply_profile_org_default
from .config import check_last_update
from .context import CLIContext, cli_roboto_env, make_cli_client
from .datasets import (
    command_set as datasets_command_set,
)
from .device_types import (
    command_set as device_types_command_set,
)
from .devices import (
    command_set as devices_command_set,
)
from .extension import (
    apply_roboto_cli_command_extensions,
    apply_roboto_cli_context_extensions,
)
from .images import (
    command_set as images_command_set,
)
from .invocations import (
    command_set as invocations_command_set,
)
from .orgs import command_set as orgs_command_set
from .secrets import (
    command_set as secrets_command_set,
)
from .tokens import (
    command_set as tokens_command_set,
)
from .triggers import (
    command_set as triggers_command_set,
)
from .upgrade.installation import remove_replaced_executable
from .users import (
    command_set as users_command_set,
)

COMMAND_SETS = [
    actions_command_set,
    auth_command_set,
    cache_command_set,
    chat_command_set,
    collections_command_set,
    datasets_command_set,
    device_types_command_set,
    devices_command_set,
    images_command_set,
    invocations_command_set,
    orgs_command_set,
    users_command_set,
    secrets_command_set,
    tokens_command_set,
    triggers_command_set,
]

BETA_USER_POOL_CLIENT_ID = "7p2e45lijin58tuaairtflf3m8"
PROD_USER_POOL_CLIENT_ID = "1gricmdmh0vv582qdd84phab5"


PROGRAMMATIC_ACCESS_BLURB = (
    "To resolve this, please consult the getting started page for programmatic access at "
    + "https://docs.roboto.ai/getting-started/programmatic-access.html."
)

ASCII_ART = """
    ██████╗  ██████╗ ██████╗  ██████╗ ████████╗ ██████╗
    ██╔══██╗██╔═══██╗██╔══██╗██╔═══██╗╚══██╔══╝██╔═══██╗
    ██████╔╝██║   ██║██████╔╝██║   ██║   ██║   ██║   ██║
    ██╔══██╗██║   ██║██╔══██╗██║   ██║   ██║   ██║   ██║
    ██║  ██║╚██████╔╝██████╔╝╚██████╔╝   ██║   ╚██████╔╝
    ╚═╝  ╚═╝ ╚═════╝ ╚═════╝  ╚═════╝    ╚═╝    ╚═════╝
"""


def construct_parser(
    context: typing.Optional[CLIContext] = None,
) -> argparse.ArgumentParser:
    """Build the parser of the ``roboto`` command, with every command group, including those CLI extensions add.

    Args:
        context: Context the commands run with, which ``entry`` fills in after parsing the command line. ``None``
            builds a parser for reading only, such as for listing the commands: any command except ``roboto setup``
            and ``roboto upgrade`` then raises ``ValueError`` when it runs.

    Raises:
        ValueError: A CLI extension adds a command group whose name another command group already has, or adds a
            command to a command group that does not exist.
    """
    parser = argparse.ArgumentParser(
        prog="roboto",
        description=(
            "CLI for interacting with Roboto. "
            "Each command group provides specific subcommands and dedicated help pages for detailed usage."
        ),
        formatter_class=SortingHelpFormatter,
        add_help=False,
    )

    parser.add_argument(
        "--help",
        "-h",
        action="help",
        default=argparse.SUPPRESS,
        help="Show this help message and exit.",
    )

    parser.add_argument(
        "--log-level",
        help=(
            "Set the log level for the CLI. "
            "Choices (case-insensitive): ERROR, WARNING, INFO, DEBUG. "
            "If not specified, defaults to error."
        ),
        type=str.upper,
        choices=["ERROR", "WARNING", "INFO", "DEBUG"],
        default="ERROR",
        dest="log_level",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        help=(
            "DEPRECATED: Use --log-level instead. "
            "Set increasing levels of verbosity. "
            "Only error logs are printed by default. "
            "Use -v (warn), -vv (info), -vvv (debug)."
        ),
        action="count",
        default=0,
    )

    parser.add_argument(
        "--version",
        help="Show the version of 'roboto' currently running.",
        action="store_true",
    )

    parser.add_argument(
        "--profile",
        help="Roboto profile to use; must match a section within the Roboto config.json.",
        required=False,
    )

    parser.add_argument(
        "--cache-dir",
        help=(
            "Override default location of the cache directory used by Roboto internally. "
            "Default is platform-dependent. "
            "Run `roboto cache where` to see the current cache directory."
        ),
        type=pathlib.Path,
        required=False,
    )

    parser.add_argument(
        "--config-file",
        help="Location of the Roboto config file. Defaults to ROBOTO_CONFIG_FILE, then ~/.roboto/config.json.",
        type=pathlib.Path,
        required=False,
    )

    parser.add_argument(
        "--suppress-upgrade-check",
        dest="suppress_upgrade_check",
        help="Suppresses the check for a newer 'roboto' package version.",
        action="store_true",
        required=False,
    )

    subcommands = parser.add_subparsers(dest="function")

    for command_set in sorted(
        apply_roboto_cli_command_extensions(base_command_sets=COMMAND_SETS),
        key=lambda x: x.name,
    ):
        command_set.sort_commands()
        command_set.add_to_subparsers(subcommands, context)

    # Filling in the CLI context exits with an error when it finds neither an access token nor a config file. A new
    # user runs `roboto setup` before saving either, and `roboto upgrade` must work whatever state the credentials are
    # in, so entry() calls both without it.
    for name, command in (("setup", setup_command), ("upgrade", upgrade_command)):
        command_parser = subcommands.add_parser(
            name,
            help=command.HELP,
            description=command.DESCRIPTION,
            formatter_class=SortingHelpFormatter,
        )
        command.setup_parser(command_parser)
        command_parser.set_defaults(func_without_context=command.run)

    return parser


def entry():
    # Delete the old roboto.exe that `roboto upgrade` or install.ps1 renamed aside, since Windows cannot replace or
    # delete a running executable.
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        remove_replaced_executable(pathlib.Path(sys.executable))

    context = CLIContext()
    parser = construct_parser(context)

    # Parse in two passes so that top-level options also work after the command, as in
    # `roboto datasets search --log-level DEBUG`. The first pass leaves options the command does not define in
    # unparsed, and the second parses them as top-level options into the same namespace. A command that defines an
    # option with a top-level option's name takes that option for itself.
    args, unparsed = parser.parse_known_args()

    args = parser.parse_args(unparsed, args)

    # The deprecated `--verbose` overrides `--log-level`: `-v` sets WARNING, `-vv` INFO, and `-vvv` or more DEBUG.
    if args.verbose > 0:
        warnings.warn(
            "The --verbose flag is deprecated. Use --log-level instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        log_level_map = {
            logging.ERROR: "ERROR",  # 40
            logging.WARNING: "WARNING",  # 30
            logging.INFO: "INFO",  # 20
            logging.DEBUG: "DEBUG",  # 10
        }
        log_level = max(logging.ERROR - (args.verbose * 10), logging.DEBUG)
        args.log_level = log_level_map[log_level]

    logging.basicConfig(level=args.log_level, stream=sys.stderr, format="%(message)s")

    try:
        if args.version:
            print(__version__)
        elif "func_without_context" in args:
            args.func_without_context(args)
        elif "func" in args:
            if getattr(args, "requires_config", True):
                __populate_context(
                    context=context,
                    parser=parser,
                    profile_override=args.profile,
                    cache_dir_override=args.cache_dir,
                    config_file_override=args.config_file,
                )
                apply_roboto_cli_context_extensions(base_context=context)
                apply_profile_org_default(args, context.roboto_config)

            args.func(args)
        else:
            print(ASCII_ART)
            parser.print_help()
    finally:
        if not args.suppress_upgrade_check:
            check_last_update()


def __populate_context(
    context: CLIContext,
    parser: argparse.ArgumentParser,
    profile_override: typing.Optional[str] = None,
    cache_dir_override: typing.Optional[pathlib.Path] = None,
    config_file_override: typing.Optional[pathlib.Path] = None,
):
    """Load the Roboto config and fill in ``context`` with it and a client configured from it.

    Raises:
        SystemExit: The config cannot be loaded, such as when the config file is missing or has no profile by the
            chosen name; the status is 2 and the reason is the exception's message. ``parser.error`` prints the usage
            text and the reason to stderr.
    """
    try:
        config = RobotoConfig.from_env(profile_override=profile_override, env=cli_roboto_env(config_file_override))
    except Exception as exc:
        parser.error(str(exc))

    if cache_dir_override:
        config.cache_dir = cache_dir_override

    context.roboto_config = config
    context.roboto_client = make_cli_client(config.endpoint, config.api_key, config.default_http_timeout)
    context.http_client = context.roboto_client.http_client

    context.extensions = {}
