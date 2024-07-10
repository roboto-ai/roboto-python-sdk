# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import unittest.mock

import pytest

from roboto import RobotoClient
from roboto.domain import actions
from roboto.http import FakeHttpResponseFactory
from roboto.time import utcnow


class TestInvocation:
    __base_invocation_record: actions.InvocationRecord
    __mock_roboto_client: RobotoClient

    def setup_method(self) -> None:
        self.__base_invocation_record = actions.InvocationRecord(
            invocation_id="test_invocation_id",
            org_id="test_org_id",
            created=utcnow(),
            compute_requirements=actions.ComputeRequirements(),
            container_parameters=actions.ContainerParameters(),
            data_source=actions.InvocationDataSource(
                data_source_type=actions.InvocationDataSourceType.Dataset,
                data_source_id="test_dataset_id",
            ),
            idempotency_id=None,
            input_data=["**/cam_front/*.jpg"],
            last_status=actions.InvocationStatus.Queued,
            provenance=actions.InvocationProvenance(
                action=actions.ActionProvenance(
                    name="test_action_name",
                    org_id="test_org_id",
                    digest="test_digest",
                ),
                executable=actions.ExecutableProvenance(
                    container_image_uri="busybox:latest",
                    container_image_digest="sha256:1234567890abcdef",
                ),
                source=actions.SourceProvenance(
                    source_type=actions.InvocationSource.Manual,
                    source_id="test_user_id",
                ),
            ),
            timeout=43200,
        )
        self.__mock_roboto_client = unittest.mock.create_autospec(
            RobotoClient, instance=True
        )

    @pytest.mark.parametrize(
        ["status_history", "expectation"],
        [
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    )
                ],
                True,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Scheduled, timestamp=utcnow()
                    ),
                ],
                False,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Scheduled, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Completed, timestamp=utcnow()
                    ),
                ],
                False,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Cancelled, timestamp=utcnow()
                    ),
                ],
                False,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Failed, timestamp=utcnow()
                    ),
                ],
                False,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Deadly, timestamp=utcnow()
                    ),
                ],
                False,
            ),
        ],
    )
    def test_is_queued_for_scheduling(
        self, status_history: list[actions.InvocationStatusRecord], expectation: bool
    ) -> None:
        # Arrange
        record = self.__base_invocation_record.model_copy(
            deep=True, update={"status": status_history}
        )
        invocation = actions.Invocation(record, self.__mock_roboto_client)

        # Act
        actual = invocation.is_queued_for_scheduling()

        # Assert
        assert actual == expectation

    @pytest.mark.parametrize(
        ["status_history", "next_status", "expected_deadly"],
        [
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    )
                ],
                actions.InvocationStatus.Scheduled,
                False,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Scheduled, timestamp=utcnow()
                    ),
                ],
                actions.InvocationStatus.Downloading,
                False,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                ],
                actions.InvocationStatus.Failed,
                False,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Failed, timestamp=utcnow()
                    ),
                ],
                actions.InvocationStatus.Failed,
                False,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Failed, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Failed, timestamp=utcnow()
                    ),
                ],
                actions.InvocationStatus.Failed,
                True,
            ),
        ],
    )
    def test_update_status_sets_status_to_deadly_if_necessary(
        self,
        status_history: list[actions.InvocationStatusRecord],
        next_status: actions.InvocationStatus,
        expected_deadly: bool,
    ) -> None:
        # Arrange
        original_record = self.__base_invocation_record.model_copy(
            deep=True, update={"status": status_history}
        )

        with unittest.mock.patch.object(
            self.__mock_roboto_client, "post"
        ) as http_post_mock:
            http_post_mock.side_effect = (
                self.__update_invocation_status_request_interceptor
            )

            invocation = actions.Invocation(original_record, self.__mock_roboto_client)

            # Evergreen check
            assert invocation.current_status != actions.InvocationStatus.Deadly

            # Act
            invocation.update_status(next_status)

        # Assert
        if expected_deadly:
            assert invocation.current_status == actions.InvocationStatus.Deadly
        else:
            assert invocation.current_status != actions.InvocationStatus.Deadly

    @pytest.mark.parametrize(
        ["status_history", "expected_current_status"],
        [
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                ],
                actions.InvocationStatus.Queued,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Scheduled, timestamp=utcnow()
                    ),
                ],
                actions.InvocationStatus.Scheduled,
            ),
            (
                [
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Queued, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Scheduled, timestamp=utcnow()
                    ),
                    actions.InvocationStatusRecord(
                        status=actions.InvocationStatus.Failed, timestamp=utcnow()
                    ),
                ],
                actions.InvocationStatus.Failed,
            ),
        ],
    )
    def test_current_status_returns_last_status(
        self,
        status_history: list[actions.InvocationStatusRecord],
        expected_current_status: actions.InvocationStatus,
    ) -> None:
        # Arrange
        record = self.__base_invocation_record.model_copy(
            deep=True, update={"status": status_history}
        )
        invocation = actions.Invocation(record, self.__mock_roboto_client)

        # Act
        actual = invocation.current_status

        # Assert
        assert actual == expected_current_status

    def __update_invocation_status_request_interceptor(self, *args, **kwargs):
        post_body: actions.UpdateInvocationStatus = kwargs["data"]
        new_status = actions.InvocationStatusRecord(
            status=post_body.status, detail=post_body.detail, timestamp=utcnow()
        )
        updated_invocation = self.__base_invocation_record.model_copy(
            update={"status": [*self.__base_invocation_record.status, new_status]}
        )
        response_data = {
            "data": updated_invocation.model_dump(mode="json"),
        }
        invocation_id = self.__base_invocation_record.invocation_id
        response_factory = FakeHttpResponseFactory(
            url=f"v1/actions/invocations/{invocation_id}/status",
            response_data=response_data,
        )
        return response_factory()
