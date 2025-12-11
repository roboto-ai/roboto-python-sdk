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
from ..http import (
    BearerTokenDecorator,
    RobotoClient,
    RobotoRequester,
    RobotoTool,
)
from ..version import __version__
from .actions import (
    command_set as actions_command_set,
)
from .argparse import SortingHelpFormatter
from .cache import (
    command_set as cache_command_set,
)
from .chat import command_set as chat_command_set
from .collections import (
    command_set as collections_command_set,
)
from .config import check_last_update
from .context import CLIContext
from .datasets import (
    command_set as datasets_command_set,
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
from .users import (
    command_set as users_command_set,
)

COMMAND_SETS = [
    actions_command_set,
    cache_command_set,
    chat_command_set,
    collections_command_set,
    datasets_command_set,
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
        help="Overrides the location of the Roboto config.json file. Defaults to ~/.roboto/config.json.",
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

    # https://bugs.python.org/issue29298
    subcommands = parser.add_subparsers(dest="function")

    for command_set in sorted(
        apply_roboto_cli_command_extensions(base_command_sets=COMMAND_SETS),
        key=lambda x: x.name,
    ):
        command_set.sort_commands()
        command_set.add_to_subparsers(subcommands, context)

    return parser


def entry():
    context = CLIContext()
    parser = construct_parser(context)

    # By default, as soon as we figure out we're running a sub-parser, any field encountered after that subparser
    # will be ignored. This means that `roboto --debug datasets search` will work but
    # `roboto datasets search --debug` will not. In order to work around this, we can use parser_known_args,
    # which gives us back the list of un-evaluated args, and then take a second pass at parse_args with those args.
    # This will only work if our subparsers never re-define top level parameters like --debug, --config-file, etc.
    #
    # This solution was based on a stack overflow post about this issue:
    # https://stackoverflow.com/questions/46962065/add-top-level-argparse-arguments-after-subparser-args
    args, unparsed = parser.parse_known_args()

    args = parser.parse_args(unparsed, args)

    # Set log level from --log-level or --verbose (deprecated)
    if args.verbose > 0:
        # Deprecated --verbose flag takes precedence for backward compatibility
        warnings.warn(
            "The --verbose flag is deprecated. Use --log-level instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Map verbose count to log level
        # 0 = ERROR, 1 = WARNING, 2 = INFO, 3+ = DEBUG
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
        elif "func" in args:
            __populate_context(
                context=context,
                parser=parser,
                profile_override=args.profile,
                cache_dir_override=args.cache_dir,
            )
            apply_roboto_cli_context_extensions(base_context=context)

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
):
    try:
        config = RobotoConfig.from_env(profile_override=profile_override)
    except Exception as exc:
        parser.error(str(exc))

    auth_decorator = BearerTokenDecorator(config.api_key)

    if cache_dir_override:
        config.cache_dir = cache_dir_override

    context.roboto_config = config
    context.roboto_client = RobotoClient(
        endpoint=config.endpoint,
        auth_decorator=auth_decorator,
    )
    context.http_client = context.roboto_client.http_client
    context.http_client.set_requester(RobotoRequester.for_tool(RobotoTool.Cli))

    context.extensions = {}
