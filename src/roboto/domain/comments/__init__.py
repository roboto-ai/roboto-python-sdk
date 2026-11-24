# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Comments: text users write on actions, collections, datasets, files, invocations, and triggers.

A comment can mention other users in the organization, which notifies them. Use
:py:class:`~roboto.domain.comments.Comment` to create, find, update, and delete comments.
"""

from .comment import Comment
from .operations import (
    CreateCommentRequest,
    UpdateCommentRequest,
)
from .record import (
    CommentEntityType,
    CommentRecord,
)

__all__ = (
    "Comment",
    "CommentRecord",
    "CreateCommentRequest",
    "CommentEntityType",
    "UpdateCommentRequest",
)
