# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import logging
import typing

import tqdm.auto

from ...compat import import_optional_dependency
from ...domain.topics import Topic
from ...logging import default_logger
from .match import Match, MatchContext

if typing.TYPE_CHECKING:
    import numpy  # pants: no-infer-dep
    import numpy.typing  # pants: no-infer-dep
    import pandas  # pants: no-infer-dep


logger = default_logger()

# Query signals must be at minimum 3 values long for results to be meaningful.
MIN_QUERY_LENGTH = 3


class MatchResult(typing.NamedTuple):
    start_idx: int
    end_idx: int
    distance: float


def _find_matches(
    query: numpy.typing.NDArray,
    target: numpy.typing.NDArray,
    *,
    max_distance: typing.Optional[float] = None,
    max_matches: typing.Optional[int] = None,
    normalize: bool = False,
) -> collections.abc.Sequence[MatchResult]:
    """
    For performing signal similarity, see :py:func:`~roboto.analytics.signal_similarity.find_similar_signals`.
    """
    stumpy = import_optional_dependency("stumpy", "analytics")

    if len(query) < MIN_QUERY_LENGTH:
        raise ValueError(
            f"Query sequence must be greater than {MIN_QUERY_LENGTH} for results to be meaningful. "
            f"Received sequence of length {len(query)}."
        )

    if len(query) > len(target):
        raise ValueError("Query sequence must be shorter than target")

    matches: list[MatchResult] = []
    for distance, start_idx in stumpy.match(
        query,
        target,
        max_distance=max_distance,
        max_matches=max_matches,
        normalize=normalize,
    ):
        end_idx = start_idx + len(query) - 1
        matches.append(
            MatchResult(
                start_idx=int(start_idx),
                end_idx=int(end_idx),
                distance=float(distance),
            )
        )

    return matches


def _find_matches_multidimensional(
    query: pandas.DataFrame,
    target: pandas.DataFrame,
    *,
    max_distance: typing.Optional[float] = None,
    max_matches: typing.Optional[int] = None,
    normalize: bool = False,
) -> collections.abc.Sequence[MatchResult]:
    """
    For performing signal similarity, see :py:func:`~roboto.analytics.signal_similarity.find_similar_signals`.
    """
    np = import_optional_dependency("numpy", "analytics")
    stumpy = import_optional_dependency("stumpy", "analytics")

    if len(query) < MIN_QUERY_LENGTH:
        raise ValueError(
            f"Query signal must be greater than {MIN_QUERY_LENGTH} for results to be meaningful. "
            f"Received DataFrame of size {query.shape}."
        )

    query_dims = set(query.columns.tolist())
    target_dims = set(target.columns.tolist())
    non_overlap = query_dims.difference(target_dims)
    if len(non_overlap):
        raise ValueError(
            "Cannot match query against target: they have non-overlapping dimensions. "
            f"Target signal is missing the following attributes: {non_overlap}"
        )

    # Accumulate summed distances for each subsequence (of length `query_signal`) within the target.
    # The distance for each subsequence starts at 0 and is incrementally updated.
    # Each dimension of the query signal (i.e., column in dataframe) is considered in turn:
    # for each dimension, compute the distance profile against the corresponding dimension in the target signal,
    # and then add that distance profile to the running total.
    # N.b.: for a target of len N and query of len M, there are a total of N - M + 1 subsequences
    #   (the first starts at index 0, the second at index 1, ..., the last starts at index N - M)
    summed_distance_profile: numpy.typing.NDArray[numpy.floating] = np.zeros(
        len(target) - len(query) + 1
    )
    for column in query_dims:
        query_sequence = query[column].to_numpy()
        target_sequence = target[column].to_numpy()
        distance_profile: numpy.typing.NDArray[numpy.floating] = stumpy.mass(
            query_sequence, target_sequence, normalize=normalize
        )
        summed_distance_profile += distance_profile

    matches: list[MatchResult] = []
    for distance, start_idx in stumpy.core._find_matches(
        summed_distance_profile,
        # https://github.com/TDAmeritrade/stumpy/blob/b7b355ce4a9450357ad207dd4f04fc8e8b4db100/stumpy/motifs.py#L533C17-L533C64
        excl_zone=int(np.ceil(len(query) / stumpy.core.config.STUMPY_EXCL_ZONE_DENOM)),
        max_distance=max_distance,
        max_matches=max_matches,
    ):
        end_idx = start_idx + len(query) - 1
        matches.append(
            MatchResult(
                start_idx=int(start_idx),
                end_idx=int(end_idx),
                distance=float(distance),
            )
        )

    return matches


def find_similar_signals(
    needle: pandas.DataFrame,
    haystack: collections.abc.Iterable[Topic],
    *,
    max_distance: typing.Optional[float] = None,
    max_matches_per_topic: typing.Optional[int] = None,
    normalize: bool = False,
) -> collections.abc.Sequence[Match]:
    """
    Find subsequences of topic data (from ``haystack``) that are similar to ``needle``.

    If ``needle`` is a dataframe with a single, non-index column,
    single-dimensional similarity search will be performed.
    If it instead has multiple non-index columns, multi-dimensional search will be performed.

    Even if there is no true similarity between the query signal and a topic's data,
    this will always return at least one :py:class:`~roboto.analytics.signal_similarity.Match`.
    Matches are expected to improve in quality as the topic data is more relevant to the query.
    Matches are returned sorted in ascending order by their distance, with the best matches (lowest distance) first.

    If ``max_distance`` is provided, only matches with a distance less than ``max_distance`` will be returned.
    Given distances computed against all comparison windows in the target, this defaults to the maximum of:
        1. the minimum distance
        2. the mean distance minus two standard deviations

    Use ``max_matches_per_topic`` to limit the number of match results contributed by a single topic.

    If ``normalize`` is True, values will be projected to the unit scale before matching.
    This is useful if you want to match windows of the target signal regardless of scale.
    For example, a query sequence of ``[1., 2., 3.]`` will perfectly match (distance == 0)
    the target ``[1000., 2000., 3000.]`` if ``normalize`` is True,
    but would have a distance of nearly 3800 if ``normalize`` is False.
    """
    matches: list[Match] = []
    _, cols = needle.shape

    targets = list(haystack)

    if cols == 1:
        # Single dimensional similarity search
        msg_path = needle.columns[0]
        query_sequence = needle[msg_path].to_numpy()
        for topic in tqdm.auto.tqdm(targets):
            match_context = MatchContext(
                dataset_id=topic.dataset_id,
                file_id=topic.file_id,
                message_paths=[msg_path],
                topic_name=topic.name,
                topic_id=topic.topic_id,
            )

            if logger.isEnabledFor(logging.DEBUG):
                tqdm.auto.tqdm.write(f"Loading data from {match_context!r}")

            topic_data = topic.get_data_as_df(message_paths_include=[msg_path])

            if logger.isEnabledFor(logging.DEBUG):
                tqdm.auto.tqdm.write(f"Searching for matches in {match_context!r}")

            target_signal = topic_data[msg_path].to_numpy()
            for match_result in _find_matches(
                query_sequence,
                target_signal,
                max_distance=max_distance,
                max_matches=max_matches_per_topic,
                normalize=normalize,
            ):
                matches.append(
                    Match(
                        context=match_context,
                        end_idx=match_result.end_idx,
                        end_time=topic_data.index[match_result.end_idx].item(),
                        distance=match_result.distance,
                        start_idx=match_result.start_idx,
                        start_time=topic_data.index[match_result.start_idx].item(),
                        subsequence=topic_data[
                            match_result.start_idx : match_result.end_idx + 1
                        ],
                    )
                )
    else:
        # Multi-dimensional match
        message_paths = needle.columns.tolist()

        for topic in tqdm.auto.tqdm(targets):
            match_context = MatchContext(
                dataset_id=topic.dataset_id,
                file_id=topic.file_id,
                message_paths=message_paths,
                topic_name=topic.name,
                topic_id=topic.topic_id,
            )

            if logger.isEnabledFor(logging.DEBUG):
                tqdm.auto.tqdm.write(f"Loading data from {match_context!r}")

            target_signal = topic.get_data_as_df(message_paths_include=message_paths)

            if logger.isEnabledFor(logging.DEBUG):
                tqdm.auto.tqdm.write(f"Searching for matches in {match_context!r}")

            for match_result in _find_matches_multidimensional(
                needle,
                target_signal,
                max_distance=max_distance,
                max_matches=max_matches_per_topic,
                normalize=normalize,
            ):
                matches.append(
                    Match(
                        context=match_context,
                        end_idx=match_result.end_idx,
                        end_time=target_signal.index[match_result.end_idx].item(),
                        distance=match_result.distance,
                        start_idx=match_result.start_idx,
                        start_time=target_signal.index[match_result.start_idx].item(),
                        subsequence=target_signal[
                            match_result.start_idx : match_result.end_idx + 1
                        ],
                    )
                )

    matches.sort(key=lambda match: match.distance)

    return matches
