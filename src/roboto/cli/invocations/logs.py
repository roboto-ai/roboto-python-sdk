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


def get_logs(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    """Print the logs the invocation has written so far, under a header naming each container that wrote them."""
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
            if last_log.partial_id is not None and log_record.partial_id != last_log.partial_id:
                # last_log was the final part of a line split into several records. Only that part is
                # printed, and only once a record from another group arrives.
                print(last_log.log)

            if last_log.process != log_record.process:
                print()  # Blank line between one container's output and the next.
                print(f"{process_decorator} {log_record.process.value} {process_decorator}")

        if log_record.partial_id is None:
            print(log_record.log)

        last_log = log_record


def stream_logs(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    """Print the invocation's logs as it writes them, checking for new lines every 2 seconds until it ends.

    Logs are grouped under container headers as ``get_logs`` prints them. Pressing Ctrl-C stops following early.
    """
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
                        # Overwrite the `Waiting for logs...` line with spaces.
                        print("\r", " " * len(wait_msg), end="\r", flush=True)
                        wait_msg = ""

                    if last_log is None:
                        print(f"{process_decorator} {log_record.process.value} {process_decorator}")
                    else:
                        if last_log.partial_id is not None and log_record.partial_id != last_log.partial_id:
                            # last_log was the final part of a line split into several records. Only that part is
                            # printed, and only once a record from another group arrives.
                            print(last_log.log)

                        if last_log.process != log_record.process:
                            print()  # Blank line between one container's output and the next.
                            print(f"{process_decorator} {log_record.process.value} {process_decorator}")

                    if log_record.partial_id is None:
                        print(log_record.log)

                    last_log = log_record
            except StopIteration as stop:
                # The generator has yielded every line written so far; its return value resumes after them.
                if invocation.reached_terminal_status:
                    break

                if not wait_msg:
                    wait_msg = "Waiting for logs..."
                    print(wait_msg, end="", flush=True)

                last_read = stop.value
                time.sleep(2)
                invocation.refresh()
    except KeyboardInterrupt:
        pass  # Exit without printing a traceback.

    if wait_msg:
        print("\r", " " * len(wait_msg), end="\r", flush=True)


def main(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
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
