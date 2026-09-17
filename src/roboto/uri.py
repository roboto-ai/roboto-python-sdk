# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto://`` URI scheme, a host-independent reference to one platform entity.

``roboto://<type>/<id>`` names an entity without naming a web address. Platform event
payloads, AI chat answers, and notifications all identify entities this way; opening
one in the Roboto web app lands on that entity's page. A URI may carry a ``?t=`` epoch
nanosecond timestamp, which asks a time-aware page to open at that instant.
"""

import dataclasses
import re
import typing
import urllib.parse

from .compat import StrEnum

ROBOTO_URI_SCHEME = "roboto"

TIMESTAMP_QUERY_PARAM = "t"
"""Query parameter naming the instant a URI points at, in epoch nanoseconds."""


class RobotoUriType(StrEnum):
    """The entity kinds a ``roboto://`` URI may name.

    A ``roboto://`` URI whose type is absent from this enum names no entity. The web
    app relies on that to reserve type names for links addressing its own controls
    rather than an entity, so an unrecognized type is ordinary input, not corruption.
    """

    Collection = "collection"
    Dataset = "dataset"
    Device = "device"
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
"""Finds where a ``roboto://`` URI starts and ends inside prose, for callers rewriting
URIs into links. Deliberately looser than :meth:`RobotoUri.parse`: it matches text this
module refuses to parse, because a finder that skipped a malformed URI would leave it
in the rendered output as raw text."""


@dataclasses.dataclass(frozen=True)
class RobotoUri:
    """A parsed ``roboto://<type>/<id>`` reference, optionally carrying a timestamp.

    ``str()`` renders it back to URI text in normalized form: the type is lowercased,
    empty path segments are dropped, and only the ``t`` query parameter survives, so
    ``str(RobotoUri.parse(text))`` equals ``text`` only when ``text`` is already
    normalized.

    Raises:
        ValueError: ``id`` is empty, or ``timestamp_ns`` is negative.
    """

    type: RobotoUriType
    id: str
    timestamp_ns: typing.Optional[int] = None
    """The instant this URI points at, in nanoseconds since the Unix epoch, written as
    the URI's ``?t=`` parameter. ``None`` when the URI names an entity and no instant.
    Only pages showing data over time act on it; the rest ignore it."""

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("A roboto:// URI needs a non-empty entity id.")
        if self.timestamp_ns is not None and self.timestamp_ns < 0:
            raise ValueError(f"A roboto:// URI timestamp cannot be negative, got {self.timestamp_ns}.")

    def __str__(self) -> str:
        uri = f"{ROBOTO_URI_SCHEME}://{self.type.value}/{self.id}"
        if self.timestamp_ns is None:
            return uri
        return f"{uri}?{TIMESTAMP_QUERY_PARAM}={self.timestamp_ns}"

    @classmethod
    def parse(cls, text: str) -> "RobotoUri":
        """Read ``roboto://<type>/<id>``, with an optional ``?t=<epoch_ns>``, into its parts.

        Query parameters other than ``t`` are ignored and the entity type is matched
        case-insensitively, so a URI written by any Roboto surface parses here.

        Args:
            text: The URI to read. Anything else raises rather than returning ``None``,
                so a caller sifting arbitrary prose should locate candidates with
                :data:`ROBOTO_URI_IN_TEXT_PATTERN` first.

        Raises:
            ValueError: ``text`` is not a ``roboto://`` URI, names a type outside
                :class:`RobotoUriType`, carries no entity id or more than one path
                segment, or carries a ``t`` that is not a whole number of nanoseconds.
        """
        split = urllib.parse.urlsplit(text)
        if split.scheme != ROBOTO_URI_SCHEME:
            raise ValueError(f"Not a roboto:// entity URI: {text!r}")

        segments = [segment for segment in split.path.split("/") if segment]
        if len(segments) != 1:
            # Reading one entity out of a URI that names a path of them would act on
            # whichever segment came first, which is unlikely to be the one the writer
            # meant. Refusing hands that judgment back to the caller.
            raise ValueError(f"A roboto:// entity URI names exactly one entity id: {text!r}")

        # urlsplit lowercases the host exactly as a browser's URL parser does, so both
        # ends of a link agree on the type without either having to normalize by hand.
        try:
            uri_type = RobotoUriType(split.hostname or "")
        except ValueError:
            raise ValueError(f"Unknown roboto:// entity type {split.hostname!r} in {text!r}") from None

        return cls(type=uri_type, id=segments[0], timestamp_ns=cls.__timestamp(split.query, text))

    @staticmethod
    def __timestamp(query: str, text: str) -> typing.Optional[int]:
        values = urllib.parse.parse_qs(query).get(TIMESTAMP_QUERY_PARAM)
        if not values:
            return None
        try:
            return int(values[0])
        except ValueError:
            raise ValueError(f"Timestamp {values[0]!r} in {text!r} is not a whole number of nanoseconds.") from None


__all__: typing.Sequence[str] = (
    "ROBOTO_URI_IN_TEXT_PATTERN",
    "ROBOTO_URI_SCHEME",
    "TIMESTAMP_QUERY_PARAM",
    "RobotoUri",
    "RobotoUriType",
)
