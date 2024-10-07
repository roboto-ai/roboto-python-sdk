# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import typing

from ...domain import events
from ...http import RobotoClient

if typing.TYPE_CHECKING:
    import pandas  # pants: no-infer-dep


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

    end_time: int
    """
    The end time in the target signal of this match.
    """

    distance: float
    """
    Unitless measure of similarity between a query signal
    and the subsequence of the target signal this Match represents.
    A smaller distance relative to a larger distance indicates a "closer" match.
    """

    start_idx: int
    """
    The start index in the target signal of this match.
    """

    start_time: int
    """
    The start time in the target signal of this match.
    """

    subsequence: pandas.DataFrame
    """
    The subsequence of the target signal this Match represents.
    It is equivalent to ``target[start_idx:end_idx]``.
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
            end_time=self.end_time,
            name=name,
            metadata={
                "distance": self.distance,
                "message_paths": self.context.message_paths,
                "start_index": self.start_idx,
                "end_index": self.end_idx,
            },
            start_time=self.start_time,
            topic_ids=[self.context.topic_id],
            caller_org_id=caller_org_id,
            roboto_client=roboto_client,
        )
