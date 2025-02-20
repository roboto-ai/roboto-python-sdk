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


def cancel_all(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    """
    Iteratively cancel active invocations until the response returns 0 for count_remaining
    or the configured timeout is reached.
    """
    start_time = utcnow()
    total_success_count = 0
    total_failure_count = 0

    try:
        while True:
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

            if response.count_remaining == 0:
                print(
                    f"Successfully cancelled {total_success_count} invocations "
                    f"with {total_failure_count} failures"
                )
                break
            else:
                print(
                    f"Cancelled {response.success_count} invocations "
                    f"({response.failure_count} failures). "
                    f"Remaining: {response.count_remaining}"
                )

    except KeyboardInterrupt:
        print(
            f"Successfully cancelled {total_success_count} invocations "
            f"with {total_failure_count} failures"
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
    command_kwargs={
        "help": "Cancel all queued and running invocations in your organization"
    },
)
