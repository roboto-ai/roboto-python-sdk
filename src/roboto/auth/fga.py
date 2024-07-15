# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


class AuthZTupleRecord(pydantic.BaseModel):
    """
    Fully qualified record of (user has relation to obj)
    """

    user: str
    relation: str
    obj: str


class EditAccessRequest(pydantic.BaseModel):
    add: list[AuthZTupleRecord] = pydantic.Field(default_factory=list)
    remove: list[AuthZTupleRecord] = pydantic.Field(default_factory=list)


class GetAccessResponse(pydantic.BaseModel):
    relations: list[AuthZTupleRecord]
    group_permissions: dict[str, list[str]] = pydantic.Field(default_factory=dict)
