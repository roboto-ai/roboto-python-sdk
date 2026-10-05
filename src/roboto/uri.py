# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto://`` URI scheme, a host-independent reference to one platform entity.

``roboto://<type>/<id>`` names an entity without naming a web address. Platform event
payloads, AI chat answers, and notifications all identify entities this way; opening
one in the Roboto web app lands on that entity's page. A URI may carry a ``?t=`` epoch
nanosecond timestamp, which asks a time-aware page to open at that instant, and a ``?v=``
version, which names one version of a versioned entity such as a file.
"""

import dataclasses
import re
import typing
import urllib.parse

from .compat import StrEnum

ROBOTO_URI_SCHEME = "roboto"

TIMESTAMP_QUERY_PARAM = "t"
"""Query parameter naming the instant a URI points at, in epoch nanoseconds."""

VERSION_QUERY_PARAM = "v"
"""Query parameter naming one version of the entity a URI points at."""


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
    """A parsed ``roboto://<type>/<id>`` reference, optionally carrying a timestamp and a version.

    ``str()`` renders it back to URI text in normalized form: the type is lowercased,
    empty path segments are dropped, and only the ``t`` and ``v`` query parameters
    survive, in that order, so ``str(RobotoUri.parse(text))`` equals ``text`` only when
    ``text`` is already normalized.

    Raises:
        ValueError: ``id`` is empty, ``timestamp_ns`` is negative, or ``version`` is below 1.
    """

    type: RobotoUriType
    id: str
    timestamp_ns: typing.Optional[int] = None
    """The instant this URI points at, in nanoseconds since the Unix epoch, written as
    the URI's ``?t=`` parameter. ``None`` when the URI names an entity and no instant.
    Only pages showing data over time act on it; the rest ignore it."""

    version: typing.Optional[int] = None
    """The version of the entity this URI points at, written as the URI's ``?v=`` parameter.
    ``None`` when the URI names the entity without pinning a version. A file link carries
    one, so it keeps resolving to the version it was made against."""

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
        """Read ``roboto://<type>/<id>``, with optional ``t=<epoch_ns>`` and ``v=<version>`` parameters, into its parts.

        Query parameters other than ``t`` and ``v`` are ignored and the entity type is matched
        case-insensitively, so a URI written by any Roboto surface parses here.

        Args:
            text: The URI to read. Anything else raises rather than returning ``None``,
                so a caller sifting arbitrary prose should locate candidates with
                :data:`ROBOTO_URI_IN_TEXT_PATTERN` first.

        Raises:
            ValueError: ``text`` is not a ``roboto://`` URI, names a type outside
                :class:`RobotoUriType`, carries no entity id or more than one path
                segment, carries a ``t`` that is not a whole number of nanoseconds, or carries a
                ``v`` that is not a whole number.
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
