# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Describe what an uploaded file carries, so the platform can register it without opening the file.

A caller declares the topics a file contributes data to, what each of them carries, and which files a read
of each opens; the types that compose those files into sessions live in :py:mod:`roboto.experimental.sessions`.
"""

from .operations import (
    MAX_FILES_AND_TOPICS_PER_REQUEST,
    MESSAGE_ENVELOPE_TIMELINE_SOURCES,
    DeclaredTimelineSource,
    FileTopicDeclaration,
    McapLogTimeSource,
    McapPublishTimeSource,
    Mp4PresentationTimeSource,
    RepresentationDeclaration,
    SchemaFieldSource,
    TopicDeclaration,
    TopicRepresentations,
)
from .schema import Field, Schema

__all__ = (
    "MAX_FILES_AND_TOPICS_PER_REQUEST",
    "MESSAGE_ENVELOPE_TIMELINE_SOURCES",
    "DeclaredTimelineSource",
    "Field",
    "FileTopicDeclaration",
    "McapLogTimeSource",
    "McapPublishTimeSource",
    "Mp4PresentationTimeSource",
    "RepresentationDeclaration",
    "Schema",
    "SchemaFieldSource",
    "TopicDeclaration",
    "TopicRepresentations",
)
