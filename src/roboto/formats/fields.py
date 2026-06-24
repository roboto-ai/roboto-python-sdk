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

    This is the single currency type the :py:mod:`roboto.formats` decoders accept.
    Each bounded context (e.g. :py:mod:`roboto.domain.topics`) translates its own field
    record into a ``FieldSelection`` at the boundary rather than passing the record in
    directly.
    """

    path_in_schema: tuple[str, ...]
    """Path components locating this field in the source data schema, root to leaf."""

    @property
    def source_path(self) -> str:
        """The field's dot-joined name as it appears in the source data / Arrow schema."""
        return ".".join(self.path_in_schema)
