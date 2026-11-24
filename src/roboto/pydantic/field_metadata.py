# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses

import pydantic


@dataclasses.dataclass(frozen=True)
class ValidatedAgainst:
    """Field metadata naming the model a field's value is validated against while the field keeps the value as sent.

    Put it in the field's ``typing.Annotated`` metadata, beside a validator that checks the value with ``model``.
    Pydantic ignores it. Roboto reads it when it rejects a request: the error message names only the fields the
    request's model declares, and this metadata lets it also name the fields ``model`` declares inside this field's
    value.
    """

    model: type[pydantic.BaseModel]
