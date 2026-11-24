# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import time
import typing

import pydantic

from roboto.exceptions import (
    RobotoFailedToGenerateException,
)

from ..compat import StrEnum


class AISummaryStatus(StrEnum):
    """Status of an AI summary's generation: whether Roboto is still writing it, finished, or failed."""

    Pending = "pending"
    """Roboto is still generating the summary; its text may be empty or partial."""

    Complete = "complete"
    """Roboto finished generating the summary, or a user set its text."""

    Failed = "failed"
    """Generation failed; the text is whatever Roboto wrote before the failure, which may be empty."""


class AISummary(pydantic.BaseModel):
    """Data record of an AI summary of a dataset or a session, as the Roboto API returns it.

    An AI summary is a description of a dataset or a session that Roboto's AI writes, or that a user sets with
    :py:meth:`~roboto.domain.datasets.Dataset.set_summary`. A dataset or session has at most one, which each new
    generation or ``set_summary`` call replaces; starting a generation clears its text.
    ``StreamingAISummary`` holds this record as its ``current`` snapshot.
    """

    text: str
    """Text of the summary, rendered as Markdown. Empty or partial while ``status`` is ``Pending``."""

    created: datetime.datetime
    """Time the summary was last written: when its generation started, completed or failed, or when a user set it."""

    status: AISummaryStatus
    """Status of the summary's generation."""

    summary_id: str
    """Unique ID of the summary, beginning with ``sm_``. It stays the same when the summary is regenerated or set."""


class StreamingAISummary(typing.Protocol):
    """Interface to an AI summary that Roboto may still be generating, read as snapshots or as streamed text.

    :py:meth:`~roboto.domain.datasets.Dataset.generate_summary` and
    :py:meth:`~roboto.domain.datasets.Dataset.get_summary` return one, as do the methods of the same names on
    :py:class:`~roboto.experimental.sessions.Session`. ``current`` returns the latest snapshot without waiting;
    ``complete_text``, ``await_completion`` and ``text_stream`` fetch the summary from Roboto until its generation
    finishes.
    """

    @property
    def complete_text(self) -> str:
        """Full text of the summary, once Roboto finishes generating it.

        Reading it waits, with no time limit, until generation finishes, and raises
        :py:class:`~roboto.exceptions.RobotoFailedToGenerateException` if a fetch finds that generation failed. To
        wait with a time limit, call ``await_completion``.
        """

    @property
    def current(self) -> typing.Optional[AISummary]:
        """Latest snapshot of the summary, or ``None`` if none has been fetched yet.

        Reading it neither waits nor fetches; ``await_completion`` and ``text_stream`` update it as they fetch.
        """
        ...

    def await_completion(self, timeout_s: typing.Optional[float] = None, poll_interval_s: float = 2) -> AISummary:
        """Wait until Roboto finishes generating the summary, and return it.

        Returns at once, without fetching, if the summary is already complete or failed; a summary that had already
        failed is returned, not raised.

        Args:
            timeout_s: Maximum time to wait, in seconds. It is checked after each fetch, so the wait can run past it
                by about one poll interval. ``None`` waits with no limit.
            poll_interval_s: Time to wait between fetches of the summary, in seconds.

        Raises:
            RobotoFailedToGenerateException: A fetch finds that generation of the summary failed.
            TimeoutError: The summary is still not complete after ``timeout_s`` seconds.
        """
        ...

    def text_stream(
        self, timeout_s: typing.Optional[float] = None, poll_interval_s: float = 2
    ) -> typing.Generator[str, None, None]:
        """Yield the summary's text as Roboto generates it.

        The first chunk is all the text fetched so far. Each later chunk is the text added since the previous
        fetch, and is empty when nothing was added. Each call starts again from the beginning of the text. If the
        summary is already complete or failed, the generator yields its whole text once, without fetching or raising.

        Args:
            timeout_s: Maximum time to wait for generation to finish, in seconds. It is checked after each fetch, so
                the wait can run past it by about one poll interval. ``None`` waits with no limit.
            poll_interval_s: Time to wait between fetches of the summary, in seconds.

        Yields:
            Chunks of the summary's text, which together make up the full text.

        Raises:
            RobotoFailedToGenerateException: A fetch finds that generation of the summary failed. It surfaces during
                iteration, when that fetch returns.
            TimeoutError: The summary is still not complete after ``timeout_s`` seconds. It surfaces during
                iteration, when the first fetch to return after ``timeout_s`` seconds finds the summary still pending.
        """
        ...


class PollingStreamingAISummary(StreamingAISummary):
    """Streaming AI summary that fetches the summary from Roboto at a fixed interval until its generation finishes.

    The SDK's own code uses it; to generate or fetch a summary, use
    :py:meth:`~roboto.domain.datasets.Dataset.generate_summary` or
    :py:meth:`~roboto.domain.datasets.Dataset.get_summary` instead.

    Args:
        poll_fn: Function that fetches the summary's current state from Roboto. ``text_stream`` assumes each call's
            text begins with the previous call's text, and yields only the characters past it.
        poll_on_init: Whether to fetch the summary when the object is built. If ``False``, the first fetch happens
            in ``await_completion`` or ``text_stream``.
        initial_summary: Snapshot to start from, which a fetch on build replaces. With neither a snapshot nor a
            fetch on build, ``current`` is ``None`` and ``await_completion`` raises
            :py:class:`~roboto.exceptions.RobotoFailedToGenerateException`.
    """

    def __init__(
        self,
        poll_fn: typing.Callable[[], AISummary],
        poll_on_init: bool = True,
        initial_summary: typing.Optional[AISummary] = None,
    ):
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

    def await_completion(self, timeout_s: typing.Optional[float] = None, poll_interval_s: float = 2) -> AISummary:
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

        while self.__summary is not None and self.__summary.status == AISummaryStatus.Pending:
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
