# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import typing

from ...compat import import_optional_dependency
from .match import Match

if typing.TYPE_CHECKING:
    import numpy.typing  # pants: no-infer-dep


class QuerySignal:
    """
    A sequence of values to match against other signals, looking for similar subsequences.

    Query signals must be at minimum 3 values long for results to be meaningful.
    """

    MIN_QUERY_LENGTH: typing.ClassVar = 3

    __query: numpy.typing.NDArray

    @staticmethod
    def from_array(sequence: numpy.typing.NDArray) -> "QuerySignal":
        if len(sequence) < QuerySignal.MIN_QUERY_LENGTH:
            raise ValueError("Query signal must be at least 3 values long")

        return QuerySignal(sequence)

    def __init__(self, query: numpy.typing.NDArray):
        self.__query = query

    def match(
        self,
        target: numpy.typing.NDArray,
        *,
        max_distance: typing.Optional[float] = None,
        max_matches: typing.Optional[int] = None,
        normalize: bool = False,
    ) -> list[Match]:
        """
        Find at least one subsequence of the target signal that is similar to the query signal.
        Even if there is no true similarity between the query and target,
        this will always return at least one :class:`~roboto.query.signal_similarity.Match`.
        Matches are expected to improve in quality as the target is more relevant to the query.
        Matches are returned sorted in ascending order by their distance, with the best matches (lowest distance) first.

        If ``max_distance`` is provided, only matches with a distance less than ``max_distance`` will be returned.
        Defaults to--given distances computed against all comparison windows in the target signal--the maximum of:
            1. the minimum distance
            2. the mean distance minus two standard deviations

        If ``max_matches`` is provided, only the top ``max_matches`` matches will be returned.

        If ``normalize`` is True, values will be projected to the unit scale before matching.
        This is useful if you want to match windows of the target signal regardless of scale.
        For example, a query signal of ``[1., 2., 3.]`` will perfectly match (distance == 0)
        the target ``[1000., 2000., 3000.]`` if ``normalize`` is True,
        but would have a distance of nearly 3800 if ``normalize`` is False.
        """
        if len(self.__query) > len(target):
            raise ValueError("Query signal must be shorter than target signal")

        matches: list[Match] = []
        stumpy = import_optional_dependency("stumpy", "analytics")
        for distance, start_idx in stumpy.match(
            self.__query,
            target,
            max_distance=max_distance,
            max_matches=max_matches,
            normalize=normalize,
        ):
            end_idx = start_idx + len(self.__query)
            matches.append(
                Match(
                    start_idx=start_idx,
                    end_idx=end_idx,
                    distance=distance,
                    subsequence=target[start_idx:end_idx],
                )
            )

        return matches

    def match_all(
        self,
        targets: collections.abc.Iterable[numpy.typing.NDArray],
        *,
        max_distance: typing.Optional[float] = None,
        max_matches: typing.Optional[int] = None,
        normalize: bool = False,
    ) -> list[Match]:
        """
        Find at least one subsequence within the collection of targets that is similar to the query signal.
        See :meth:`~roboto.query.signal_similarity.QuerySignal.match` for more details.
        """
        matches: list[Match] = []
        for target in targets:
            matches.extend(
                self.match(
                    target,
                    max_distance=max_distance,
                    max_matches=max_matches,
                    normalize=normalize,
                )
            )

        matches.sort(key=lambda match: match.distance)

        if max_matches is not None:
            return matches[:max_matches]

        return matches
