# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import os
import typing

from ...domain import orgs
from ...exceptions import (
    RobotoNoOrgProvidedException,
)

ORG_ARG_HELP = (
    "The calling organization ID. Gets set implicitly if in a single org. "
    + "The `ROBOTO_ORG_ID` environment variable can be set to control the default value."
)

DEFAULT_ORG_ID = os.getenv("ROBOTO_ORG_ID")


def add_org_arg(parser: argparse.ArgumentParser, arg_help: str = ORG_ARG_HELP):
    parser.add_argument(
        "--org", required=False, type=str, help=arg_help, default=DEFAULT_ORG_ID
    )


def get_defaulted_org_id(org_id: typing.Optional[str]) -> str:
    if org_id is not None:
        return org_id

    user_orgs = orgs.Org.for_self()
    if len(user_orgs) == 0:
        raise RobotoNoOrgProvidedException(
            "Current user is not a member of any orgs, and did not provide a --org"
        )
    elif len(user_orgs) > 1:
        raise RobotoNoOrgProvidedException(
            f"Current user is a member of {len(user_orgs)} orgs, and must specify one with --org"
        )
    else:
        return user_orgs[0].org_id
