# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import time
from typing import Any, Optional

from ...domain import actions
from ..command import RobotoCommand
from ..context import CLIContext


def get_logs(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    invocation = actions.Invocation.from_id(
        args.invocation_id,
        roboto_client=context.roboto_client,
    )

    process_decorator = "=" * 10
    last_log = None
    for log_record in invocation.get_logs():
        if last_log is None:
            print(f"{process_decorator} {log_record.process.value} {process_decorator}")
        else:
            if (
                last_log.partial_id is not None
                and log_record.partial_id != last_log.partial_id
            ):
                # `last_record` was the last partial message from its group--print it
                print(last_log.log)

            if last_log.process != log_record.process:
                print()  # Newline separate process output
                print(
                    f"{process_decorator} {log_record.process.value} {process_decorator}"
                )

        if log_record.partial_id is None:
            print(log_record.log)

        last_log = log_record


def stream_logs(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    invocation = actions.Invocation.from_id(
        args.invocation_id,
        roboto_client=context.roboto_client,
    )

    last_read: Optional[Any] = None
    wait_msg = ""
    last_log = None
    process_decorator = "=" * 10
    try:
        while True:
            try:
                log_record_generator = invocation.stream_logs(last_read)
                while True:
                    log_record = next(log_record_generator)
                    if wait_msg:
                        # Clear wait message
                        print("\r", " " * len(wait_msg), end="\r", flush=True)
                        wait_msg = ""

                    if last_log is None:
                        print(
                            f"{process_decorator} {log_record.process.value} {process_decorator}"
                        )
                    else:
                        if (
                            last_log.partial_id is not None
                            and log_record.partial_id != last_log.partial_id
                        ):
                            # `last_record` was the last partial message from its group--print it
                            print(last_log.log)

                        if last_log.process != log_record.process:
                            print()  # Newline separate process output
                            print(
                                f"{process_decorator} {log_record.process.value} {process_decorator}"
                            )

                    if log_record.partial_id is None:
                        print(log_record.log)

                    last_log = log_record
            except StopIteration as stop:
                if invocation.reached_terminal_status:
                    break

                if not wait_msg:
                    wait_msg = "Waiting for logs..."
                    print(wait_msg, end="", flush=True)

                last_read = stop.value
                time.sleep(2)
                invocation.refresh()
    except KeyboardInterrupt:
        pass  # Swallow

    if wait_msg:
        print("\r", " " * len(wait_msg), end="\r", flush=True)


def main(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    if args.tail:
        stream_logs(args, context, parser)
    else:
        get_logs(args, context, parser)


def get_logs_parser(parser: argparse.ArgumentParser):
    parser.add_argument("invocation_id")
    parser.add_argument("--tail", required=False, action="store_true")


get_logs_command = RobotoCommand(
    name="logs",
    logic=main,
    setup_parser=get_logs_parser,
    command_kwargs={"help": "Get invocation logs."},
)
