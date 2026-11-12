# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Topics APIs in active refinement; see :py:mod:`roboto.experimental` for the stability contract."""

from .batch_transforms import (
    ELEMENT_NAMES_FIELD_METADATA_KEY,
    TIMESTAMP_FIELD_METADATA_KEY,
    timestamp_column_index,
)
from .named_array import NamedArray
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
    ReadPlanNamedArray,
    ReadPlanObjectRef,
    ReadPlanPartition,
    ReadPlanProjection,
    ReadPlanScanTask,
    ReadPlanSchemaRef,
    ReadPlanTimestamp,
    TimeWindow,
    UnreadableTopicPartitionsWarning,
)
from .record import RepresentationRecord, RepresentationSelector
from .topic import (
    DatasetContext,
    DeviceContext,
    EventContext,
    FieldAddressLike,
    FileContext,
    SessionContext,
    Topic,
    TopicContext,
)

__all__ = [
    "ELEMENT_NAMES_FIELD_METADATA_KEY",
    "PLAN_VERSION",
    "TIMESTAMP_FIELD_METADATA_KEY",
    "DatasetContext",
    "DeviceContext",
    "EventContext",
    "FieldAddress",
    "FieldAddressLike",
    "FileContext",
    "NamedArray",
    "ReadPlan",
    "ReadPlanFieldRef",
    "ReadPlanNamedArray",
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
    "UnreadableTopicPartitionsWarning",
    "timestamp_column_index",
]
