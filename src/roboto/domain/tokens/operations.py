# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from roboto.auth.scope import ApiScope


class CreateTokenRequest(pydantic.BaseModel):
    """Request payload to create a new token"""

    api_scopes: typing.Optional[set[ApiScope]] = pydantic.Field(
        default=None, description="Optional set of API scopes to grant this token."
    )
    description: typing.Optional[str] = pydantic.Field(
        default=None, description="An optional longer description for this token."
    )
    expiry_days: int = pydantic.Field(description="Number of days until the token expires")
    name: str = pydantic.Field(description="A human-readable name for this token.")
