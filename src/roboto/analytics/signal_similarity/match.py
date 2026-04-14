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
    """
    Configuration for rate-invariant (multi-scale) signal similarity search.

    Searching across multiple scales finds a query pattern regardless of how quickly or
    slowly it unfolds in the target. For example, a robot lifting a cup in 1 second and
    the same robot lifting a cup in 3 seconds would both be found.

    ``min`` and ``max`` are positive scale factors relative to the original query length.
    A scale of ``1.0`` corresponds to the original query length; ``2.0`` searches for
    target subsequences twice as long (action happened at half speed); ``0.5`` searches
    for subsequences half as long (action happened at double speed).

    While ``Scale.any()`` provides a convenient wide-range preset, providing
    domain-informed bounds (e.g. ``Scale(min=0.5, max=3.0)`` for a motion that can
    happen between half and triple speed) will both improve match quality — by
    concentrating the search grid where matches are physically plausible — and
    reduce compute by avoiding unnecessary scale steps.
    """

    min: float
    """Minimum scale factor (must be positive)."""

    max: float
    """Maximum scale factor (must be >= ``min``)."""

    steps: int = 10
    """Number of scale values to sample across the range."""

    spacing: typing.Literal["log", "linear"] = "log"
    """
    How to distribute scale values across the range.

    * ``"log"`` (default) — geometrically spaced; equal ratio between adjacent steps,
      which is more natural for speed ratios (e.g. 0.5x, 1x, 2x are equally spaced on a log scale).
    * ``"linear"`` — linearly spaced.
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
        """Well-known preset covering a wide range of speed ratios (0.1x to 10x)."""
        return cls(min=0.1, max=10.0, steps=30)

    def factors(self) -> list[float]:
        """Return a list of scale factors spanning the configured range."""
        np = import_optional_dependency("numpy", "analytics")
        if self.spacing == "log":
            return np.geomspace(self.min, self.max, self.steps).tolist()
        return np.linspace(self.min, self.max, self.steps).tolist()


@dataclasses.dataclass(frozen=True)
class MatchContext:
    """
    Correlate a matched subsequence back to its source.
    """

    message_paths: collections.abc.Sequence[str]
    topic_id: str
    topic_name: str

    dataset_id: typing.Optional[str] = None
    file_id: typing.Optional[str] = None


@dataclasses.dataclass(frozen=True)
class Match:
    """
    A subsequence of a target signal that is similar to a query signal.
    """

    context: MatchContext
    """
    Correlate a matched subsequence back to its source.
    """

    end_idx: int
    """
    The end index in the target signal of this match.
    """

    end_time: pandas.Timestamp
    """
    The end time in the target signal of this match.
    """

    distance: float
    """
    Measure of similarity between a query signal and the subsequence of the target signal
    this Match represents. A smaller distance indicates a closer match.

    In single-scale search (``scale=None``) this is the raw z-normalised Euclidean
    distance produced by MASS, with range ``[0, 2·√N]`` where ``N`` is the query length.

    In multi-scale search (``scale`` provided) this is multiplied by ``√N / √M``
    (where ``N`` is the original needle length and ``M`` is the resampled length at that
    scale step), projecting onto the same ``[0, 2·√N]`` range as single-scale search.
    This means a ``max_distance`` threshold calibrated on single-scale search transfers
    directly to multi-scale search without adjustment.
    """

    start_idx: int
    """
    The start index in the target signal of this match.
    """

    start_time: pandas.Timestamp
    """
    The start time in the target signal of this match.
    """

    subsequence: pandas.DataFrame
    """
    The subsequence of the target signal this Match represents.
    It is equivalent to ``target[start_idx:end_idx]``.
    """

    scale: float = 1.0
    """
    The time-scale factor at which this match was found.

    A value of ``1.0`` means the matched subsequence has the same length as the query.
    Values greater than ``1.0`` mean the matched subsequence is proportionally longer
    (the action occurred more slowly in the target than in the query).
    Values less than ``1.0`` mean the matched subsequence is proportionally shorter
    (the action occurred more quickly).

    This field is only meaningful when ``scale`` is passed to
    :py:func:`~roboto.analytics.signal_similarity.find_similar_signals`.
    """

    def to_event(
        self,
        name: str = "Signal Similarity Match Result",
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> events.Event:
        """
        Create a Roboto Platform event out of this similarity match result.
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
