# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
from enum import Enum

import pydantic


class CommentEntityType(str, Enum):
    """Enumeration of Roboto platform entities that support comments.

    This enum defines the types of resources in the Roboto platform that can
    have comments attached to them. Each value corresponds to a specific
    domain entity type.
    """

    Action = "action"
    """Actions that can be executed on the platform."""

    Collection = "collection"
    """Collections of related datasets or resources."""

    Dataset = "dataset"
    """Datasets containing uploaded data files."""

    File = "file"
    """Individual files within datasets."""

    Invocation = "invocation"
    """Executions of actions with specific inputs."""

    Trigger = "trigger"
    """Automated triggers for action execution."""


class CommentRecord(pydantic.BaseModel):
    """A wire-transmissible representation of a comment.

    This model represents the complete data structure of a comment as stored
    and transmitted by the Roboto platform API. It includes all metadata
    about the comment including creation/modification timestamps, user mentions,
    and the associated entity information.
    """

    org_id: str
    """Organization ID that owns this comment (partition key)."""

    comment_id: str
    """Unique identifier for this comment."""

    entity_type: CommentEntityType
    """Type of entity this comment is attached to."""

    entity_id: str
    """Unique identifier of the entity this comment is attached to."""

    created: datetime.datetime
    """Timestamp when the comment was created.

    Stored as datetime.datetime in Python but serialized as ISO 8601 string in UTC
    when transmitted over the API.
    """

    created_by: str
    """User ID of the comment author."""

    comment_text: str
    """The text content of the comment, may include `@mention` syntax."""

    mentions: list[str] = pydantic.Field(default_factory=list)
    """List of user IDs mentioned in this comment using `@mention` syntax."""

    modified: datetime.datetime
    """Timestamp when the comment was last modified.

    Stored as datetime.datetime in Python but serialized as ISO 8601 string in UTC
    when transmitted over the API.
    """

    modified_by: str
    """User ID of the user who last modified this comment."""

    # for v2
    # parent_comment_id: str
