# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum
import typing
import urllib.parse

import pydantic

from .exceptions import (
    RobotoIllegalArgumentException,
)


class AssociationType(enum.Enum):
    """AssociationType is the Roboto domain entity type of the association."""

    Dataset = "dataset"
    File = "file"


class Association(pydantic.BaseModel):
    """Use to declare an association between two Roboto entities."""

    URL_ENCODING_SEP: typing.ClassVar[str] = ":"

    @classmethod
    def from_url_encoded_value(cls, encoded: str) -> "Association":
        """Reverse of Association::url_encode."""
        unquoted = urllib.parse.unquote_plus(encoded)
        association_type, association_id = unquoted.split(cls.URL_ENCODING_SEP)
        try:
            return cls(
                association_id=association_id,
                association_type=AssociationType(association_type),
            )
        except ValueError:
            raise RobotoIllegalArgumentException(
                f"Invalid association type '{association_type}'"
            ) from None

    association_id: str
    """Roboto identifier"""

    association_type: AssociationType
    """association_type is the Roboto domain entity type of the association."""

    def url_encode(self) -> str:
        """Association encoded in a URL path segment ready format."""
        return urllib.parse.quote_plus(
            f"{self.association_type.value}{Association.URL_ENCODING_SEP}{self.association_id}"
        )
