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
    InvocationRecord,
    InvocationStatus,
    InvocationStatusRecord,
    LogRecord,
    LogsLocation,
    SourceProvenance,
)


class Invocation:
    __record: InvocationRecord
    __roboto_client: RobotoClient

    @classmethod
    def from_id(
        cls,
        invocation_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Invocation":
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
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def action(self) -> ActionProvenance:
        return self.__record.provenance.action

    @property
    def compute_requirements(self) -> ComputeRequirements:
        return self.__record.compute_requirements

    @property
    def container_parameters(self) -> ContainerParameters:
        return self.__record.container_parameters

    @property
    def created(self) -> datetime.datetime:
        return self.__record.created

    @property
    def current_status(self) -> InvocationStatus:
        sorted_status_records = sorted(
            self.__record.status, key=lambda s: s.status.value
        )
        return sorted_status_records[-1].status

    @property
    def data_source(self) -> InvocationDataSource:
        return self.__record.data_source

    @property
    def executable(self) -> ExecutableProvenance:
        return self.__record.provenance.executable

    @property
    def id(self) -> str:
        return self.__record.invocation_id

    @property
    def input_data(self) -> list[str]:
        return self.__record.input_data

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def parameter_values(self) -> dict[str, typing.Any]:
        return self.__record.parameter_values

    @property
    def reached_terminal_status(self) -> bool:
        return any(
            status_record.status.is_terminal() for status_record in self.__record.status
        )

    @property
    def record(self) -> InvocationRecord:
        return self.__record

    @property
    def source(self) -> SourceProvenance:
        return self.__record.provenance.source

    @property
    def status_log(self) -> list[InvocationStatusRecord]:
        return self.__record.status

    @property
    def timeout(self) -> int:
        return self.__record.timeout

    def cancel(self) -> None:
        if self.current_status.is_terminal():
            return

        self.__roboto_client.post(
            f"v1/actions/invocations/{self.id}/cancel",
            owner_org_id=self.org_id,
        )

    def get_logs(
        self, page_token: typing.Optional[str] = None
    ) -> collections.abc.Generator[LogRecord, None, None]:
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
