# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Input specification parsing utilities.

This module handles parsing and validating invocation input specifications
from CLI arguments.
"""

import argparse
import typing

from ....domain import actions


def parse_input_spec(
    args: argparse.Namespace,
) -> typing.Optional[actions.InvocationInput]:
    """Parse input specification from CLI arguments.

    Supports three input modes:
    1. Query-based: --file-query and/or --topic-query
    2. Dataset + paths: --dataset + --file-path
    3. No input: neither specified

    Returns:
        InvocationInput instance or None if no input is specified.
    """
    file_query = getattr(args, "file_query", None)
    topic_query = getattr(args, "topic_query", None)
    dataset_id = getattr(args, "dataset_id", None)
    file_paths = getattr(args, "file_paths", None)

    # Query-based input
    if file_query is not None or topic_query is not None:
        return actions.InvocationInput(
            files=(actions.FileSelector(query=file_query) if file_query is not None else None),
            topics=(actions.DataSelector(query=topic_query) if topic_query is not None else None),
        )

    # Dataset + paths input
    if dataset_id is not None and file_paths:
        return actions.InvocationInput.from_dataset_file_paths(dataset_id, file_paths)

    # No input specified
    return None


def validate_input_specification(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Validate mutual exclusivity of input specification methods.

    Query-based input (--file-query, --topic-query) is mutually exclusive with
    dataset+paths input (--dataset + --file-path).
    """
    has_query_input = getattr(args, "file_query", None) is not None or getattr(args, "topic_query", None) is not None
    has_dataset_input = getattr(args, "dataset_id", None) is not None or getattr(args, "file_paths", None) is not None

    if has_query_input and has_dataset_input:
        parser.error(
            "Cannot specify input data as both a query (--file-query/--topic-query) "
            "and as a dataset/file paths combination (--dataset/--file-path)."
        )

    # Validate that --file-path requires --dataset
    if getattr(args, "file_paths", None) is not None and args.dataset_id is None:
        parser.error("--file-path requires --dataset to be specified.")
