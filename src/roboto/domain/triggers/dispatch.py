# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses
import datetime
import typing

import pydantic

from ...compat import StrEnum
from ...uri import RobotoUri
from ..platform_events import PlatformEventType
from .targets import TriggerTargetType


class TriggerDispatchStatus(StrEnum):
    """Lifecycle state of one dispatch: one attempt to run one target for one matched event."""

    Claimed = "claimed"
    """The dispatch slot is claimed and the target is about to run. A claim that
    neither finalizes nor is reclaimed within the redelivery grace period is presumed
    dead and may be claimed again, so delivery is at-least-once: a target may run
    twice for one event."""

    Dispatched = "dispatched"
    """The target ran; :attr:`TriggerDispatchRecord.result_ref` points at what it produced."""

    Failed = "failed"
    """The target raised; a redelivered event may claim the slot again."""

    Unknown = "unknown"
    """The claim outlived every redelivery of its event without finalizing, so the
    outcome cannot be determined. Set by an operational sweep, never reclaimable."""


@dataclasses.dataclass(frozen=True)
class DispatchSlot:
    """One target of one trigger at one dedup token: the unit a dispatch claims.

    At most one dispatch ever occupies a slot. It is the dispatch table's primary key
    and the vocabulary every dispatch port speaks.
    """

    trigger_id: str
    idempotency_token: str
    target_id: str


class TriggerDispatchRecord(pydantic.BaseModel):
    """Wire-transmissible representation of one trigger dispatch.

    A dispatch is one attempt to run one target of one trigger for one matched
    platform event, deduped at the trigger's :class:`~roboto.domain.platform_events.OncePer`.
    The triple (:attr:`trigger_id`, :attr:`idempotency_token`,
    :attr:`target_id`) is the :class:`DispatchSlot`; at most one dispatch ever
    occupies a slot, which is what makes redelivered events safe.
    """

    trigger_id: str
    """Trigger this dispatch belongs to."""

    idempotency_token: str
    """Dedup token derived from the matched event at the trigger's ``once_per``
    (``{event.type}|{once_per}:{projection}``)."""

    target_id: str
    """Which of the trigger's targets this dispatch ran."""

    org_id: str
    """Organization that owns the trigger."""

    target_type: TriggerTargetType
    """Kind of target dispatched."""

    event_type: PlatformEventType
    """Type of the platform event that matched."""

    event_id: str
    """Id of the platform event occurrence that most recently claimed this slot."""

    subject: str
    """The entity the matched platform event was about, as a ``roboto://`` URI; the
    same value as the event's own ``subject``."""

    dataset_id: typing.Optional[str] = None
    """The dataset the subject belongs to (the subject itself for a dataset event),
    which is what a dataset's page lists dispatches by. ``None`` when the subject has
    no dataset, such as a session or an invocation."""

    status: TriggerDispatchStatus
    """Where this dispatch is in its lifecycle."""

    status_detail: typing.Optional[str] = None
    """Human-readable detail for :attr:`status`, e.g. the error a failed target raised."""

    result_ref: typing.Optional[str] = None
    """What a dispatched target produced: an invocation id, an agent thread id, or a
    Slack message timestamp, per :attr:`target_type`."""

    claimed_at: datetime.datetime
    """When the slot was (most recently) claimed."""

    finalized_at: typing.Optional[datetime.datetime] = None
    """When the dispatch reached a terminal status; ``None`` while claimed."""

    @property
    def slot(self) -> DispatchSlot:
        """The slot this dispatch occupies."""
        return DispatchSlot(self.trigger_id, self.idempotency_token, self.target_id)

    @property
    def subject_uri(self) -> RobotoUri:
        """:attr:`subject` as a parsed :class:`~roboto.uri.RobotoUri`."""
        return RobotoUri.parse(self.subject)


__all__ = [
    "DispatchSlot",
    "TriggerDispatchRecord",
    "TriggerDispatchStatus",
]
