# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import contextlib
import json
from typing import Optional

import pydantic
import pytest

from roboto.domain import actions
from roboto.time import utcnow


def test_InvocationRecord_to_str_stringifies_all_attributes() -> None:
    # Arrange
    record = actions.InvocationRecord(
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
        last_heartbeat=None,
        last_status=actions.InvocationStatus.Queued,
        parameter_values={
            "test_parameter_name": "test_value",
            "test_parameter_name_2": 2,
        },
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
                source_type=actions.InvocationSource.Manual, source_id="test_user_id"
            ),
        ),
        timeout=43200,
    )

    # Act
    actual = str(record)

    # Assert
    assert json.loads(actual).keys() == record.model_dump().keys()


@pytest.mark.parametrize(
    ["vCPU", "memory", "expectation", "context"],
    [
        (128, 512, None, pytest.raises(pydantic.ValidationError)),
        (
            256,
            1024,
            actions.ComputeRequirements(vCPU=256, memory=1024),
            contextlib.nullcontext(),
        ),
        (
            4096,
            12 * 1024,
            actions.ComputeRequirements(vCPU=4096, memory=12 * 1024),
            contextlib.nullcontext(),
        ),
        (
            8192,
            60 * 1024,
            actions.ComputeRequirements(vCPU=8192, memory=60 * 1024),
            contextlib.nullcontext(),
        ),
        (
            16384,
            32 * 1024,
            actions.ComputeRequirements(vCPU=16384, memory=32 * 1024),
            contextlib.nullcontext(),
        ),
        (16384, 30 * 1024, None, pytest.raises(pydantic.ValidationError)),
    ],
)
def test_ComputeRequirements_validates_vcpu_memory_combination(
    vCPU: int,
    memory: int,
    expectation: actions.ComputeRequirements,
    context: contextlib.AbstractContextManager,
) -> None:
    # Arrange / Act
    with context:
        actual = actions.ComputeRequirements(vCPU=vCPU, memory=memory)

        # Assert
        assert actual == expectation


@pytest.mark.parametrize(
    ["current_status", "next_status", "expected"],
    [
        (actions.InvocationStatus.Queued, actions.InvocationStatus.Queued, True),
        (actions.InvocationStatus.Queued, actions.InvocationStatus.Scheduled, True),
        (actions.InvocationStatus.Queued, actions.InvocationStatus.Downloading, True),
        (actions.InvocationStatus.Queued, actions.InvocationStatus.Processing, True),
        (actions.InvocationStatus.Queued, actions.InvocationStatus.Uploading, True),
        (actions.InvocationStatus.Queued, actions.InvocationStatus.Completed, True),
        (actions.InvocationStatus.Queued, actions.InvocationStatus.Cancelled, True),
        (actions.InvocationStatus.Queued, actions.InvocationStatus.Failed, True),
        (actions.InvocationStatus.Queued, actions.InvocationStatus.Deadly, True),
        (actions.InvocationStatus.Scheduled, actions.InvocationStatus.Queued, False),
        (actions.InvocationStatus.Scheduled, actions.InvocationStatus.Scheduled, True),
        (
            actions.InvocationStatus.Scheduled,
            actions.InvocationStatus.Downloading,
            True,
        ),
        (
            actions.InvocationStatus.Scheduled,
            actions.InvocationStatus.Processing,
            True,
        ),
        (actions.InvocationStatus.Scheduled, actions.InvocationStatus.Uploading, True),
        (actions.InvocationStatus.Scheduled, actions.InvocationStatus.Completed, True),
        (actions.InvocationStatus.Scheduled, actions.InvocationStatus.Cancelled, True),
        (actions.InvocationStatus.Scheduled, actions.InvocationStatus.Failed, True),
        (actions.InvocationStatus.Scheduled, actions.InvocationStatus.Deadly, False),
        (actions.InvocationStatus.Downloading, actions.InvocationStatus.Queued, False),
        (
            actions.InvocationStatus.Downloading,
            actions.InvocationStatus.Scheduled,
            False,
        ),
        (
            actions.InvocationStatus.Downloading,
            actions.InvocationStatus.Downloading,
            True,
        ),
        (
            actions.InvocationStatus.Downloading,
            actions.InvocationStatus.Processing,
            True,
        ),
        (
            actions.InvocationStatus.Downloading,
            actions.InvocationStatus.Uploading,
            True,
        ),
        (
            actions.InvocationStatus.Downloading,
            actions.InvocationStatus.Completed,
            True,
        ),
        (
            actions.InvocationStatus.Downloading,
            actions.InvocationStatus.Cancelled,
            True,
        ),
        (actions.InvocationStatus.Downloading, actions.InvocationStatus.Failed, True),
        (actions.InvocationStatus.Downloading, actions.InvocationStatus.Deadly, False),
        (actions.InvocationStatus.Processing, actions.InvocationStatus.Queued, False),
        (
            actions.InvocationStatus.Processing,
            actions.InvocationStatus.Scheduled,
            False,
        ),
        (
            actions.InvocationStatus.Processing,
            actions.InvocationStatus.Downloading,
            False,
        ),
        (
            actions.InvocationStatus.Processing,
            actions.InvocationStatus.Processing,
            True,
        ),
        (actions.InvocationStatus.Processing, actions.InvocationStatus.Uploading, True),
        (
            actions.InvocationStatus.Processing,
            actions.InvocationStatus.Completed,
            True,
        ),
        (actions.InvocationStatus.Processing, actions.InvocationStatus.Cancelled, True),
        (actions.InvocationStatus.Processing, actions.InvocationStatus.Failed, True),
        (actions.InvocationStatus.Processing, actions.InvocationStatus.Deadly, False),
        (actions.InvocationStatus.Uploading, actions.InvocationStatus.Queued, False),
        (actions.InvocationStatus.Uploading, actions.InvocationStatus.Scheduled, False),
        (
            actions.InvocationStatus.Uploading,
            actions.InvocationStatus.Downloading,
            False,
        ),
        (
            actions.InvocationStatus.Uploading,
            actions.InvocationStatus.Processing,
            False,
        ),
        (actions.InvocationStatus.Uploading, actions.InvocationStatus.Uploading, True),
        (actions.InvocationStatus.Uploading, actions.InvocationStatus.Completed, True),
        (actions.InvocationStatus.Uploading, actions.InvocationStatus.Cancelled, True),
        (actions.InvocationStatus.Uploading, actions.InvocationStatus.Failed, True),
        (actions.InvocationStatus.Uploading, actions.InvocationStatus.Deadly, False),
        (actions.InvocationStatus.Completed, actions.InvocationStatus.Queued, False),
        (actions.InvocationStatus.Completed, actions.InvocationStatus.Scheduled, False),
        (
            actions.InvocationStatus.Completed,
            actions.InvocationStatus.Downloading,
            False,
        ),
        (
            actions.InvocationStatus.Completed,
            actions.InvocationStatus.Processing,
            False,
        ),
        (actions.InvocationStatus.Completed, actions.InvocationStatus.Uploading, False),
        (actions.InvocationStatus.Completed, actions.InvocationStatus.Completed, True),
        (actions.InvocationStatus.Completed, actions.InvocationStatus.Cancelled, False),
        (actions.InvocationStatus.Completed, actions.InvocationStatus.Failed, False),
        (actions.InvocationStatus.Completed, actions.InvocationStatus.Deadly, False),
        (actions.InvocationStatus.Cancelled, actions.InvocationStatus.Queued, False),
        (actions.InvocationStatus.Cancelled, actions.InvocationStatus.Scheduled, False),
        (
            actions.InvocationStatus.Cancelled,
            actions.InvocationStatus.Downloading,
            False,
        ),
        (
            actions.InvocationStatus.Cancelled,
            actions.InvocationStatus.Processing,
            False,
        ),
        (actions.InvocationStatus.Cancelled, actions.InvocationStatus.Uploading, False),
        (actions.InvocationStatus.Cancelled, actions.InvocationStatus.Completed, False),
        (actions.InvocationStatus.Cancelled, actions.InvocationStatus.Cancelled, True),
        (actions.InvocationStatus.Cancelled, actions.InvocationStatus.Failed, False),
        (actions.InvocationStatus.Cancelled, actions.InvocationStatus.Deadly, False),
        (actions.InvocationStatus.Failed, actions.InvocationStatus.Queued, True),
        (actions.InvocationStatus.Failed, actions.InvocationStatus.Scheduled, False),
        (actions.InvocationStatus.Failed, actions.InvocationStatus.Downloading, False),
        (actions.InvocationStatus.Failed, actions.InvocationStatus.Processing, False),
        (actions.InvocationStatus.Failed, actions.InvocationStatus.Uploading, False),
        (actions.InvocationStatus.Failed, actions.InvocationStatus.Completed, False),
        (actions.InvocationStatus.Failed, actions.InvocationStatus.Cancelled, False),
        (actions.InvocationStatus.Failed, actions.InvocationStatus.Failed, True),
        (actions.InvocationStatus.Failed, actions.InvocationStatus.Deadly, True),
        (actions.InvocationStatus.Deadly, actions.InvocationStatus.Queued, False),
        (actions.InvocationStatus.Deadly, actions.InvocationStatus.Scheduled, False),
        (actions.InvocationStatus.Deadly, actions.InvocationStatus.Downloading, False),
        (actions.InvocationStatus.Deadly, actions.InvocationStatus.Processing, False),
        (actions.InvocationStatus.Deadly, actions.InvocationStatus.Uploading, False),
        (actions.InvocationStatus.Deadly, actions.InvocationStatus.Completed, False),
        (actions.InvocationStatus.Deadly, actions.InvocationStatus.Cancelled, False),
        (actions.InvocationStatus.Deadly, actions.InvocationStatus.Failed, False),
        (actions.InvocationStatus.Deadly, actions.InvocationStatus.Deadly, True),
    ],
)
def test_InvocationStatus_can_transition_to(
    current_status: actions.InvocationStatus,
    next_status: actions.InvocationStatus,
    expected: bool,
) -> None:
    # Arrange / Act
    actual = current_status.can_transition_to(next_status)

    # Assert
    assert actual is expected


@pytest.mark.parametrize(
    ["current_status", "next_status"],
    [
        (actions.InvocationStatus.Queued, actions.InvocationStatus.Scheduled),
        (actions.InvocationStatus.Scheduled, actions.InvocationStatus.Downloading),
        (actions.InvocationStatus.Downloading, actions.InvocationStatus.Processing),
        (actions.InvocationStatus.Processing, actions.InvocationStatus.Uploading),
        (actions.InvocationStatus.Uploading, actions.InvocationStatus.Completed),
        (actions.InvocationStatus.Completed, None),
        (actions.InvocationStatus.Cancelled, None),
        (actions.InvocationStatus.Failed, None),
        (actions.InvocationStatus.Deadly, None),
    ],
)
def test_InvocationStatus_next(
    current_status: actions.InvocationStatus,
    next_status: Optional[actions.InvocationStatus],
) -> None:
    # Arrange / Act
    actual = current_status.next()

    # Assert
    assert actual is next_status
