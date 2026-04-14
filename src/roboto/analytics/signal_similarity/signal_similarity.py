# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import logging
import math
import typing

import tqdm.auto

from ...compat import import_optional_dependency
from ...domain.topics import Topic
from ...logging import default_logger
from .match import Match, MatchContext, Scale

if typing.TYPE_CHECKING:
    import numpy  # pants: no-infer-dep
    import numpy.typing  # pants: no-infer-dep
    import pandas  # pants: no-infer-dep


logger = default_logger()

# Query signals must be at minimum 3 values long for results to be meaningful.
MIN_QUERY_LENGTH = 3


def _resample_sequence(
    arr: numpy.typing.NDArray,
    new_length: int,
) -> numpy.typing.NDArray:
    """
    Linearly resample a 1-D array to ``new_length`` samples via :func:`numpy.interp`.

    Used to stretch or compress a query signal before similarity matching so that
    a target subsequence of a different duration can be compared against it.
    """
    np = import_optional_dependency("numpy", "analytics")
    old_idx = np.linspace(0.0, 1.0, len(arr))
    new_idx = np.linspace(0.0, 1.0, new_length)
    return np.interp(new_idx, old_idx, arr)


def _resample_df(
    df: pandas.DataFrame,
    new_length: int,
) -> pandas.DataFrame:
    """
    Linearly resample each column of ``df`` to ``new_length`` rows.

    The returned DataFrame has a default integer index; the original index is discarded
    because the time axis is being deliberately distorted.
    """
    np = import_optional_dependency("numpy", "analytics")
    pd = import_optional_dependency("pandas", "analytics")
    old_idx = np.linspace(0.0, 1.0, len(df))
    new_idx = np.linspace(0.0, 1.0, new_length)
    return pd.DataFrame({col: np.interp(new_idx, old_idx, df[col].to_numpy()) for col in df.columns})


def _suppress_overlapping_matches(
    matches: list[Match],
    overlap_threshold: float = 0.5,
) -> list[Match]:
    """
    Remove duplicate matches covering the same target region.

    Matches are processed in ascending distance order (best first). A candidate is
    suppressed if it overlaps with any already-accepted match by more than
    ``overlap_threshold`` of the shorter match's sample-index duration.

    Overlap ratio is ``intersection_length / min(len_a, len_b)``.
    """
    accepted: list[Match] = []
    for candidate in sorted(matches, key=lambda m: m.distance):
        for accepted_match in accepted:
            intersection = max(
                0,
                min(candidate.end_idx, accepted_match.end_idx) - max(candidate.start_idx, accepted_match.start_idx) + 1,
            )
            if intersection == 0:
                continue
            shorter = min(
                candidate.end_idx - candidate.start_idx + 1,
                accepted_match.end_idx - accepted_match.start_idx + 1,
            )
            if intersection / shorter > overlap_threshold:
                break
        else:
            accepted.append(candidate)
    return accepted


def _coerce_to_numeric(df: pandas.DataFrame) -> pandas.DataFrame:
    """
    Coerce the entire pandas DataFrame to float64.

    String representations of numbers (e.g., ``"1.0"``) and narrower numeric dtypes
    (e.g., float32) are converted to float64, which stumpy requires.
    Rows containing values that cannot be converted (e.g., arbitrary text strings) are
    dropped and logged at ``INFO`` level with the count of dropped rows.
    """
    pd = import_optional_dependency("pandas", "analytics")
    coerced = df.apply(pd.to_numeric, errors="coerce")
    dropped = coerced.isna().any(axis=1)
    n_dropped = int(dropped.sum())
    if n_dropped:
        logger.info(
            "Dropped %d row(s) containing non-numeric values before similarity search. "
            "This may affect match quality if the data has many non-numeric entries.",
            n_dropped,
        )
    return coerced.dropna().astype("float64")


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
    summed_distance_profile: numpy.typing.NDArray[numpy.floating] = np.zeros(len(target) - len(query) + 1)
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
    scale: typing.Optional[Scale] = None,
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
    This makes the search **amplitude-invariant** (y-axis): it matches the *shape* of the
    signal regardless of its absolute magnitude.
    For example, a query sequence of ``[1., 2., 3.]`` will perfectly match (distance == 0)
    the target ``[1000., 2000., 3000.]`` if ``normalize`` is True,
    but would have a distance of nearly 3800 if ``normalize`` is False.

    DataFrames with string-typed columns are supported as long as all values are
    convertible to numeric types (e.g., ``"1.0"``). Rows containing values that cannot
    be converted are dropped with a warning.

    **Rate-invariant (multi-scale) search**

    Pass a :py:class:`~roboto.analytics.signal_similarity.Scale` to make the search
    **rate-invariant** (x-axis / time axis): it finds the query pattern regardless of how
    quickly or slowly it unfolds in the target. For example, a robot lifting a cup in
    1 second and the same robot lifting a cup in 3 seconds would both be found with an
    appropriate ``scale``.

    See :py:class:`~roboto.analytics.signal_similarity.Scale` for details on configuring
    the scale range, step count, and spacing. Well-known presets are available as class
    attributes, e.g. ``Scale.any()``.

    The scale at which each match was found is reported in :py:attr:`~roboto.analytics.signal_similarity.Match.scale`.

    When ``scale`` is used, ``max_matches_per_topic`` is applied to the combined results
    across all scales for a given topic, keeping the best (lowest-distance) matches.

    **Distance normalisation in multi-scale mode**

    The raw z-normalised Euclidean distance produced by MASS has range ``[0, 2·√M]``, where
    ``M`` is the query length at a given scale.  Without correction this biases results toward
    smaller scales (shorter queries always produce smaller raw distances).

    When ``scale`` is used, every distance is multiplied by ``√N / √M`` before being
    stored in :py:attr:`~roboto.analytics.signal_similarity.Match.distance`, where ``N`` is
    the original needle length.  This projects all scales onto the same ``[0, 2·√N]`` range —
    identical to the single-scale range — so that distances are directly comparable across
    scales *and* consistent with single-scale results.  A ``max_distance`` threshold tuned on
    single-scale search can therefore be reused without adjustment in multi-scale search.

    Single-scale distances (``scale=None``) are unchanged.
    """
    if scale is not None:
        factors: collections.abc.Sequence[float] = scale.factors()
    else:
        factors = [1.0]

    is_multiscale = scale is not None
    matches: list[Match] = []
    needle = _coerce_to_numeric(needle)
    _, cols = needle.shape
    targets = list(haystack)

    if cols == 1:
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
            topic_data = _coerce_to_numeric(topic_data)
            target_signal = topic_data[msg_path].to_numpy()

            if logger.isEnabledFor(logging.DEBUG):
                tqdm.auto.tqdm.write(f"Searching for matches in {match_context!r}")

            topic_matches: list[Match] = []
            original_query_len = len(query_sequence)
            sqrt_original = math.sqrt(original_query_len)
            for factor in factors:
                if is_multiscale:
                    new_length = round(original_query_len * factor)
                    if new_length < MIN_QUERY_LENGTH:
                        if logger.isEnabledFor(logging.DEBUG):
                            tqdm.auto.tqdm.write(
                                f"Skipping scale {factor:.3f}x for {match_context!r}: "
                                f"resampled query length {new_length} is below minimum {MIN_QUERY_LENGTH}"
                            )
                        continue
                    if new_length > len(target_signal):
                        if logger.isEnabledFor(logging.DEBUG):
                            tqdm.auto.tqdm.write(
                                f"Skipping scale {factor:.3f}x for {match_context!r}: "
                                f"resampled query length {new_length} exceeds target length {len(target_signal)}"
                            )
                        continue
                    effective_query = _resample_sequence(query_sequence, new_length)
                else:
                    effective_query = query_sequence

                query_len = len(effective_query)
                sqrt_query = math.sqrt(query_len)
                raw_max_distance = (
                    max_distance * sqrt_query / sqrt_original
                    if is_multiscale and max_distance is not None
                    else max_distance
                )
                for match_result in _find_matches(
                    effective_query,
                    target_signal,
                    max_distance=raw_max_distance,
                    max_matches=max_matches_per_topic,
                    normalize=normalize,
                ):
                    distance = (
                        match_result.distance * sqrt_original / sqrt_query if is_multiscale else match_result.distance
                    )
                    if is_multiscale and max_distance is not None and distance > max_distance:
                        continue
                    topic_matches.append(
                        Match(
                            context=match_context,
                            end_idx=match_result.end_idx,
                            end_time=topic_data.index[match_result.end_idx],
                            distance=distance,
                            start_idx=match_result.start_idx,
                            start_time=topic_data.index[match_result.start_idx],
                            subsequence=topic_data[match_result.start_idx : match_result.end_idx + 1],
                            scale=float(factor),
                        )
                    )

            if is_multiscale:
                topic_matches = _suppress_overlapping_matches(topic_matches)

            if is_multiscale and max_matches_per_topic is not None:
                topic_matches.sort(key=lambda m: m.distance)
                topic_matches = topic_matches[:max_matches_per_topic]

            matches.extend(topic_matches)

    else:
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
            target_signal = _coerce_to_numeric(target_signal)

            if logger.isEnabledFor(logging.DEBUG):
                tqdm.auto.tqdm.write(f"Searching for matches in {match_context!r}")

            topic_matches = []
            original_needle_len = len(needle)
            sqrt_original = math.sqrt(original_needle_len)
            for factor in factors:
                if is_multiscale:
                    new_length = round(original_needle_len * factor)
                    if new_length < MIN_QUERY_LENGTH:
                        if logger.isEnabledFor(logging.DEBUG):
                            tqdm.auto.tqdm.write(
                                f"Skipping scale {factor:.3f}x for {match_context!r}: "
                                f"resampled query length {new_length} is below minimum {MIN_QUERY_LENGTH}"
                            )
                        continue
                    if new_length > len(target_signal):
                        if logger.isEnabledFor(logging.DEBUG):
                            tqdm.auto.tqdm.write(
                                f"Skipping scale {factor:.3f}x for {match_context!r}: "
                                f"resampled query length {new_length} exceeds target length {len(target_signal)}"
                            )
                        continue
                    effective_needle = _resample_df(needle, new_length)
                else:
                    effective_needle = needle

                needle_len = len(effective_needle)
                sqrt_needle = math.sqrt(needle_len)
                raw_max_distance = (
                    max_distance * sqrt_needle / sqrt_original
                    if is_multiscale and max_distance is not None
                    else max_distance
                )
                for match_result in _find_matches_multidimensional(
                    effective_needle,
                    target_signal,
                    max_distance=raw_max_distance,
                    max_matches=max_matches_per_topic,
                    normalize=normalize,
                ):
                    distance = (
                        match_result.distance * sqrt_original / sqrt_needle if is_multiscale else match_result.distance
                    )
                    if is_multiscale and max_distance is not None and distance > max_distance:
                        continue
                    topic_matches.append(
                        Match(
                            context=match_context,
                            end_idx=match_result.end_idx,
                            end_time=target_signal.index[match_result.end_idx],
                            distance=distance,
                            start_idx=match_result.start_idx,
                            start_time=target_signal.index[match_result.start_idx],
                            subsequence=target_signal[match_result.start_idx : match_result.end_idx + 1],
                            scale=float(factor),
                        )
                    )

            if is_multiscale:
                topic_matches = _suppress_overlapping_matches(topic_matches)

            if is_multiscale and max_matches_per_topic is not None:
                topic_matches.sort(key=lambda m: m.distance)
                topic_matches = topic_matches[:max_matches_per_topic]

            matches.extend(topic_matches)

    matches.sort(key=lambda match: match.distance)

    return matches
