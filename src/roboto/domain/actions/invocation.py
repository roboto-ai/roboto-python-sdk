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


class Invocation:
    """An instance of an execution of an action, initiated manually by a user or automatically by a trigger.

    An Invocation represents a single execution of an Action with specific inputs,
    parameters, and configuration. It tracks the execution lifecycle from creation
    through completion, including status updates, logs, and results.

    Invocations are created by calling :py:meth:`Action.invoke` or through the UI.
    They cannot be created directly through the constructor. Each invocation has a
    unique ID and maintains a complete audit trail of its execution.

    Key features:

    - Status tracking (Queued, Running, Completed, Failed, etc.)
    - Input data specification and parameter values
    - Compute requirement and container parameter overrides
    - Log collection and output file management
    - Progress monitoring and result retrieval
    """

    __record: InvocationRecord
    __roboto_client: RobotoClient

    @classmethod
    def from_id(
        cls,
        invocation_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Invocation":
        """Load an existing invocation by its ID.

        Retrieves an invocation from the Roboto platform using its unique identifier.

        Args:
            invocation_id: The unique ID of the invocation to retrieve.
            roboto_client: Roboto client instance. Uses default if not provided.

        Returns:
            The Invocation instance.

        Raises:
            RobotoNotFoundException: If the invocation is not found.
            RobotoUnauthorizedException: If the caller lacks permission to access the invocation.

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
        """Query invocations with optional filtering and pagination.

        Searches for invocations based on the provided query specification.
        Can filter by status, action name, creation time, and other attributes.

        Args:
            spec: Query specification with filters, sorting, and pagination.
                If not provided, returns all accessible invocations.
            owner_org_id: Organization ID to search within. If not provided,
                searches in the caller's organization.
            roboto_client: Roboto client instance. Uses default if not provided.

        Yields:
            Invocation instances matching the query criteria.

        Raises:
            ValueError: If the query specification contains unknown fields.
            RobotoUnauthorizedException: If the caller lacks permission to query invocations.

        Examples:
            Query all invocations:

            >>> for invocation in Invocation.query():
            ...     print(f"Invocation: {invocation.id}")

            Query completed invocations:

            >>> from roboto.query import QuerySpecification
            >>> from roboto.domain.actions import InvocationStatus
            >>> spec = QuerySpecification().where("current_status").equals(InvocationStatus.Completed)
            >>> completed = list(Invocation.query(spec))

            Query recent invocations:

            >>> spec = QuerySpecification().order_by("created", ascending=False).limit(10)
            >>> recent = list(Invocation.query(spec))
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec or QuerySpecification()

        known = set(InvocationRecord.model_fields.keys())
        actual = set()
        for field in spec.fields():
            # Support dot notation for nested fields
            # E.g., "metadata.SoftwareVersion"
            if "." in field:
                actual.add(field.split(".")[0])
            else:
                actual.add(field)
        unknown = actual - known
        if unknown:
            plural = len(unknown) > 1
            msg = (
                "are not known attributes of Invocation"
                if plural
                else "is not a known attribute of Invocation"
            )
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
        """Initialize an Invocation instance.

        Args:
            record: The invocation record containing all invocation data.
            roboto_client: Roboto client instance. Uses default if not provided.
        """
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def action(self) -> ActionProvenance:
        """Provenance information about the action that was invoked."""
        return self.__record.provenance.action

    @property
    def compute_requirements(self) -> ComputeRequirements:
        """The compute requirements (CPU, memory) used for this invocation."""
        return self.__record.compute_requirements

    @property
    def container_parameters(self) -> ContainerParameters:
        """The container parameters used for this invocation."""
        return self.__record.container_parameters

    @property
    def created(self) -> datetime.datetime:
        """The timestamp when this invocation was created."""
        return self.__record.created

    @property
    def current_status(self) -> InvocationStatus:
        """The current status of this invocation (e.g., Queued, Running, Completed)."""
        sorted_status_records = sorted(
            self.__record.status,
            # Sort by timestamp ASC, then by status value ASC
            key=lambda status_record: (status_record.timestamp, status_record.status),
        )
        return sorted_status_records[-1].status

    @property
    def data_source(self) -> InvocationDataSource:
        """The data source that provided input data for this invocation."""
        return self.__record.data_source

    @property
    def executable(self) -> ExecutableProvenance:
        """Provenance information about the executable (container) that was run."""
        return self.__record.provenance.executable

    @property
    def id(self) -> str:
        """The unique identifier for this invocation."""
        return self.__record.invocation_id

    @property
    def input_data(self) -> typing.Optional[InvocationInput]:
        """The input data specification for this invocation, if any."""
        if self.__record.rich_input_data:
            return self.__record.rich_input_data

        if not self.__record.data_source.is_unspecified():
            return InvocationInput.from_dataset_file_paths(
                dataset_id=self.__record.data_source.data_source_id,
                file_paths=self.__record.input_data,
            )

        return None

    @property
    def org_id(self) -> str:
        """The organization ID that owns this invocation."""
        return self.__record.org_id

    @property
    def parameter_values(self) -> dict[str, typing.Any]:
        """The parameter values that were provided when this invocation was created."""
        return self.__record.parameter_values

    @property
    def reached_terminal_status(self) -> bool:
        """True if this invocation has reached a terminal status (Completed, Failed, etc.)."""
        return self.current_status.is_terminal()

    @property
    def record(self) -> InvocationRecord:
        """The underlying invocation record containing all invocation data."""
        return self.__record

    @property
    def source(self) -> SourceProvenance:
        """Provenance information about the source that initiated this invocation."""
        return self.__record.provenance.source

    @property
    def status_log(self) -> list[InvocationStatusRecord]:
        """The complete history of status changes for this invocation."""
        return self.__record.status

    @property
    def timeout(self) -> int:
        """The timeout in minutes for this invocation."""
        return self.__record.timeout

    @property
    def upload_destination(self) -> typing.Optional[InvocationUploadDestination]:
        """The destination where output files from this invocation will be uploaded."""
        return self.__record.upload_destination

    def cancel(self) -> None:
        """Cancel this invocation if it is not already in a terminal status.

        Attempts to cancel the invocation. If the invocation has already
        completed, failed, or reached another terminal status, this method
        has no effect.

        Raises:
            RobotoNotFoundException: If the invocation is not found.
            RobotoUnauthorizedException: If the caller lacks permission to cancel the invocation.

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

    def get_logs(
        self, page_token: typing.Optional[str] = None
    ) -> collections.abc.Generator[LogRecord, None, None]:
        """Retrieve runtime STDOUT/STDERR logs generated during this invocation's execution.

        Fetches log records from the invocation's container execution, with support
        for pagination to handle large log volumes.

        Args:
            page_token: Optional token for pagination. If provided, starts
                retrieving logs from that point.

        Yields:
            LogRecord instances containing log messages and metadata.

        Raises:
            RobotoNotFoundException: If the invocation is not found.
            RobotoUnauthorizedException: If the caller lacks permission to access logs.
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
        """
        An invocation is queued for scheduling if:
            1. its most recent status is "Queued"
            3. and is not "Deadly"
        """
        if self.current_status != InvocationStatus.Queued:
            return False

        return not any(
            status_record.status == InvocationStatus.Deadly
            for status_record in self.__record.status
        )

    def refresh(self) -> "Invocation":
        self.__record = Invocation.from_id(self.id, self.__roboto_client).record
        return self

    def set_container_image_digest(
        self,
        digest: str,
    ) -> "Invocation":
        """
        This is an admin-only operation to memorialize the digest of the container image
        that was pulled in the course of invoking the action.
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
        """
        This is an admin-only operation to memorialize the base location where invocation logs are saved.

        Use the "get_logs" or "stream_logs" methods to access invocation logs.
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
        while True:
            response = self.__roboto_client.get(
                f"v1/actions/invocations/{self.id}/logs/stream",
                owner_org_id=self.org_id,
                query={"last_read": last_read} if last_read else None,
            )

            response_data = response.to_dict(json_path=["data"])
            streamed_results = StreamedList(
                items=[
                    LogRecord.model_validate(record)
                    for record in response_data["items"]
                ],
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
        return self.__record.model_dump(mode="json")

    def update_status(
        self, next_status: InvocationStatus, detail: typing.Optional[str] = None
    ) -> "Invocation":
        if next_status == InvocationStatus.Failed:
            # Heuristic: if this is the third time the invocation has failed, it is Deadly
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
        """
        Wait for the invocation to reach a terminal status.

        Throws a :py:exc:`~roboto.waiters.TimeoutError` if the timeout is reached.

        Args:
            timeout: The maximum amount of time, in seconds, to wait for the invocation to reach a terminal status.
            poll_interval: The amount of time, in seconds, to wait between polling iterations.
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
