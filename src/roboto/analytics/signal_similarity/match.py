# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import typing

from ...compat import import_optional_dependency
from ...domain import events
from ...http import RobotoClient

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep


@dataclasses.dataclass(frozen=True)
class Scale:
    """Range of time scales to search for a query at, so a motion is found whether it happens faster or slower.

    Pass it as ``scale`` to :py:func:`~roboto.analytics.signal_similarity.find_similar_signals`, which resamples the
    query to the length each scale factor gives and searches at each length. A scale factor is relative to the query's
    length: at ``2.0`` the search looks for matches twice as long as the query (the motion happened at half the speed),
    and at ``0.5`` for matches half as long (twice the speed). A robot that lifts a cup in 1 second and one that lifts
    it in 3 seconds are then both found.

    ``Scale.any()`` covers a wide range. Bounds that fit the motion, such as ``Scale(min=0.5, max=3.0)`` for one that
    can take from half to three times as long as in the query, place the scale factors closer together where matches
    are plausible and need fewer of them, so the search finds better matches with less computation.

    Raises:
        ValueError: ``min`` or ``max`` is not positive, ``min`` is greater than ``max``, or ``steps`` is less than 1.
    """

    min: float
    """Smallest scale factor to search at. Must be positive."""

    max: float
    """Largest scale factor to search at. Must be at least ``min``."""

    steps: int = 10
    """Number of scale factors to search at, from ``min`` to ``max`` inclusive. Must be at least 1."""

    spacing: typing.Literal["log", "linear"] = "log"
    """How the scale factors are spread from ``min`` to ``max``:

    * ``"log"``: with an equal ratio between adjacent factors, so 0.5, 1 and 2 are evenly spaced. This suits speed
      ratios.
    * ``"linear"``: with an equal difference between adjacent factors.
    """

    def __post_init__(self) -> None:
        if self.min <= 0 or self.max <= 0:
            raise ValueError(f"Scale min and max must be positive; got min={self.min!r}, max={self.max!r}")
        if self.min > self.max:
            raise ValueError(f"Scale min must be <= max; got min={self.min!r}, max={self.max!r}")
        if self.steps < 1:
            raise ValueError(f"Scale steps must be >= 1; got {self.steps!r}")

    @classmethod
    def any(cls) -> Scale:
        """Build a scale that searches at 30 scale factors from 0.1 to 10, log-spaced.

        It finds matches from a tenth of the query's length to ten times its length.
        """
        return cls(min=0.1, max=10.0, steps=30)

    def factors(self) -> list[float]:
        """Return the ``steps`` scale factors from ``min`` to ``max`` inclusive, spread as ``spacing`` sets.

        Raises:
            ImportError: The ``roboto[analytics]`` extra is not installed.
        """
        np = import_optional_dependency("numpy", "analytics")
        if self.spacing == "log":
            return np.geomspace(self.min, self.max, self.steps).tolist()
        return np.linspace(self.min, self.max, self.steps).tolist()


@dataclasses.dataclass(frozen=True)
class MatchContext:
    """Topic, message paths, dataset and file a match was found in.

    Carried in ``Match.context``.
    """

    message_paths: collections.abc.Sequence[str]
    """Message paths whose data was compared with the query: the query's column names."""

    topic_id: str
    """ID of the topic the match was found in."""

    topic_name: str
    """Name of the topic the match was found in."""

    dataset_id: typing.Optional[str] = None
    """ID of the dataset the topic or its file belongs to, or ``None`` if the topic belongs to neither."""

    file_id: typing.Optional[str] = None
    """ID of the file the topic belongs to, or ``None`` if the topic does not belong to a file."""


@dataclasses.dataclass(frozen=True)
class Match:
    """Consecutive messages of a topic whose data is similar to a query.

    :py:func:`~roboto.analytics.signal_similarity.find_similar_signals` returns these. ``start_idx`` and ``end_idx``
    count rows of the topic's data from 0, after rows with a missing or non-numeric value are dropped.
    """

    context: MatchContext
    """Topic, message paths, dataset and file the match was found in."""

    end_idx: int
    """Position of the match's last row in the topic's data."""

    end_time: pandas.Timestamp
    """Timestamp of the match's last message, in UTC."""

    distance: float
    """Distance between the query and the match. A smaller distance means a closer match.

    It is the Euclidean distance between the query and the match, summed over the message paths when the query has
    several. When :py:func:`~roboto.analytics.signal_similarity.find_similar_signals` is called with
    ``normalize=True``, each message path's values are first rescaled to a mean of 0 and a standard deviation of 1, so
    each message path adds at most ``2·√N``, where ``N`` is the number of rows in the query.

    When it is called with ``scale``, the query is resampled to ``M`` rows at each scale factor, and the distance is
    multiplied by ``√N / √M``. This makes distances at different scale factors comparable with each other and with a
    search without ``scale``, so a ``max_distance`` chosen for one kind of search works unchanged for the other.
    """

    start_idx: int
    """Position of the match's first row in the topic's data."""

    start_time: pandas.Timestamp
    """Timestamp of the match's first message, in UTC."""

    subsequence: pandas.DataFrame
    """Rows of the topic's data from ``start_idx`` through ``end_idx`` inclusive, one column per message path.

    It is indexed by message timestamp, in UTC.
    """

    scale: float = 1.0
    """Scale factor at which the match was found, relative to the query's length.

    At ``1.0`` the match has as many rows as the query. Above ``1.0`` it has proportionally more (the motion happened
    more slowly than in the query), and below ``1.0`` proportionally fewer (more quickly). Always ``1.0`` when
    :py:func:`~roboto.analytics.signal_similarity.find_similar_signals` is called without ``scale``.
    """

    def to_event(
        self,
        name: str = "Signal Similarity Match Result",
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> events.Event:
        """Create an event on the match's topic that spans the match's first to last message.

        The event's description is ``"Match score: <distance>"``, and its metadata holds ``distance``,
        ``message_paths``, ``start_index``, ``end_index`` and ``scale``. Reading the event's data leaves out the
        match's last message, because a read of an event's data excludes its end time.

        Args:
            name: Human-readable name of the event.
            caller_org_id: Organization to create the event in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new event.

        Raises:
            RobotoInvalidRequestException: The match's topic no longer exists, or belongs to an organization other
                than the one the event is created in.
        """
        return events.Event.create(
            description=f"Match score: {self.distance}",
            end_time=self.end_time.as_unit("ns").value,
            name=name,
            metadata={
                "distance": self.distance,
                "message_paths": self.context.message_paths,
                "start_index": self.start_idx,
                "end_index": self.end_idx,
                "scale": self.scale,
            },
            start_time=self.start_time.as_unit("ns").value,
            topic_ids=[self.context.topic_id],
            caller_org_id=caller_org_id,
            roboto_client=roboto_client,
        )
