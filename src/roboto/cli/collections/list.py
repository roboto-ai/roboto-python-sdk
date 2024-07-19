# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain.collections import Collection
from ..command import RobotoCommand
from ..common_args import add_org_arg
from ..context import CLIContext


def list(args, context: CLIContext, parser: argparse.ArgumentParser):
    for collection in Collection.list_all(
        owner_org_id=args.org,
        roboto_client=context.roboto_client,
    ):
        print(collection.record.model_dump_json(indent=2))


list_command = RobotoCommand(
    name="list",
    logic=list,
    setup_parser=add_org_arg,
    command_kwargs={"help": "Lists existing collections."},
)
