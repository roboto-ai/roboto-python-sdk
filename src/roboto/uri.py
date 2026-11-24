# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses
import re
import typing
import urllib.parse

from .compat import StrEnum

ROBOTO_URI_SCHEME = "roboto"
"""Scheme of every ``RobotoUri``: the ``roboto`` in ``roboto://``."""

TIMESTAMP_QUERY_PARAM = "t"
"""Query parameter that holds the instant a URI points at, in nanoseconds since the Unix epoch."""

VERSION_QUERY_PARAM = "v"
"""Query parameter that holds the version of the entity a URI points at."""


class RobotoUriType(StrEnum):
    """Type of entity a ``RobotoUri`` names, written as the ``<type>`` in ``roboto://<type>/<id>``.

    A ``roboto://`` URI whose type is not a member names no entity. The Roboto web app reserves other types, such as
    ``ui``, for links to its own controls, so treat an unknown type as a link to something other than an entity, not as
    corrupt data.
    """

    Collection = "collection"
    Dataset = "dataset"
    Device = "device"
    DeviceType = "device_type"
    Event = "event"
    File = "file"
    Invocation = "invocation"
    Layout = "layout"
    MessagePath = "msgpath"
    Org = "org"
    Session = "session"
    Topic = "topic"
    Trigger = "trigger"
    Workspace = "workspace"


ROBOTO_URI_IN_TEXT_PATTERN = re.compile(
    rf"{ROBOTO_URI_SCHEME}://[a-z_]+/[A-Za-z0-9_\-./]+(?:\?[A-Za-z0-9_=&%.\-]*)?",
)
"""Regular expression that finds ``roboto://`` URIs in text, such as an answer from Roboto's AI.

It also matches text ``RobotoUri.parse`` rejects, such as an unknown type or more than one path segment, so a caller
that turns each match into a link turns a malformed URI into one too, instead of leaving it as raw text.
"""


@dataclasses.dataclass(frozen=True)
class RobotoUri:
    """A reference to one Roboto entity, such as a dataset or file, as ``roboto://<type>/<id>`` text.

    The URI names the entity without naming a web address. Roboto writes one as the subject of a platform event, as
    the target of a file that links to another file, and in answers from Roboto's AI. The Roboto web app opens a URI
    of most types at the entity's page.

    ``str()`` writes the URI as text, with ``t`` and ``v`` query parameters for ``timestamp_ns`` and ``version``.
    ``str(RobotoUri.parse(text))`` equals ``text`` only when ``text`` is already in that form: a lowercase type, no
    empty path segments, and no query parameters other than ``t`` and ``v``, in that order.

    Raises:
        ValueError: ``id`` is empty, ``timestamp_ns`` is below 0, or ``version`` is below 1.
    """

    type: RobotoUriType
    """Type of entity the URI names."""

    id: str
    """ID of the entity, such as ``ds_12345`` for a dataset."""

    timestamp_ns: typing.Optional[int] = None
    """Instant the URI points at, in nanoseconds since the Unix epoch, or ``None`` if it points at no instant.

    Written as the ``t`` query parameter. Pages in the Roboto web app that show data over time open at this instant;
    other pages ignore it.
    """

    version: typing.Optional[int] = None
    """Version of the entity the URI points at, or ``None`` if it names no version.

    Written as the ``v`` query parameter. The URI of a file that links to another file carries one, so the link keeps
    pointing at the version of the target it was made against.
    """

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("A roboto:// URI needs a non-empty entity id.")
        if self.timestamp_ns is not None and self.timestamp_ns < 0:
            raise ValueError(f"A roboto:// URI timestamp cannot be negative, got {self.timestamp_ns}.")
        if self.version is not None and self.version < 1:
            raise ValueError(f"A roboto:// URI version starts at 1, got {self.version}.")

    def __str__(self) -> str:
        uri = f"{ROBOTO_URI_SCHEME}://{self.type.value}/{self.id}"
        query = urllib.parse.urlencode(
            {
                name: value
                for name, value in ((TIMESTAMP_QUERY_PARAM, self.timestamp_ns), (VERSION_QUERY_PARAM, self.version))
                if value is not None
            }
        )
        return f"{uri}?{query}" if query else uri

    @classmethod
    def parse(cls, text: str) -> "RobotoUri":
        """Parse ``roboto://<type>/<id>`` text, with its optional ``t`` and ``v`` query parameters, into a URI.

        The type is matched without regard to case, and query parameters other than ``t`` and ``v`` are ignored.

        Args:
            text: The URI, and nothing else. To find URIs inside longer text, match it against
                ``ROBOTO_URI_IN_TEXT_PATTERN`` first.

        Raises:
            ValueError: ``text`` is not a ``roboto://`` URI, its type is not a member of ``RobotoUriType``, it has no
                entity ID or more than one path segment, its ``t`` is not a whole number at or above 0, or its ``v`` is
                not a whole number at or above 1.
        """
        split = urllib.parse.urlsplit(text)
        if split.scheme != ROBOTO_URI_SCHEME:
            raise ValueError(f"Not a roboto:// entity URI: {text!r}")

        segments = [segment for segment in split.path.split("/") if segment]
        if len(segments) != 1:
            # A URI such as roboto://dataset/ds_1/files/fl_2 could mean either ID, so refuse it rather than guess.
            raise ValueError(f"A roboto:// entity URI names exactly one entity id: {text!r}")

        # hostname is the type lowercased, as a browser's URL parser lowercases it, so this reads the same type as
        # the Roboto web app.
        try:
            uri_type = RobotoUriType(split.hostname or "")
        except ValueError:
            raise ValueError(f"Unknown roboto:// entity type {split.hostname!r} in {text!r}") from None

        query = urllib.parse.parse_qs(split.query)
        return cls(
            type=uri_type,
            id=segments[0],
            timestamp_ns=cls.__whole_number(
                query, TIMESTAMP_QUERY_PARAM, text, "Timestamp", "a whole number of nanoseconds"
            ),
            version=cls.__whole_number(query, VERSION_QUERY_PARAM, text, "Version", "a whole number"),
        )

    @staticmethod
    def __whole_number(
        query: dict[str, list[str]], param: str, text: str, label: str, meaning: str
    ) -> typing.Optional[int]:
        values = query.get(param)
        if not values:
            return None
        try:
            return int(values[0])
        except ValueError:
            raise ValueError(f"{label} {param}={values[0]!r} in {text!r} is not {meaning}.") from None


__all__: typing.Sequence[str] = (
    "ROBOTO_URI_IN_TEXT_PATTERN",
    "ROBOTO_URI_SCHEME",
    "TIMESTAMP_QUERY_PARAM",
    "VERSION_QUERY_PARAM",
    "RobotoUri",
    "RobotoUriType",
)
