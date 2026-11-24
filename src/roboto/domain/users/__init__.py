# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Users: people, and service users that Roboto runs automated work as, who act in the organizations they belong to.

Use :py:class:`~roboto.domain.users.User` to fetch the caller or a user by ID, update a user's name, picture, and
notification settings, and delete a user.
"""

from .operations import (
    CreateUserRequest,
    UpdateUserRequest,
)
from .record import UserRecord
from .user import User

__all__ = [
    "CreateUserRequest",
    "User",
    "UserRecord",
    "UpdateUserRequest",
]
