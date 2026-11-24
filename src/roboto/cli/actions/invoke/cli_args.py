# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...command import (
    KeyValuePairsAction,
    NonBlankString,
)


def add_input_specification_args(parser: argparse.ArgumentParser) -> None:
    """Add the flags that select an action invocation's input data to ``parser``.

    ``roboto actions invoke`` and ``roboto actions invoke-local`` both use these flags. This adds two argument groups,
    each rendered as its own section of ``--help`` output:

    1. Selector-based input: ``--file-query``, ``--session-id``, ``--session-query``, ``--topic-query``
    2. Dataset and file path input: ``--dataset``, ``--file-path``

    A user may supply flags from one group or the other, not both, and ``--file-path`` requires ``--dataset``.
    argparse enforces neither rule, so a command that adds these flags must also pass its parsed arguments
    through ``validate_input_specification``.
    """
    selector_group = parser.add_argument_group(
        "Selector-Based Input",
        description=(
            "Specify input data with a RoboQL query or by session ID. "
            "Mutually exclusive with dataset and file path-based input."
        ),
    )
    selector_group.add_argument(
        "--file-query",
        required=False,
        type=NonBlankString,
        dest="file_query",
        help="RoboQL query to select input files.",
    )
    selector_group.add_argument(
        "--session-id",
        required=False,
        type=NonBlankString,
        action="append",
        dest="session_ids",
        help="Unique identifier for a session to use as input. Can be specified multiple times for multiple sessions.",
    )
    selector_group.add_argument(
        "--session-query",
        required=False,
        type=NonBlankString,
        dest="session_query",
        help="RoboQL query to select input sessions.",
    )
    selector_group.add_argument(
        "--topic-query",
        required=False,
        type=NonBlankString,
        dest="topic_query",
        help="RoboQL query to select input topics.",
    )

    dataset_group = parser.add_argument_group(
        "Dataset and File Path-Based Input",
        description=(
            "Specify input data with a dataset ID and one or more file paths. "
            "Mutually exclusive with selector-based input."
        ),
    )
    dataset_group.add_argument(
        "--dataset",
        required=False,
        type=NonBlankString,
        action="store",
        dest="dataset_id",
        help=(
            "Unique identifier for a dataset to use as the data source for this invocation. "
            "Required if --file-path is provided."
        ),
    )

    dataset_group.add_argument(
        "--file-path",
        required=False,
        type=NonBlankString,
        action="append",
        dest="file_paths",
        help=(
            "Specific file path from the dataset. "
            "Can be specified multiple times for multiple file paths. "
            "Requires --dataset to be specified."
        ),
    )


def add_parameter_args(parser: argparse.ArgumentParser) -> None:
    """Add the flags that set an action invocation's parameter values to ``parser``.

    ``roboto actions invoke`` and ``roboto actions invoke-local`` both use the repeatable ``-p``/``--parameter``
    flag this adds. Each use of the flag adds one ``<name>=<value>`` pair to ``params``, a dictionary of strings that
    is empty when the flag is absent. The value is everything after the first ``=``, and a name given twice keeps its
    last value.
    """
    parser.add_argument(
        "-p",
        "--parameter",
        required=False,
        metavar="<PARAMETER_NAME>=<PARAMETER_VALUE>",
        dest="params",
        action=KeyValuePairsAction,
        parse_json=False,  # Forwarded to KeyValuePairsAction, which then keeps each value a string.
        default=dict(),
        help=(
            "Parameter in ``<parameter_name>=<parameter_value>`` format. "
            "``parameter_value`` is parsed as a string. "
            "Can be specified multiple times for multiple parameters."
        ),
    )
