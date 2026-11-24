# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import decimal
import typing

from roboto.types import UserMetadata


def field_serializer_user_metadata(value: dict[str, typing.Any]) -> UserMetadata:
    """Serialize metadata values as strings, numbers and booleans, converting ``decimal.Decimal`` to ``float``.

    Changes ``value`` in place and returns it.

    Raises:
        ValueError: A value's type is not exactly ``bool``, ``int``, ``float``, ``str`` or ``decimal.Decimal``. This
            rejects ``None`` and subclasses, such as a ``str`` enum.
    """
    for k, v in value.items():
        if type(v) in [bool, int, float, str]:
            continue
        elif type(v) is decimal.Decimal:
            value[k] = float(v)
        else:
            raise ValueError(f"Illegal metadata element with key '{k}',  type {type(v)}")

    return value


def field_serializer_custom_field_values(value: dict[str, typing.Any]) -> dict[str, typing.Any]:
    """Serialize custom field values for JSON, writing each ``datetime`` with ``datetime.datetime.isoformat``.

    ``isoformat`` writes UTC as ``+00:00``. Pydantic's JSON encoding writes it as ``Z``, which
    ``datetime.datetime.fromisoformat`` rejects before Python 3.11, and the SDK supports Python 3.10.
    """
    return {k: v.isoformat() if isinstance(v, datetime.datetime) else v for k, v in value.items()}
