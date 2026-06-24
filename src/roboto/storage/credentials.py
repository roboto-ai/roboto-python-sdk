# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ..time import utcnow
from .object_store import Credentials


class RobotoCredentials(pydantic.BaseModel):
    """
    Credentials returned from the Roboto Platform
    """

    access_key_id: str
    bucket: str
    expiration: datetime.datetime
    secret_access_key: str
    session_token: str
    region: str
    required_prefix: str

    def is_expired(self) -> bool:
        return utcnow() >= self.expiration

    def to_dict(self) -> dict[str, typing.Any]:
        return self.model_dump(mode="json")

    def to_object_store_credentials(self) -> Credentials:
        return {
            "access_key": self.access_key_id,
            "secret_key": self.secret_access_key,
            "token": self.session_token,
            "expiry_time": self.expiration.isoformat(),
            "region": self.region,
        }
