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
    """Add the flag that selects the organization a command acts in, ``--org``, to ``parser``.

    ``--org`` defaults to ``ROBOTO_ORG_ID``, then to the config file profile's ``org_id``. The profile is not known
    until the command line is parsed, so this marks the parsed arguments as taking the profile's ``org_id``, and
    ``apply_profile_org_default`` fills it in afterwards.
    """
    # An empty ROBOTO_ORG_ID names no organization, so it counts as unset.
    parser.add_argument("--org", required=False, type=str, help=arg_help, default=os.getenv(RobotoEnvKey.OrgId) or None)
    parser.set_defaults(org_defaults_to_profile=True)


def apply_profile_org_default(args: argparse.Namespace, config: RobotoConfig) -> None:
    """Fill in ``--org`` from the config file profile's ``org_id`` when the command line and environment set none.

    The CLI calls this after it loads the config, before it runs the command. Only a command whose ``--org`` option
    came from ``add_org_arg`` gets the default. An ``--org`` defined any other way is left as the command line set it,
    such as the one naming the organization that ``roboto orgs remove-user`` removes a user from.
    """
    if getattr(args, "org_defaults_to_profile", False) and args.org is None:
        args.org = config.org_id


def get_defaulted_org_id(org_id: typing.Optional[str]) -> str:
    """Return ``org_id``, or the ID of the caller's only organization when ``org_id`` is ``None``.

    Args:
        org_id: ID of the organization the command names, usually from ``--org``. ``None`` fetches the caller's
            organizations and uses the only one.

    Raises:
        RobotoNoOrgProvidedException: ``org_id`` is ``None`` and the caller belongs to no organization or to more
            than one.
    """
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
