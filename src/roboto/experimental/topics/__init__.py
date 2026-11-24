# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Topics: sequences of structured time-series data, called messages, identified by name across the files that log them.

Unlike :py:mod:`roboto.domain.topics`, where each file has its own topic of a given name, a ``Topic`` here holds the
data every file in an organization logs under one topic name. Use ``Topic`` to read a topic's messages as
dictionaries, a pandas DataFrame or Arrow record batches, and to anchor its data in a session to wall-clock time; a
``TopicContext`` limits those operations to the topic's data in one session, event, file, dataset or device, as on
the ``Topic`` that :py:meth:`~roboto.experimental.sessions.Session.get_topic` returns.
"""

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
