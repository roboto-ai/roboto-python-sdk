# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from roboto.cli.command import RobotoCommand
from roboto.cli.common_args import add_org_arg
from roboto.cli.context import CLIContext
from roboto.domain.orgs import Org
from roboto.domain.secrets import Secret


def list_logic(args, context: CLIContext, parser: argparse.ArgumentParser):
    org_id = args.org
    if org_id is None:
        orgs = list(Org.for_self(context.roboto_client))
        if len(orgs) == 0:
            parser.error("No organizations found for the current user.")
        elif len(orgs) == 1:
            org_id = orgs[0].org_id
        else:
            parser.error("Multiple organizations found for the current user. Please specify one explicitly with --org.")

    for secret in Secret.for_org(org_id, context.roboto_client):
        print(secret)


def list_setup_parser(parser):
    add_org_arg(parser)


list_command = RobotoCommand(
    name="list",
    logic=list_logic,
    setup_parser=list_setup_parser,
    command_kwargs={
        "help": "List all secrets in an organization. "
        "This does not reveal the secret values, only the secret names and metadata."
    },
)
