# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import dataclasses
import pathlib
import typing

import pydantic

from ..domain.files import File, FileRecord

DEFAULT_INPUT_FILE = pathlib.Path.cwd() / "action_input.json"


class ActionInputRecord(pydantic.BaseModel):
    """Serializable representation of an ``ActionInput``."""

    files: collections.abc.Sequence[
        tuple[FileRecord, typing.Optional[pathlib.Path]]
    ] = pydantic.Field(default_factory=list)


@dataclasses.dataclass
class ActionInput:
    """
    Resolved references to input data an Action was given to operate on.

    To use, access via :py:meth:`~roboto.action_runtime.ActionRuntime.get_input`.

    Example:
        From within an Action, list files passed as input and check their size:

        >>> action_runtime = ActionRuntime.from_env()
        >>> action_input = action_runtime.get_input()
        >>> for file, local_path in action_input.files:
        >>>     print(f"{file.file_id} is {local_path.stat().st_size} bytes")

    """

    files: collections.abc.Sequence[tuple[File, typing.Optional[pathlib.Path]]] = (
        dataclasses.field(default_factory=list)
    )
    """
    Files passed as input data to an action invocation.

    A file is represented as a tuple of (File, Optional[Path]) where:
    - File exposes metadata about the file and useful file operations
    - Optional[Path] is the local file path if the file has been downloaded
    """
