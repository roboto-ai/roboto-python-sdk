# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import os
import typing

from ...config import RobotoConfig
from ...domain import orgs
from ...env import RobotoEnvKey
from ...exceptions import (
    RobotoNoOrgProvidedException,
)

ORG_ARG_HELP = (
    "The calling organization ID. Gets set implicitly if in a single org. "
    + "The `ROBOTO_ORG_ID` environment variable can be set to control the default value; without it, the default is "
    + "the `org_id` of the config file profile in use, which `roboto setup` saves."
)


def add_org_arg(parser: argparse.ArgumentParser, arg_help: str = ORG_ARG_HELP) -> None:
    """Add the ``--org`` option, which defaults to ``ROBOTO_ORG_ID``, then to the config file profile's ``org_id``.

    The profile isn't known until the command line has been parsed,
    so this records on the parsed arguments that ``--org`` takes the profile's ``org_id``,
    and :py:func:`apply_profile_org_default` fills it in afterwards.
    """
    # `ROBOTO_ORG_ID=` names no organization, so it counts as unset, as it does everywhere else the variable is read.
    parser.add_argument("--org", required=False, type=str, help=arg_help, default=os.getenv(RobotoEnvKey.OrgId) or None)
    parser.set_defaults(org_defaults_to_profile=True)


def apply_profile_org_default(args: argparse.Namespace, config: RobotoConfig) -> None:
    """Fill in ``args.org`` from the config file profile's ``org_id`` when the command line and environment set none.

    Only a command whose ``--org`` option came from :py:func:`add_org_arg` gets the default.
    An ``--org`` defined any other way is left as the command line set it,
    such as the one naming the organization that ``roboto orgs remove-user`` removes a user from.

    Args:
        args: Parsed command line arguments.
        config: The Roboto config the command runs with.
    """
    if getattr(args, "org_defaults_to_profile", False) and args.org is None:
        args.org = config.org_id


def get_defaulted_org_id(org_id: typing.Optional[str]) -> str:
    if org_id is not None:
        return org_id

    user_orgs = orgs.Org.for_self()
    if len(user_orgs) == 0:
        raise RobotoNoOrgProvidedException("Current user is not a member of any orgs, and did not provide a --org")
    elif len(user_orgs) > 1:
        raise RobotoNoOrgProvidedException(
            f"Current user is a member of {len(user_orgs)} orgs, and must specify one with --org"
        )
    else:
        return user_orgs[0].org_id
