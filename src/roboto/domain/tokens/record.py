# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
from typing import Optional

import pydantic


class TokenContext(pydantic.BaseModel):
    token_id: str
    name: str
    description: Optional[str] = None
    expires: datetime.datetime
    last_used: Optional[datetime.datetime] = None
    enabled: bool = True


class TokenRecord(pydantic.BaseModel):
    secret: Optional[str] = None
    user_id: Optional[str] = None
    context: Optional[TokenContext] = None
