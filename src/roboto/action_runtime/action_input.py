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
from ..domain.topics import Topic, TopicRecord

DEFAULT_INPUT_FILE = pathlib.Path.cwd() / "action_input.json"


class ActionInputRecord(pydantic.BaseModel):
    """Serializable representation of an ``ActionInput``."""

    files: collections.abc.Sequence[
        tuple[FileRecord, typing.Optional[pathlib.Path]]
    ] = pydantic.Field(default_factory=list)

    topics: collections.abc.Sequence[TopicRecord] = pydantic.Field(default_factory=list)


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

    topics: collections.abc.Sequence[Topic] = dataclasses.field(default_factory=list)
    """
    Topics passed as input data to an action invocation.
    """

    def get_topics_by_name(self, topic_name: str) -> list[Topic]:
        """
        Returns any topics in this ``ActionInput`` that have the provided name.

        Args:
            topic_name: Topic name to look for.

        Returns:
            A list of matching ``Topic`` instances from ``self.topics``. If no topics
            have the provided name, the list will be empty. Otherwise, there will be
            one or more topics in the list, depending on the topic selectors provided
            to the action invocation.
        """

        return [topic for topic in self.topics if topic.name == topic_name]
