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

MIN_QUERY_LENGTH = 3
"""Minimum number of rows in a query signal, below which its matches are not meaningful."""


def _resample_sequence(
    arr: numpy.typing.NDArray,
    new_length: int,
) -> numpy.typing.NDArray:
    """Resample a 1-D array to ``new_length`` evenly spaced samples by linear interpolation."""
    np = import_optional_dependency("numpy", "analytics")
    old_idx = np.linspace(0.0, 1.0, len(arr))
    new_idx = np.linspace(0.0, 1.0, new_length)
    return np.interp(new_idx, old_idx, arr)


def _resample_df(
    df: pandas.DataFrame,
    new_length: int,
) -> pandas.DataFrame:
    """Resample each column of ``df`` to ``new_length`` rows by linear interpolation.

    The result has a default integer index, because resampling changes the rows' spacing in time and the original
    timestamps no longer apply.
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
    """Drop each match that overlaps a closer kept match by more than ``overlap_threshold`` of the shorter one's rows.

    Matches are considered closest first, so of two overlapping matches the closer one is kept.
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
    """Convert every column of ``df`` to float64, which stumpy requires, dropping rows that cannot be converted.

    Numeric strings such as ``"1.0"`` and narrower numeric types such as float32 convert. A row with a missing value
    or any other string is dropped, and the number of dropped rows is logged at ``INFO``.
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
    """Span of a target signal similar to a query, by row position, with its distance.

    The SDK's own code uses it; to find similar signals, use
    :py:func:`~roboto.analytics.signal_similarity.find_similar_signals` instead.
    """

    start_idx: int
    """Position of the span's first row in the target."""

    end_idx: int
    """Position of the span's last row in the target."""

    distance: float
    """Distance between the query and the span, before any adjustment for the query's scale factor."""


def _find_matches(
    query: numpy.typing.NDArray,
    target: numpy.typing.NDArray,
    *,
    max_distance: typing.Optional[float] = None,
    max_matches: typing.Optional[int] = None,
    normalize: bool = False,
) -> collections.abc.Sequence[MatchResult]:
    """Find the spans of ``target`` similar to the 1-D ``query``, closest first.

    ``max_distance``, ``max_matches`` and ``normalize`` act as in
    :py:func:`~roboto.analytics.signal_similarity.find_similar_signals`, with ``max_matches`` counting this target only.

    Raises:
        ValueError: ``query`` has fewer than ``MIN_QUERY_LENGTH`` samples, or more samples than ``target``.
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
    """Find the spans of ``target`` similar to ``query`` over all of the query's columns, closest first.

    A span's distance is the sum of its distances to the query in each column. ``max_distance``, ``max_matches`` and
    ``normalize`` act as in :py:func:`~roboto.analytics.signal_similarity.find_similar_signals`, with ``max_matches``
    counting this target only.

    Raises:
        ValueError: ``query`` has fewer than ``MIN_QUERY_LENGTH`` rows, a column ``target`` lacks, or more rows than
            ``target``.
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

    # Sum, over the query's columns, the distance from the query to each window of the target. A target of N rows
    # and a query of M rows have N - M + 1 windows, starting at rows 0 through N - M.
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
        # The exclusion zone stumpy.match uses: after each match, skip windows that start within
        # ceil(M / STUMPY_EXCL_ZONE_DENOM) rows of it, so one region does not yield several matches.
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
    """Find the spans of topics' data whose values are similar to a query signal, closest first.

    Each topic's data is read at the message paths ``needle`` names, and rows of ``needle`` or of a topic's data with a
    missing or non-numeric value are dropped first; numeric strings such as ``"1.0"`` convert. A topic's data is
    compared with ``needle`` at every window of ``needle``'s length, and the windows closest to it are kept as matches,
    skipping any that starts within a quarter of ``needle``'s length of a closer match. With ``max_distance`` left
    ``None``, every topic searched yields at least one match, even when nothing in it resembles ``needle``. A progress
    bar over the topics is printed while the search runs.

    With ``scale``, ``needle`` is resampled to the length each scale factor gives and each topic is searched at every
    length, which finds a motion whether it happens faster or slower than in ``needle``:

    - A scale factor is skipped for a topic when the resampled ``needle`` would have fewer than 3 rows or more rows
      than the topic's data.
    - Distances are adjusted for each scale factor's length, so they compare across scale factors and with a search
      without ``scale``. :py:attr:`~roboto.analytics.signal_similarity.Match.distance` gives the adjustment.
      ``max_distance`` applies to the adjusted distances.
    - Of two matches in a topic that overlap by more than half of the shorter one's rows, only the closer one is kept.
    - :py:attr:`~roboto.analytics.signal_similarity.Match.scale` gives the scale factor of each match.

    Args:
        needle: Query signal, with one column per message path, named by its message path, and one row per sample.
            Its index is not read. With several columns, a window's distance is the sum of its distances in each
            column.
        haystack: Topics to search.
        max_distance: Largest distance a match may have. ``None`` keeps, for each topic and scale factor, the matches
            no farther than the larger of the closest match's distance and the mean distance over all windows minus
            two standard deviations.
        max_matches_per_topic: Maximum number of matches to return from each topic, keeping the closest. ``None``
            returns every match. With ``scale``, it counts the topic's matches at every scale factor together.
        normalize: Whether to rescale ``needle`` and each window of a topic's data to a mean of 0 and a standard
            deviation of 1 before comparing them, so a match has the shape of ``needle`` whatever its offset and
            amplitude. ``[1.0, 2.0, 3.0]`` matches ``[1000.0, 2000.0, 3000.0]`` at distance 0 with ``normalize=True``,
            and at a distance of about 3738 without.
        scale: Range of scale factors to resample ``needle`` by before searching. ``None`` searches with ``needle``
            as given.

    Returns:
        Matches from every topic, sorted by ascending
        :py:attr:`~roboto.analytics.signal_similarity.Match.distance`.

    Raises:
        ValueError: Without ``scale``, ``needle`` has fewer than 3 rows (``MIN_QUERY_LENGTH``) or more rows than a
            topic's data. With several columns, a topic's data lacks one of ``needle``'s message paths.
        ImportError: The ``roboto[analytics]`` extra is not installed.

    Examples:
        Search a dataset's IMU topics for two seconds of angular velocity, at any speed from a tenth to ten times
        the original:

        >>> from roboto.analytics.signal_similarity import Scale, find_similar_signals
        >>> from roboto.domain.datasets import Dataset
        >>> from roboto.domain.topics import Topic
        >>> imu = Topic.from_name_and_file(topic_name="/imu/data", file_id="fl_12345")
        >>> needle = imu.get_data_as_df(
        ...     message_paths_include=["angular_velocity"],
        ...     start_time=1_700_000_000_000_000_000,
        ...     end_time=1_700_000_002_000_000_000,
        ... )
        >>> topics = Dataset.from_id("ds_12345").get_topics(include=["/imu/data"])
        >>> matches = find_similar_signals(needle, topics, max_matches_per_topic=3, normalize=True, scale=Scale.any())
        >>> for match in matches[:5]:
        ...     print(match.context.topic_id, match.start_time, match.distance)
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
