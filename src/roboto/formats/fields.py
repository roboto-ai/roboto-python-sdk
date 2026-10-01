# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class FieldSelection:
    """A field to read out of a data file, identified by its path through the schema.

    The :py:mod:`roboto.formats` readers take the fields to read as ``FieldSelection`` values;
    :py:meth:`~roboto.domain.topics.MessagePathRecord.to_field_selection` converts a topic's message path into one.
    """

    path_in_schema: tuple[str, ...]
    """Path components locating this field in the source data schema, root to leaf.

    A component may contain dots, so ``("header", "stamp")`` (a ``stamp`` field nested in a ``header`` struct) and
    ``("header.stamp",)`` (a top-level column named ``header.stamp``) are different fields.
    """
