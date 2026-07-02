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
)
from .read_plan import (
    PLAN_VERSION,
    ReadPlan,
    ReadPlanExtent,
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
from .topic import FieldAddressLike, SessionContext, Topic

__all__ = [
    "PLAN_VERSION",
    "TIMESTAMP_FIELD_METADATA_KEY",
    "FieldAddress",
    "FieldAddressLike",
    "ReadPlan",
    "ReadPlanExtent",
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
    "TimeWindow",
    "Topic",
    "timestamp_column_index",
]
