# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic

from .record import CommentEntityType


class CreateCommentRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.comments.Comment.create`."""

    entity_type: CommentEntityType
    """Type of the resource to comment on."""

    entity_id: str
    """ID of the resource to comment on, such as ``ds_12345`` for a dataset."""

    comment_text: str
    """Text of the comment.

    A mention, written ``@[<display_name>](<user_id>)``, adds that user to the comment's ``mentions`` and notifies
    them, by email unless their settings turn off comment-mention emails. Every user mentioned other than the caller
    must belong to the caller's organization; otherwise Roboto raises ``RobotoUnauthorizedException``.
    """


class UpdateCommentRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.comments.Comment.update_comment`."""

    comment_text: str
    """New text of the comment, which replaces the old text.

    Mentions take the same form as in ``CreateCommentRequest.comment_text``. Only users the previous text did not
    mention are notified.
    """
