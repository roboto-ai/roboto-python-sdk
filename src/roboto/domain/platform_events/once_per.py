# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ...compat import StrEnum


class OncePer(StrEnum):
    """Value of a trigger's ``once_per``: what it runs each target at most once for.

    Either each platform event, or a resource the platform event names. With ``once_per`` set to ``File``, for example,
    a trigger on the :py:class:`~roboto.domain.platform_events.PlatformEventType` member ``FileMetadataUpdated`` runs
    its targets for the first metadata change to a file and not for later changes to that file. The limit applies to
    each event type separately, so a trigger on both ``FileUploaded`` and ``FileIngested`` with ``once_per`` set to
    ``File`` can run twice per file, once for each event type.

    Each event type supports ``Occurrence`` and some of the resources its payload names;
    :py:attr:`~roboto.domain.platform_events.PlatformEventDescriptor.supported_once_per` lists which. Roboto rejects a
    trigger whose ``once_per`` one of its subscribed event types does not support.
    """

    Occurrence = "occurrence"
    """Each platform event, so the trigger runs for every one and once for a platform event delivered twice.

    Every event type supports it.
    """

    File = "file"
    """Files (:py:class:`~roboto.domain.files.File`) the platform event names.

    Supported by the :py:class:`~roboto.domain.platform_events.PlatformEventType` members ``FileUploaded``,
    ``FileIngested`` and ``FileMetadataUpdated``.
    """

    Dataset = "dataset"
    """Datasets (:py:class:`~roboto.domain.datasets.Dataset`) the platform event names.

    The dataset the platform event is about, or the dataset of the file it is about. Supported by every event type
    about a file or a dataset except :py:attr:`~roboto.domain.platform_events.PlatformEventType.DatasetTagAdded`.
    """

    Invocation = "invocation"
    """Action invocations (:py:class:`~roboto.domain.actions.Invocation`) the platform event names.

    Supported by :py:attr:`~roboto.domain.platform_events.PlatformEventType.InvocationCompleted` and
    :py:attr:`~roboto.domain.platform_events.PlatformEventType.InvocationFailed`.
    """

    Event = "event"
    """Events (:py:class:`~roboto.domain.events.Event`), annotations over a span of time, that the platform event names.

    Supported by :py:attr:`~roboto.domain.platform_events.PlatformEventType.EventCreated` and
    :py:attr:`~roboto.domain.platform_events.PlatformEventType.SessionEventCreated`.
    """


__all__ = ["OncePer"]
