# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Declarations of the topic data an uploaded file carries, which Roboto registers without opening the file.

A declaration states each topic's name, its :py:class:`~roboto.experimental.ingest.Schema`, the timeline sources its
data carries with their bounds, and the files a read of the topic opens. Pass
:py:class:`~roboto.experimental.ingest.TopicDeclaration` objects to a
:py:class:`~roboto.experimental.sessions.SessionFile` to declare a file's topics as part of a session,
:py:class:`~roboto.experimental.ingest.FileTopicDeclaration` to :py:meth:`~roboto.domain.files.File.declare_topics` to
declare them without naming a session, and :py:class:`~roboto.experimental.ingest.TopicRepresentations` to
:py:meth:`~roboto.domain.files.File.set_representations` to replace the files a read of a topic opens.
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
