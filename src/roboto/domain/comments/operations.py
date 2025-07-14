# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic

from .record import CommentEntityType


class CreateCommentRequest(pydantic.BaseModel):
    """Request payload for creating a new comment.

    This model defines the required information to create a comment
    on a Roboto platform entity.
    """

    entity_type: CommentEntityType
    """Type of entity to attach the comment to."""

    entity_id: str
    """Unique identifier of the entity to attach the comment to."""

    comment_text: str
    """Text content of the comment, may include `@mention` syntax."""


class UpdateCommentRequest(pydantic.BaseModel):
    """Request payload for updating an existing comment.

    This model defines the information that can be modified when
    updating a comment.
    """

    comment_text: str
    """Updated text content of the comment, may include `@mention` syntax."""
