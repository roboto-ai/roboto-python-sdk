# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import decimal
import typing

from roboto.types import UserMetadata


def field_serializer_user_metadata(value: dict[str, typing.Any]) -> UserMetadata:
    for k, v in value.items():
        if type(v) in [bool, int, float, str]:
            continue
        elif type(v) is decimal.Decimal:
            value[k] = float(v)
        else:
            raise ValueError(
                f"Illegal metadata element with key '{k}',  type {type(v)}"
            )

    return value
