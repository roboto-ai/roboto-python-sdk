# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum
import time
import typing

import pydantic

from roboto.exceptions import (
    RobotoFailedToGenerateException,
)


class AISummaryStatus(str, enum.Enum):
    """
    Status of an AI summary.
    """

    Pending = "pending"
    """The summary is being generated. Its text may be the empty string, or may be a partial result. If
    you continually poll for the summary while it is in the pending state, you will eventually get the
    complete summary."""

    Complete = "complete"
    """The summary has been generated."""

    Failed = "failed"
    """The summary failed to generate."""


class AISummary(pydantic.BaseModel):
    """
    A wire-transmissible representation of an AI summary
    """

    text: str
    """The text of the summary."""

    created: datetime.datetime
    """The time at which the summary was created."""

    status: AISummaryStatus
    """The status of the summary."""

    summary_id: str
    """The ID of the summary."""


class StreamingAISummary(typing.Protocol):
    """
    A streaming interface for an AI summary.

    Roboto AI summaries are typically generated asynchronously, and can be viewed as either a point-in-time
    partially (or fully) complete snapshot, or as a stream of characters. This class provides a single interface
    for accessing the summary in both ways.
    """

    @property
    def complete_text(self) -> str:
        """The complete text of the summary.

        This method will block until the summary is complete.

        Raises:
            RobotoFailedToGenerateException: If the summary fails to generate,
        """

    @property
    def current(self) -> typing.Optional[AISummary]:
        """The current state of the summary.

        This may be None if no summary has been generated yet.
        """
        ...

    def await_completion(
        self, timeout_s: typing.Optional[float] = None, poll_interval_s: float = 2
    ) -> AISummary:
        """Wait for the summary to complete.

        This will return instantly if the summary is already complete.

        Args:
            timeout_s: Optional timeout, in seconds, to wait for the summary to complete.
            poll_interval_s: Polling interval, in seconds, to use when waiting for the summary.

        Returns:
            The completed summary.

        Raises:
            RobotoFailedToGenerateException: If the summary fails to generate.
            TimeoutError: If the timeout is reached before the summary completes.
        """
        ...

    def text_stream(
        self, timeout_s: typing.Optional[float] = None, poll_interval_s: float = 2
    ) -> typing.Generator[str, None, None]:
        """Stream the text of the summary as it is generated.

        This will yield the entire summary instantly if the summary is already complete. If the summary is not
        complete, this will yield the text as it is generated.

        Args:
            timeout_s: Optional timeout, in seconds, to wait for the summary to complete.
            poll_interval_s: Polling interval, in seconds, to use when waiting for the summary.

        Yields:
            The text of the summary as it is generated.

        Raises:
            RobotoFailedToGenerateException: If the summary fails to generate.
            TimeoutError: If the timeout is reached before the summary completes.
        """
        ...


class PollingStreamingAISummary(StreamingAISummary):
    """
    An implementation of StreamingAISummary which polls for updates.
    """

    def __init__(
        self,
        poll_fn: typing.Callable[[], AISummary],
        poll_on_init: bool = True,
        initial_summary: typing.Optional[AISummary] = None,
    ):
        """Initialize a streaming AI summary.

        Args:
            poll_fn: Function to call for retrieving the latest summary state.
                Should return an :py:class:`AISummary` object with current status and text.
            poll_on_init: Whether to immediately poll for the latest summary upon
                initialization. If False, polling only occurs when methods like
                :py:meth:`text_stream` or :py:meth:`await_completion` are called.
                Defaults to True.
            initial_summary: Optional initial summary state. If provided, this
                summary will be used as the starting point instead of polling immediately.
        """
        self.__poll_fn: typing.Callable[[], AISummary] = poll_fn
        self.__summary: typing.Optional[AISummary] = initial_summary

        if poll_on_init:
            self.__summary = self.__poll_fn()

    @property
    def complete_text(self) -> str:
        return self.await_completion().text

    @property
    def current(self) -> typing.Optional[AISummary]:
        return self.__summary

    def await_completion(
        self, timeout_s: typing.Optional[float] = None, poll_interval_s: float = 2
    ) -> AISummary:
        for _ in self.text_stream(timeout_s, poll_interval_s):
            pass

        if self.__summary is None:
            raise RobotoFailedToGenerateException("Failed to generate summary")

        return self.__summary

    def text_stream(
        self, timeout_s: typing.Optional[float] = None, poll_interval_s: float = 2
    ) -> typing.Generator[str, None, None]:
        chars_streamed_so_far = 0

        if self.__summary:
            yield self.__summary.text
            chars_streamed_so_far = len(self.__summary.text)

            if self.__summary.status == AISummaryStatus.Complete:
                return

        start_time = time.perf_counter()

        while (
            self.__summary is not None
            and self.__summary.status == AISummaryStatus.Pending
        ):
            self.__summary = self.__poll_fn()

            if self.__summary.status == AISummaryStatus.Failed:
                raise RobotoFailedToGenerateException("Failed to generate summary")

            yield self.__summary.text[chars_streamed_so_far:]
            chars_streamed_so_far = len(self.__summary.text)

            if self.__summary.status == AISummaryStatus.Complete:
                break

            elapsed = time.perf_counter() - start_time

            if timeout_s is not None and elapsed > timeout_s:
                raise TimeoutError("Timed out waiting for summary")

            time.sleep(poll_interval_s)
