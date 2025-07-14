# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Comments module for the Roboto SDK.

This module provides functionality for creating, retrieving, updating, and deleting
comments on various Roboto platform entities such as datasets, files, actions,
invocations, triggers, and collections.

Comments support `@mention` syntax to notify users and can be queried by entity,
entity type, user, or organization. The module includes both the high-level
:py:class:`Comment` domain entity and supporting data structures for API operations.
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
