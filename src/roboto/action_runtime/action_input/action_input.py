# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import pathlib
import typing

import pydantic

from ...domain.files import File, FileRecord
from ...domain.topics import Topic, TopicRecord
from ...experimental.sessions import Session, SessionRecord
from ...http import RobotoClient

DEFAULT_INPUT_FILE = pathlib.Path.cwd() / "action_input.json"
"""Path of an ``action_input.json`` file in the working directory at the time this module is imported.

No SDK method reads it.
"""


class ActionInputRecord(pydantic.BaseModel):
    """Data record of an action invocation's input: the files, sessions, and topics its input selectors matched.

    Returned by :py:meth:`~roboto.action_runtime.ActionInputResolver.resolve_input_spec`, which Roboto calls while it
    sets up an invocation. :py:meth:`~roboto.action_runtime.InvocationContext.get_input` reads it back and wraps it in
    :py:class:`~roboto.action_runtime.ActionInput`.
    """

    files: collections.abc.Sequence[tuple[FileRecord, typing.Optional[pathlib.Path]]] = pydantic.Field(
        default_factory=list
    )
    """Records of the files the invocation's file selectors matched, each paired with the file's local path.

    The path is ``None`` when the files were not downloaded.
    """

    sessions: collections.abc.Sequence[SessionRecord] = pydantic.Field(default_factory=list)
    """Records of the sessions the invocation's session selectors matched."""

    topics: collections.abc.Sequence[TopicRecord] = pydantic.Field(default_factory=list)
    """Records of the topics the invocation's topic selectors matched."""


@dataclasses.dataclass
class ActionInput:
    """Input data of an action invocation: the files, sessions, and topics its input selectors matched.

    Inside an action, fetch it with :py:meth:`~roboto.action_runtime.InvocationContext.get_input`; actions do not build
    it directly.
    """

    files: collections.abc.Sequence[tuple[File, typing.Optional[pathlib.Path]]] = dataclasses.field(
        default_factory=list
    )
    """Files the invocation's file selectors matched, as ``(file, local_path)`` tuples.

    ``file`` is a :py:class:`~roboto.domain.files.File`. ``local_path`` is where Roboto downloaded the file before the
    action started, or ``None`` when the action does not require downloaded inputs
    (:py:attr:`~roboto.domain.actions.Action.requires_downloaded_inputs`).
    """

    sessions: collections.abc.Sequence[Session] = dataclasses.field(default_factory=list)
    """Sessions (:py:class:`~roboto.experimental.sessions.Session`) the invocation's session selectors matched."""

    topics: collections.abc.Sequence[Topic] = dataclasses.field(default_factory=list)
    """Topics (:py:class:`~roboto.domain.topics.Topic`) the invocation's topic selectors matched."""

    @classmethod
    def from_record(cls, record: ActionInputRecord, roboto_client: RobotoClient) -> ActionInput:
        """Build an ``ActionInput`` from its record, wrapping each file, session, and topic record.

        :py:meth:`~roboto.action_runtime.InvocationContext.get_input` builds an action's input through it, so most code
        never calls it.

        Args:
            record: Record of the invocation's input.
            roboto_client: Client to make requests to Roboto with.
        """

        return cls(
            files=[(File(file_rec, roboto_client), path) for file_rec, path in record.files],
            sessions=[Session(session_rec, roboto_client) for session_rec in record.sessions],
            topics=[Topic(topic_rec, roboto_client) for topic_rec in record.topics],
        )

    def get_topics_by_name(self, topic_name: str) -> list[Topic]:
        """Return the input topics with this name.

        Several input topics can share a name, such as the same topic recorded in two files.

        Args:
            topic_name: Name of the topics to return, such as ``"/imu/data"``.

        Returns:
            Topics in ``topics`` with this name, in their order there. Empty when no input topic has this name.
        """

        return [topic for topic in self.topics if topic.name == topic_name]
