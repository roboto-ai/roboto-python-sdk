# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Topics: sequences of structured time-series data, called messages, linked to a source file.

Use :py:class:`~roboto.domain.topics.Topic` to find a file's or dataset's topics and read their messages,
:py:class:`~roboto.domain.topics.MessagePath` to read the data of one field within those messages, and
``TopicSchema`` to look up the fields that make up a topic's messages.
"""

from .message_path import MessagePath
from .operations import (
    AddMessagePathRepresentationRequest,
    AddMessagePathRequest,
    CreateTopicRequest,
    DeleteMessagePathRequest,
    MessagePathChangeset,
    SetDefaultRepresentationRequest,
    SetTimelineOffsetsRequest,
    TimelineOffsetEntry,
    TimelineSourceUpdate,
    UpdateMessagePathRequest,
    UpdateTopicRequest,
)
from .record import (
    CanonicalDataType,
    MessagePathMetadataWellKnown,
    MessagePathRecord,
    MessagePathRepresentationMapping,
    MessagePathStatistic,
    RepresentationRecord,
    RepresentationSelector,
    RepresentationStorageFormat,
    SchemaFieldRecord,
    TimelineExtentRecord,
    TimelineSourceKind,
    TimelineSourceRecord,
    TopicIdentityRecord,
    TopicPartitionRecord,
    TopicRecord,
    TopicSchemaRecord,
    TopicTimeBounds,
    TransformationKind,
)
from .topic import Topic
from .topic_data_service import TopicDataService
from .topic_reader import Timestamp
from .topic_schema import TopicSchema

__all__ = (
    "AddMessagePathRequest",
    "AddMessagePathRepresentationRequest",
    "CreateTopicRequest",
    "CanonicalDataType",
    "DeleteMessagePathRequest",
    "MessagePath",
    "MessagePathChangeset",
    "MessagePathRepresentationMapping",
    "MessagePathRecord",
    "MessagePathStatistic",
    "MessagePathMetadataWellKnown",
    "RepresentationRecord",
    "RepresentationSelector",
    "RepresentationStorageFormat",
    "SchemaFieldRecord",
    "SetDefaultRepresentationRequest",
    "SetTimelineOffsetsRequest",
    "TimelineExtentRecord",
    "TimelineOffsetEntry",
    "TimelineSourceKind",
    "TimelineSourceRecord",
    "TimelineSourceUpdate",
    "Timestamp",
    "Topic",
    "TopicDataService",
    "TopicIdentityRecord",
    "TopicPartitionRecord",
    "TopicRecord",
    "TopicSchema",
    "TopicSchemaRecord",
    "TopicTimeBounds",
    "TransformationKind",
    "UpdateMessagePathRequest",
    "UpdateTopicRequest",
)
