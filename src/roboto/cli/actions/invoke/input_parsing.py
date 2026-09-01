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

_SELECTOR_FLAGS = {
    "--file-query": "file_query",
    "--session-id": "session_ids",
    "--session-query": "session_query",
    "--topic-query": "topic_query",
}
"""Every flag that names input data by query or by ID, mapped to its argparse ``dest``.

``add_input_specification_args`` registers these flags. One it registers but this mapping omits is silently
ignored: it contributes nothing to the invocation's input and does not conflict with ``--dataset`` or
``--file-path``.
"""


def parse_input_spec(
    args: argparse.Namespace,
) -> typing.Optional[actions.InvocationInput]:
    """Build the input specification for an action invocation from its parsed command line.

    Input data is specified one of two ways, or not at all:

    1. Selectors: ``--file-query``, ``--session-id``, ``--session-query``, ``--topic-query``. Any combination is
       accepted, and files, sessions, and topics are each looked up independently of the others.
       ``--session-id`` and ``--session-query`` given together select every session named by ID plus every
       session the query matches, each session once.
    2. A dataset and paths within it: ``--dataset`` together with ``--file-path``.

    The two ways are mutually exclusive. Run ``args`` through ``validate_input_specification`` first to reject a
    command line that mixes them.

    Args:
        args: Parsed arguments from a parser that ``add_input_specification_args`` has configured.

    Returns:
        The selected input, or None when no selector flag was given and ``--dataset`` and ``--file-path`` were
        not both given.
    """
    if _has_selector_input(args):
        file_query = getattr(args, "file_query", None)
        session_ids = getattr(args, "session_ids", None)
        session_query = getattr(args, "session_query", None)
        topic_query = getattr(args, "topic_query", None)

        return actions.InvocationInput(
            files=(actions.FileSelector(query=file_query) if file_query is not None else None),
            sessions=(
                actions.DataSelector(ids=session_ids, query=session_query)
                if session_ids is not None or session_query is not None
                else None
            ),
            topics=(actions.DataSelector(query=topic_query) if topic_query is not None else None),
        )

    dataset_id = getattr(args, "dataset_id", None)
    file_paths = getattr(args, "file_paths", None)
    if dataset_id is not None and file_paths:
        return actions.InvocationInput.from_dataset_file_paths(dataset_id, file_paths)

    return None


def validate_input_specification(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Reject input flag combinations argparse cannot express, before an invocation is submitted.

    Two rules are enforced, in order:

    1. The selector flags in ``_SELECTOR_FLAGS`` may not be combined with ``--dataset`` or ``--file-path``.
    2. ``--file-path`` requires ``--dataset``.

    Args:
        args: Parsed arguments from a parser that ``add_input_specification_args`` has configured.
        parser: The parser that produced ``args``, used to report a broken rule.

    Raises:
        SystemExit: Raised by ``parser.error`` when a rule is broken. The reason and the usage text are printed
            to stderr and the process exits, so this function does not return to its caller in that case.
    """
    dataset_id = getattr(args, "dataset_id", None)
    file_paths = getattr(args, "file_paths", None)

    if _has_selector_input(args) and (dataset_id is not None or file_paths is not None):
        parser.error(
            f"Cannot specify input data as both a selector ({'/'.join(_SELECTOR_FLAGS.keys())}) "
            "and as a dataset/file paths combination (--dataset/--file-path)."
        )

    if file_paths is not None and dataset_id is None:
        parser.error("--file-path requires --dataset to be specified.")


def _has_selector_input(args: argparse.Namespace) -> bool:
    return any(getattr(args, dest, None) is not None for dest in _SELECTOR_FLAGS.values())
