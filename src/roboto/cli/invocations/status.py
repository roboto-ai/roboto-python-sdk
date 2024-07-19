# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json
import time

from ...domain import actions
from ..command import RobotoCommand
from ..context import CLIContext


def status(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    if not args.tail:
        invocation = actions.Invocation.from_id(
            args.invocation_id,
            roboto_client=context.roboto_client,
        )
        print(
            json.dumps(
                [
                    status_record.to_presentable_dict()
                    for status_record in invocation.status_log
                ],
                indent=2,
            )
        )
        return

    printed: set[actions.InvocationStatus] = set()
    invocation = actions.Invocation.from_id(
        args.invocation_id,
        roboto_client=context.roboto_client,
    )
    try:
        while True:
            status_records_to_print = [
                status_record
                for status_record in invocation.status_log
                if status_record.status not in printed
            ]
            if status_records_to_print:
                for status_record in status_records_to_print:
                    printed.add(status_record.status)
                    print(json.dumps(status_record.to_presentable_dict(), indent=2))

            if invocation.reached_terminal_status:
                break

            time.sleep(1)
            invocation.refresh()
    except KeyboardInterrupt:
        pass  # Swallow


def status_parser(parser: argparse.ArgumentParser):
    parser.add_argument("invocation_id")
    parser.add_argument("--tail", required=False, action="store_true")


status_command = RobotoCommand(
    name="status",
    logic=status,
    setup_parser=status_parser,
    command_kwargs={"help": "Get invocation status."},
)
