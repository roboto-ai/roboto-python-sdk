# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Topics APIs in active refinement; see :py:mod:`roboto.experimental` for the stability contract."""

from .batch_transforms import (
    TIMESTAMP_FIELD_METADATA_KEY,
    timestamp_column_index,
)
from .operations import (
    FieldAddress,
    ReadPlanRequest,
    RepresentationOverride,
    RepresentationPreference,
    SetTopicUnixOffsetRequest,
)
from .read_plan import (
    PLAN_VERSION,
    ReadPlan,
    ReadPlanFieldRef,
    ReadPlanObjectRef,
    ReadPlanPartition,
    ReadPlanProjection,
    ReadPlanScanTask,
    ReadPlanSchemaRef,
    ReadPlanTimestamp,
    TimeWindow,
)
from .record import RepresentationRecord, RepresentationSelector
from .topic import (
    DatasetContext,
    DeviceContext,
    FieldAddressLike,
    FileContext,
    SessionContext,
    Topic,
    TopicContext,
)

__all__ = [
    "PLAN_VERSION",
    "TIMESTAMP_FIELD_METADATA_KEY",
    "DatasetContext",
    "DeviceContext",
    "FieldAddress",
    "FieldAddressLike",
    "FileContext",
    "ReadPlan",
    "ReadPlanFieldRef",
    "ReadPlanObjectRef",
    "ReadPlanPartition",
    "ReadPlanProjection",
    "ReadPlanRequest",
    "ReadPlanScanTask",
    "ReadPlanSchemaRef",
    "ReadPlanTimestamp",
    "RepresentationOverride",
    "RepresentationPreference",
    "RepresentationRecord",
    "RepresentationSelector",
    "SessionContext",
    "SetTopicUnixOffsetRequest",
    "TimeWindow",
    "Topic",
    "TopicContext",
    "timestamp_column_index",
]
