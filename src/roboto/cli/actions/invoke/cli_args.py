# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""CLI argument setup utilities.

This module contains shared argparse configuration functions used by both
hosted and local invocation commands.
"""

import argparse

from ...command import KeyValuePairsAction


def add_input_specification_args(parser: argparse.ArgumentParser) -> None:
    """Add input specification argument groups to parser.

    Adds two mutually exclusive groups:
    1. Query-based input (--file-query, --topic-query)
    2. Dataset + file paths input (--dataset, --file-path)
    """
    # Query-based input arguments
    query_group = parser.add_argument_group(
        "Query-Based Input",
        description=(
            "Specify input data with a RoboQL query. Mutually exclusive with 'dataset file path'-based input."
        ),
    )
    query_group.add_argument(
        "--file-query",
        required=False,
        dest="file_query",
        help="RoboQL query to select input files.",
    )
    query_group.add_argument(
        "--topic-query",
        required=False,
        dest="topic_query",
        help="RoboQL query to select input topics.",
    )

    # Dataset and file path-based input arguments
    dataset_group = parser.add_argument_group(
        "Dataset and File Path-Based Input",
        description=(
            "Specify input data with a dataset id and one or more file paths. "
            "Mutually exclusive with query-based input."
        ),
    )
    dataset_group.add_argument(
        "--dataset",
        required=False,
        action="store",
        dest="dataset_id",
        help=(
            "Unique identifier for dataset to use as data source for this invocation. "
            "Required if --file-path is provided."
        ),
    )

    dataset_group.add_argument(
        "--file-path",
        required=False,
        type=str,
        action="append",
        dest="file_paths",
        help=(
            "Specific file path from the dataset. "
            "Can be specified multiple times for multiple file paths. "
            "Requires --dataset to be specified."
        ),
    )


def add_parameter_args(parser: argparse.ArgumentParser) -> None:
    """Add parameter specification arguments to parser."""
    parser.add_argument(
        "-p",
        "--parameter",
        required=False,
        metavar="<PARAMETER_NAME>=<PARAMETER_VALUE>",
        dest="params",
        action=KeyValuePairsAction,
        parse_json=False,  # Passed to KeyValuePairsAction
        default=dict(),
        help=(
            "Parameter in ``<parameter_name>=<parameter_value>`` format. "
            "``parameter_value`` is parsed as a string. "
            "Can be specified multiple times for multiple parameters."
        ),
    )
