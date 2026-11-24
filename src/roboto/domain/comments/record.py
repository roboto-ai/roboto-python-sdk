# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime

import pydantic

from ...compat import StrEnum


class CommentEntityType(StrEnum):
    """Kind of Roboto resource a comment is on."""

    Action = "action"
    """Actions (:py:class:`~roboto.domain.actions.Action`)."""

    Collection = "collection"
    """Collections (:py:class:`~roboto.domain.collections.Collection`)."""

    Dataset = "dataset"
    """Datasets (:py:class:`~roboto.domain.datasets.Dataset`)."""

    File = "file"
    """Files (:py:class:`~roboto.domain.files.File`)."""

    Invocation = "invocation"
    """Invocations (:py:class:`~roboto.domain.actions.Invocation`)."""

    Trigger = "trigger"
    """Triggers (:py:class:`~roboto.domain.triggers.Trigger`)."""


class CommentRecord(pydantic.BaseModel):
    """Data record of a comment, as the Roboto API returns it.

    A comment is text a user writes on an action, collection, dataset, file, invocation, or trigger, and it can
    mention other users in the organization. :py:class:`~roboto.domain.comments.Comment` wraps this record with methods
    that act on the comment, and exposes it as :py:attr:`~roboto.domain.comments.Comment.record`.
    """

    org_id: str
    """ID of the organization that owns the comment."""

    comment_id: str
    """Unique ID of the comment, beginning with ``cm_``."""

    entity_type: CommentEntityType
    """Kind of resource the comment is on."""

    entity_id: str
    """ID of the resource the comment is on.

    For example, a dataset's ``ds_`` ID when ``entity_type`` is ``CommentEntityType.Dataset``.
    """

    created: datetime.datetime
    """Time the comment was created."""

    created_by: str
    """ID of the user who wrote the comment."""

    comment_text: str
    """Text of the comment, in which each mention of a user is written ``@[<display_name>](<user_id>)``."""

    mentions: list[str] = pydantic.Field(default_factory=list)
    """IDs of the users ``comment_text`` mentions, in the order they appear.

    Roboto reads them from the ``@[<display_name>](<user_id>)`` mentions in the text when the comment is created or
    edited.
    """

    modified: datetime.datetime
    """Time the comment was last modified."""

    modified_by: str
    """ID of the user who wrote the comment.

    Roboto sets it to ``created_by`` and does not change it when the comment is edited.
    """
