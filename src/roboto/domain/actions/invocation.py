# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

from ...http import RobotoClient, StreamedList
from ...query import QuerySpecification
from ...waiters import Interval, wait_for
from .action_record import (
    ComputeRequirements,
    ContainerParameters,
)
from .invocation_operations import (
    SetContainerInfoRequest,
    SetLogsLocationRequest,
    UpdateInvocationStatus,
)
from .invocation_record import (
    ActionProvenance,
    ExecutableProvenance,
    InvocationDataSource,
    InvocationInput,
    InvocationRecord,
    InvocationStatus,
    InvocationStatusRecord,
    InvocationUploadDestination,
    LogRecord,
    LogsLocation,
    SourceProvenance,
)

_QUERYABLE_NON_RECORD_FIELDS = frozenset({"data_source_id", "data_source_type", "input.session_id"})
"""Condition fields the invocations query API accepts that are not invocation record attributes.

None of them is an attribute of :py:class:`~roboto.domain.actions.InvocationRecord`. The API matches each
by its full name.

:py:class:`~roboto.domain.actions.InvocationRecord` nests the data source under ``data_source``, but
the API accepts it only in the flat form: it refuses a condition on ``data_source`` or on
``data_source.data_source_id``. ``data_source_id`` matches an invocation's recorded data source,
which is set only when its invoker names one. ``data_source_type`` matches every invocation for as
long as :py:class:`~roboto.domain.actions.InvocationDataSourceType` has a single member.

``input.session_id`` takes only ``Comparator.Equals`` and matches the invocations whose input names that
session by ID. It does not match an input that selected sessions by query or by name.
"""


class Invocation:
    """An invocation: one run of an action, started by a user or by a trigger.

    An invocation records the inputs, parameter values, compute requirements, and container parameters it ran with,
    the history of statuses it entered, and the log lines its containers wrote.

    Invocations are started by :py:meth:`~roboto.domain.actions.Action.invoke`, by a trigger, or in the Roboto web
    app. Get an ``Invocation`` from ``from_id`` or ``query``. Each instance holds a copy of the invocation's record,
    so its status does not change as the invocation runs: ``refresh`` fetches the latest record, and
    ``wait_for_terminal_status`` polls until the invocation ends.
    """

    __record: InvocationRecord
    __roboto_client: RobotoClient

    @classmethod
    def from_id(
        cls,
        invocation_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Invocation":
        """Fetch an invocation by its ID.

        Reading an invocation takes permission to read every dataset it was given: its data source, each dataset its
        input selectors name, the dataset of each file and topic it selects by ID, and each dataset that holds a file
        of a session it selects by ID. An invocation given no dataset takes only permission to read the invocation.
        The invocation's own credential, which its action uses, can always read it.

        Args:
            invocation_id: ID of the invocation, beginning with ``iv_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No invocation has this ID.
            RobotoUnauthorizedException: The caller may not read a dataset the invocation was given, such as one
                restricted to the people it is shared with.

        Examples:
            Load an invocation and check its status:

            >>> invocation = Invocation.from_id("iv_12345")
            >>> print(f"Status: {invocation.current_status}")
            >>> print(f"Created: {invocation.created}")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        response = roboto_client.get(f"v1/actions/invocations/{invocation_id}")
        record = response.to_record(InvocationRecord)
        return cls(record, roboto_client)

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Invocation", None, None]:
        """Yield the invocations in an organization that match a query, fetching them a page at a time.

        Conditions and sorts name fields of :py:class:`~roboto.domain.actions.InvocationRecord`, such as
        ``last_status`` or ``created``, or one of ``data_source_id``, ``data_source_type``, and ``input.session_id``.

        Args:
            spec: Conditions and sort order of the query. ``None`` matches every invocation in the organization.
            owner_org_id: Organization to query invocations in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            ValueError: ``spec`` names a field that is neither a field of ``InvocationRecord`` nor one of
                ``data_source_id``, ``data_source_type``, and ``input.session_id``. Of a dotted field such as
                ``provenance.action``, only the part before the first dot is checked. It surfaces on the first
                iteration.
            RobotoIllegalArgumentException: The query filters or sorts on a field Roboto does not accept for
                invocations, filters ``last_status`` on a value that is neither a whole number nor a status name, or
                compares ``last_status`` with :py:attr:`~roboto.query.Comparator.Like`, ``NotLike``, ``Contains``,
                ``NotContains`` or ``BeginsWith``. It surfaces on the first iteration.

        Examples:
            Query all invocations:

            >>> for invocation in Invocation.query():
            ...     print(f"Invocation: {invocation.id}")

            Query invocations whose data source is a given dataset:

            >>> from roboto.query import Comparator, Condition, QuerySpecification
            >>> spec = QuerySpecification(
            ...     condition=Condition(
            ...         field="data_source_id",
            ...         comparator=Comparator.Equals,
            ...         value="ds_12345",
            ...     )
            ... )
            >>> for invocation in Invocation.query(spec):
            ...     print(invocation.id)

            Query invocations whose input names a session by ID:

            >>> spec = QuerySpecification(
            ...     condition=Condition(
            ...         field="input.session_id",
            ...         comparator=Comparator.Equals,
            ...         value="se_12345",
            ...     )
            ... )
            >>> on_session = list(Invocation.query(spec))

            Query completed invocations. ``last_status`` also accepts the status name in any
            case, so ``value="completed"`` finds the same invocations. Greater-than and
            less-than comparators compare status numbers, so
            :py:attr:`~roboto.domain.actions.InvocationStatus.Cancelled` (997), ``Failed`` (998) and
            ``Deadly`` (999) count as greater than ``Completed`` (5):

            >>> from roboto.domain.actions import InvocationStatus
            >>> spec = QuerySpecification(
            ...     condition=Condition(
            ...         field="last_status",
            ...         comparator=Comparator.Equals,
            ...         value=InvocationStatus.Completed.value,
            ...     )
            ... )
            >>> completed = list(Invocation.query(spec))

            Query the ten most recent invocations. Neither ``limit`` nor ``max_results`` caps an
            invocation query, so take the first ten from the generator:

            >>> import itertools
            >>> from roboto.query import SortDirection
            >>> spec = QuerySpecification(sort_by="created", sort_direction=SortDirection.Descending)
            >>> recent = list(itertools.islice(Invocation.query(spec), 10))
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec or QuerySpecification()

        known = set(InvocationRecord.model_fields.keys()) | _QUERYABLE_NON_RECORD_FIELDS
        actual = set()
        for field in spec.fields():
            if field in _QUERYABLE_NON_RECORD_FIELDS:
                continue
            # A dotted field such as "provenance.action.name" is known when its first part is.
            if "." in field:
                actual.add(field.split(".")[0])
            else:
                actual.add(field)
        unknown = actual - known
        if unknown:
            plural = len(unknown) > 1
            msg = "are not known attributes of Invocation" if plural else "is not a known attribute of Invocation"
            raise ValueError(f"{unknown} {msg}. Known attributes: {known}")

        while True:
            response = roboto_client.post(
                "v1/actions/invocations/query",
                data=spec,
                owner_org_id=owner_org_id,
            )

            paginated_results = response.to_paginated_list(InvocationRecord)
            for record in paginated_results.items:
                yield cls(record, roboto_client)
            if paginated_results.next_token:
                spec.after = paginated_results.next_token
            else:
                break

    def __init__(
        self,
        record: InvocationRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> None:
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def action(self) -> ActionProvenance:
        """Action the invocation ran.

        It is :py:attr:`~roboto.domain.actions.InvocationProvenance.action`: the action's name, the organization that
        owns it, and its version's digest.
        """
        return self.__record.provenance.action

    @property
    def compute_requirements(self) -> ComputeRequirements:
        """CPU, memory, and storage the invocation runs with: the action's, with any overrides the invoker gave."""
        return self.__record.compute_requirements

    @property
    def container_parameters(self) -> ContainerParameters:
        """Command, entry point, environment variables, and working directory the invocation's container starts with.

        They are the action's, with any overrides the invoker gave.
        """
        return self.__record.container_parameters

    @property
    def created(self) -> datetime.datetime:
        """Time the invocation was created, in UTC."""
        return self.__record.created

    @property
    def current_status(self) -> InvocationStatus:
        """Latest status in the invocation's status history.

        Statuses include :py:attr:`~roboto.domain.actions.InvocationStatus.Queued`, ``Processing``, and ``Completed``.
        When two statuses share a timestamp, the one with the higher value counts as the latest.
        """
        sorted_status_records = sorted(
            self.__record.status,
            key=lambda status_record: (status_record.timestamp, status_record.status),
        )
        return sorted_status_records[-1].status

    @property
    def data_source(self) -> InvocationDataSource:
        """Dataset the invocation reads from, or an unspecified data source when its invoker named none."""
        return self.__record.data_source

    @property
    def executable(self) -> ExecutableProvenance:
        """Container image the invocation ran."""
        return self.__record.provenance.executable

    @property
    def id(self) -> str:
        """Unique ID of the invocation, beginning with ``iv_``."""
        return self.__record.invocation_id

    @property
    def input_data(self) -> typing.Optional[InvocationInput]:
        """Inputs as the invoker requested them, or ``None`` if it requested none.

        A file selector with ``paths`` and no ``dataset_id`` is relative to the invocation's data source. When the
        data source is a dataset, this returns a copy of such a selector with ``dataset_id`` set to that dataset's ID,
        so the selector names its files without the invocation; the record is not changed. When the data source is
        unspecified, selectors are returned as stored.

        An invocation whose record holds only file paths within its data source, in the deprecated
        ``InvocationRecord.input_data``, returns a file selector for those paths in that dataset.
        """
        rich = self.__record.rich_input_data
        if rich:
            data_source = self.__record.data_source
            if data_source.is_unspecified() or not rich.files:
                return rich
            selectors = rich.files if isinstance(rich.files, list) else [rich.files]
            anchored = [
                selector.model_copy(update={"dataset_id": data_source.data_source_id})
                if selector.paths and not selector.dataset_id
                else selector
                for selector in selectors
            ]
            return rich.model_copy(update={"files": anchored if isinstance(rich.files, list) else anchored[0]})

        # Needs paths as well as a data source: a FileSelector with no paths, query, IDs, or names fails
        # validation, so a dataset with no paths selected from it is reported as no inputs.
        if not self.__record.data_source.is_unspecified() and self.__record.input_data:
            return InvocationInput.from_dataset_file_paths(
                dataset_id=self.__record.data_source.data_source_id,
                file_paths=self.__record.input_data,
            )

        return None

    @property
    def resolved_input_data(self) -> typing.Optional[InvocationInput]:
        """Inputs the request resolved to, each named by its file, session, or topic ID.

        ``None`` if the invocation records none. Where ``input_data`` can select inputs by path or by query, this names
        each input by its ID, whatever number of datasets they span. See
        :py:attr:`~roboto.domain.actions.InvocationRecord.resolved_input_data`.
        """
        return self.__record.resolved_input_data

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the invocation."""
        return self.__record.org_id

    @property
    def parameter_values(self) -> dict[str, typing.Any]:
        """Values of the action's parameters for this invocation, keyed by parameter name.

        Parameters the invoker left out have their defaults.
        """
        return self.__record.parameter_values

    @property
    def reached_terminal_status(self) -> bool:
        """Whether the current status ends the invocation.

        The statuses that end it are :py:attr:`~roboto.domain.actions.InvocationStatus.Completed`, ``Cancelled``,
        ``Failed``, and ``Deadly``.
        """
        return self.current_status.is_terminal()

    @property
    def record(self) -> InvocationRecord:
        """Record of the invocation that this instance holds."""
        return self.__record

    @property
    def source(self) -> SourceProvenance:
        """User or trigger that started the invocation."""
        return self.__record.provenance.source

    @property
    def status_log(self) -> list[InvocationStatusRecord]:
        """Statuses the invocation has entered, each with the time it entered it."""
        return self.__record.status

    @property
    def timeout(self) -> int:
        """Maximum time, in minutes, the invocation may run."""
        return self.__record.timeout

    @property
    def upload_destination(self) -> typing.Optional[InvocationUploadDestination]:
        """Where Roboto uploads the files the action writes to its output directory.

        ``None`` if the invoker named no destination. Without one, Roboto uploads them to the dataset the inputs come
        from, when they all come from one.
        """
        return self.__record.upload_destination

    def cancel(self) -> None:
        """Cancel the invocation, unless this instance's copy of its status is already terminal.

        Roboto marks the invocation :py:attr:`~roboto.domain.actions.InvocationStatus.Cancelled` and stops its
        containers. Cancelling an invocation that has already ended changes nothing. This instance's record is not
        updated; call ``refresh`` to see the new status.

        Examples:
            Cancel a running invocation:

            >>> invocation = Invocation.from_id("iv_12345")
            >>> if not invocation.reached_terminal_status:
            ...     invocation.cancel()
        """
        if self.current_status.is_terminal():
            return

        self.__roboto_client.post(
            f"v1/actions/invocations/{self.id}/cancel",
            owner_org_id=self.org_id,
        )

    def get_logs(self, page_token: typing.Optional[str] = None) -> collections.abc.Generator[LogRecord, None, None]:
        """Yield the lines the invocation's containers wrote to STDOUT and STDERR, fetching them a page at a time.

        The containers are the setup container, the action's own container, and the output handler; each
        :py:class:`~roboto.domain.actions.LogRecord` names the one that wrote it. An invocation that has written no
        logs yet yields nothing. To follow the logs of an invocation that is still running, use ``stream_logs``. Reading
        the logs takes permission to read every dataset the invocation was given, as ``from_id`` does.

        Args:
            page_token: Token from a previous page's response that resumes the listing after it. ``None`` starts at
                the first page.

        Examples:
            Print every line the invocation wrote:

            >>> invocation = Invocation.from_id("iv_12345")
            >>> for record in invocation.get_logs():
            ...     print(record.process, record.log)
        """
        while True:
            response = self.__roboto_client.get(
                f"v1/actions/invocations/{self.id}/logs",
                query={"page_token": page_token} if page_token else None,
                owner_org_id=self.org_id,
            )
            paginated_results = response.to_paginated_list(LogRecord)
            for record in paginated_results.items:
                yield record
            if paginated_results.next_token:
                page_token = paginated_results.next_token
            else:
                break

    def is_queued_for_scheduling(self) -> bool:
        """Return whether the invocation is waiting for Roboto to start it.

        True when the current status is :py:attr:`~roboto.domain.actions.InvocationStatus.Queued` and the status
        history holds no ``Deadly`` entry.
        """
        if self.current_status != InvocationStatus.Queued:
            return False

        return not any(status_record.status == InvocationStatus.Deadly for status_record in self.__record.status)

    def refresh(self) -> "Invocation":
        """Replace this instance's record with the invocation's current record from Roboto.

        Use it to see the status changes and other updates made since this instance was loaded.

        Returns:
            This instance, with its record updated from Roboto's response.

        Examples:
            >>> invocation = Invocation.from_id("iv_12345")
            >>> print(invocation.refresh().current_status)
        """
        self.__record = Invocation.from_id(self.id, self.__roboto_client).record
        return self

    def set_container_image_digest(
        self,
        digest: str,
    ) -> "Invocation":
        """Record the digest of the container image Roboto pulled to run the invocation.

        Roboto calls this when it has pulled the invocation's container image. It refuses the request unless it comes
        from a Roboto administrator or with the credentials Roboto gives the running invocation.

        Args:
            digest: Digest of the pulled container image.

        Returns:
            This instance, with its record updated from Roboto's response.
        """
        request = SetContainerInfoRequest(image_digest=digest)
        response = self.__roboto_client.put(
            f"v1/actions/invocations/{self.id}/container-info",
            data=request,
            owner_org_id=self.org_id,
        )
        record = response.to_record(InvocationRecord)
        self.__record = record
        return self

    def set_logs_location(self, logs: LogsLocation) -> "Invocation":
        """Record the S3 location where Roboto stores the invocation's log files.

        Roboto calls this when it schedules the invocation. Only Roboto administrators may call it. To read the logs,
        use ``get_logs`` or ``stream_logs``.

        Args:
            logs: Bucket and key prefix of the log files.

        Returns:
            This instance, with its record updated from Roboto's response.
        """
        request = SetLogsLocationRequest(bucket=logs.bucket, prefix=logs.prefix)
        response = self.__roboto_client.put(
            f"v1/actions/invocations/{self.id}/logs",
            data=request,
            owner_org_id=self.org_id,
        )
        record = response.to_record(InvocationRecord)
        self.__record = record
        return self

    def stream_logs(
        self, last_read: typing.Optional[str] = None
    ) -> collections.abc.Generator[LogRecord, None, typing.Optional[str]]:
        """Yield the log lines written after ``last_read``, then return a token that resumes after the last of them.

        Use it to follow the logs of an invocation that is still running. The generator's return value, which is the
        ``value`` of the ``StopIteration`` it raises when exhausted, is the token to pass as ``last_read`` on the next
        call, so that call yields only lines written since. It is ``None`` when the invocation has no logs to read.
        Reading the logs takes permission to read every dataset the invocation was given, as ``from_id`` does.

        Args:
            last_read: Token a previous call returned. ``None`` starts at the first line.

        Examples:
            Print the invocation's logs as it writes them, until it ends:

            >>> import time
            >>> invocation = Invocation.from_id("iv_12345")
            >>> last_read = None
            >>> while True:
            ...     ended = invocation.refresh().reached_terminal_status
            ...     logs = invocation.stream_logs(last_read)
            ...     try:
            ...         while True:
            ...             print(next(logs).log)
            ...     except StopIteration as stop:
            ...         last_read = stop.value
            ...     if ended:
            ...         break
            ...     time.sleep(2)
        """
        while True:
            response = self.__roboto_client.get(
                f"v1/actions/invocations/{self.id}/logs/stream",
                owner_org_id=self.org_id,
                query={"last_read": last_read} if last_read else None,
            )

            response_data = response.to_dict(json_path=["data"])
            streamed_results = StreamedList(
                items=[LogRecord.model_validate(record) for record in response_data["items"]],
                has_next=response_data["has_next"],
                last_read=response_data["last_read"],
            )

            for record in streamed_results.items:
                yield record
            if streamed_results.has_next and streamed_results.last_read:
                last_read = streamed_results.last_read
            else:
                break

        return streamed_results.last_read

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the record this instance holds as a JSON-compatible dictionary.

        Returns:
            :py:class:`~roboto.domain.actions.InvocationRecord` of the invocation, as a JSON-compatible dictionary.

        Examples:
            >>> invocation = Invocation.from_id("iv_12345")
            >>> invocation.to_dict()["invocation_id"]
            'iv_12345'
        """
        return self.__record.model_dump(mode="json")

    def update_status(self, next_status: InvocationStatus, detail: typing.Optional[str] = None) -> "Invocation":
        """Record that the invocation entered ``next_status``.

        Roboto calls this when the invocation moves to a new status. It refuses the request unless it comes from a
        Roboto administrator or with the credentials Roboto gives the running invocation, and it leaves the status
        unchanged when the invocation cannot move to ``next_status`` from its current status (see
        :py:meth:`~roboto.domain.actions.InvocationStatus.can_transition_to`).

        A third failure is recorded as :py:attr:`~roboto.domain.actions.InvocationStatus.Deadly`, which is not
        retried: when ``next_status`` is ``Failed`` and this instance's status history already holds two ``Failed``
        entries, ``Deadly`` is sent instead.

        Args:
            next_status: Status the invocation entered.
            detail: Human-readable explanation of the status, such as why the invocation failed. ``None`` or an empty
                string records the text ``"None"``.

        Returns:
            This instance, with its record updated from Roboto's response.
        """
        if next_status == InvocationStatus.Failed:
            num_failures = len(
                [
                    status_record
                    for status_record in self.__record.status
                    if status_record.status == InvocationStatus.Failed
                ]
            )
            if num_failures >= 2:
                next_status = InvocationStatus.Deadly

        request = UpdateInvocationStatus(
            status=next_status,
            detail=detail if detail else "None",
        )
        response = self.__roboto_client.post(
            f"v1/actions/invocations/{self.id}/status",
            data=request,
            owner_org_id=self.org_id,
        )
        record = response.to_record(InvocationRecord)
        self.__record = record
        return self

    def wait_for_terminal_status(
        self,
        timeout: float = 60 * 5,
        poll_interval: Interval = 5,
    ) -> None:
        """Wait until the invocation's status is terminal, refreshing this instance's record as it polls.

        When this returns, ``current_status`` is :py:attr:`~roboto.domain.actions.InvocationStatus.Completed`,
        ``Cancelled``, ``Failed``, or ``Deadly``.

        Args:
            timeout: Maximum time to wait, in seconds.
            poll_interval: Seconds to wait between polls, or a function that takes the number of polls made so far and
                returns the seconds to wait before the next.

        Raises:
            roboto.waiters.TimeoutError: The invocation did not end within ``timeout``. It subclasses the built-in
                ``TimeoutError``.

        Examples:
            Wait up to ten minutes for an invocation to end:

            >>> invocation = Invocation.from_id("iv_12345")
            >>> invocation.wait_for_terminal_status(timeout=600)
            >>> print(invocation.current_status)
        """

        def _condition() -> bool:
            self.refresh()
            return self.reached_terminal_status

        return wait_for(
            _condition,
            timeout=timeout,
            interval=poll_interval,
            timeout_msg=f"Timed out waiting for invocation '{self.id}' to reach terminal status",
        )
