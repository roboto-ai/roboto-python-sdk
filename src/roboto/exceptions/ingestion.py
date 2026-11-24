# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


class IngestionException(Exception):
    """Base class of the exceptions the SDK raises when it cannot create a topic from local data, such as a DataFrame.

    :py:meth:`~roboto.domain.topics.Topic.create_from_df` and :py:meth:`~roboto.domain.files.File.add_topic` raise it
    before creating or updating the topic when the timestamp column is missing, has a type that cannot hold
    timestamps, holds timestamps that are not timezone-aware, or holds numbers and no unit was given. They also raise
    it when the topic's data finishes uploading without Roboto returning an ID for the uploaded file. The message says
    which.
    """


class TimestampFieldNotFoundException(IngestionException):
    """The SDK cannot find the column that holds each row's timestamp.

    :py:meth:`~roboto.domain.topics.Topic.create_from_df` and :py:meth:`~roboto.domain.files.File.add_topic` raise it
    when the named timestamp column is not in the data, or when no column was named and no column's type is a
    timezone-aware timestamp.
    """
