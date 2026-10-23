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

    Put it in the field's ``typing.Annotated`` metadata, beside a validator that runs ``model``'s validation. Pydantic
    ignores it. A formatter of validation errors reads it, so that a message about an error that validation raised may
    name the fields ``model`` declares.
    """

    model: type[pydantic.BaseModel]
