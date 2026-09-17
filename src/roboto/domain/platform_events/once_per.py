# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ...compat import StrEnum


class OncePer(StrEnum):
    """A grain an event offers for deduplication: the occurrence itself, or an entity the event names.

    This is an event's vocabulary, not a trigger's. Each
    :class:`~roboto.domain.platform_events.PlatformEventType` declares the grains it supports,
    and how an occurrence projects onto each, in its
    :class:`~roboto.domain.platform_events.PlatformEventDescriptor`; that projection is what
    turns one occurrence into one idempotency token. A trigger only chooses among the grains
    its events offer, and its choice must be legal for every event type it subscribes to.
    """

    Occurrence = "occurrence"
    """Fire on every occurrence; nothing collapses. Supported by every event type."""

    File = "file"
    """Fire once per file."""

    Dataset = "dataset"
    """Fire once per dataset."""

    Invocation = "invocation"
    """Fire once per action invocation."""

    Session = "session"
    """Fire once per session."""

    Event = "event"
    """Fire once per event, the annotation marking a span of time on your data."""


__all__ = ["OncePer"]
