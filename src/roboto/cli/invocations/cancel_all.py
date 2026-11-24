# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain import actions
from ...time import utcnow
from ..command import RobotoCommand
from ..common_args import add_org_arg
from ..context import CLIContext


def cancel_all(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    """Cancel the ``--org`` organization's active invocations, and print the totals cancelled and failed.

    The command repeats its request until Roboto reports none left. Active invocations are those that have not
    completed, failed, or been cancelled. Each request cancels every queued one and a limited number of the scheduled
    and running ones created no later than the command's start, so a scheduled or running invocation created while the
    command runs is left alone. After each request that leaves more to cancel, the command prints that request's
    counts.

    The command stops in one of three ways, and each prints the totals cancelled and failed once it has tried to
    cancel at least one invocation:

    - Roboto reports no active invocations left.
    - ``--timeout`` is positive and more than that many seconds have passed when the next request is due. The command
      exits with status 2, and the usage error it prints to stderr also gives the totals.
    - The user presses Ctrl-C, and the command exits with status 0.
    """
    start_time = utcnow()
    total_success_count = 0
    total_failure_count = 0

    try:
        has_more = True

        while has_more:
            if args.timeout > 0:
                elapsed = (utcnow() - start_time).total_seconds()
                if elapsed > args.timeout:
                    parser.error(
                        f"Timeout of {args.timeout}s reached. "
                        f"Cancelled {total_success_count} invocations with {total_failure_count} failures."
                    )

            response = context.roboto_client.post(
                path="/v1/actions/invocations/cancel/all",
                data=actions.CancelActiveInvocationsRequest(created_before=start_time),
                owner_org_id=args.org,
            ).to_record(actions.CancelActiveInvocationsResponse)

            total_success_count += response.success_count
            total_failure_count += response.failure_count
            has_more = response.has_more

            if has_more:
                print(f"Progress: cancelled {response.success_count} invocations, {response.failure_count} failures.")

    except KeyboardInterrupt:
        pass
    finally:
        if total_success_count > 0 or total_failure_count > 0:
            print(
                f"Successfully cancelled {total_success_count} invocations. "
                f"Failed to cancel {total_failure_count} invocations."
            )


def cancel_all_parser(parser: argparse.ArgumentParser):
    add_org_arg(parser)
    parser.add_argument(
        "--timeout",
        dest="timeout",
        required=False,
        type=int,
        help=(
            "Amount of time to wait before giving up attempting to cancel active invocations. "
            "Defaults to -1, which is interpretted as 'try forever'."
        ),
        default=-1,
    )


cancel_all_command = RobotoCommand(
    name="cancel-all",
    logic=cancel_all,
    setup_parser=cancel_all_parser,
    command_kwargs={"help": "Cancel all queued and running invocations in your organization"},
)
