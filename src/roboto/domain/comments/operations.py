# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic

from .record import CommentEntityType


class CreateCommentRequest(pydantic.BaseModel):
    entity_type: CommentEntityType
    entity_id: str
    comment_text: str


class UpdateCommentRequest(pydantic.BaseModel):
    comment_text: str
