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
    """Status of a dispatch: one attempt to run one of a trigger's targets for one matched platform event.

    Roboto may deliver a platform event to a trigger more than once, such as after a failure, so a slot whose dispatch
    failed or was abandoned can be claimed again and its target retried.
    """

    Claimed = "claimed"
    """The dispatch has claimed its slot, and its target is running or about to run.

    A claim that has not finished after five minutes is presumed abandoned, and a redelivery of the platform event may
    claim the slot again, so a target can run twice for one platform event.
    """

    Dispatched = "dispatched"
    """The target ran, or had already run for this slot.

    ``TriggerDispatchRecord.result_ref`` names what it produced when it ran.
    """

    Failed = "failed"
    """The target failed or was rejected. A redelivery of the platform event may claim the slot again."""

    Unknown = "unknown"
    """The claim never finished and no redelivery claimed the slot again, so the target's outcome cannot be determined.

    Roboto moves a claim to this status after about two hours, and never claims the slot again.
    """


@dataclasses.dataclass(frozen=True)
class DispatchSlot:
    """Slot a dispatch occupies: one target of one trigger, for the platform events that share one idempotency token.

    Roboto keeps one dispatch record per slot, and a retry of the slot replaces it. Returned by
    ``TriggerDispatchRecord.slot``.
    """

    trigger_id: str
    """ID of the trigger."""

    idempotency_token: str
    """Token that identifies the matched platform event at the trigger's ``once_per``.

    For example, ``file.uploaded|dataset:ds_12345``.
    """

    target_id: str
    """ID of the target, unique within the trigger."""


class TriggerDispatchRecord(pydantic.BaseModel):
    """Data record of a trigger dispatch, as the Roboto API returns it.

    A dispatch is one attempt to run one of a trigger's targets for a platform event that matched the trigger. The
    trigger's ``once_per`` (a :py:class:`~roboto.domain.platform_events.OncePer`) decides which platform events share an
    idempotency token, and Roboto runs each target at most once per token, except when it retries a slot whose dispatch
    failed or was abandoned. :py:meth:`~roboto.domain.triggers.Trigger.dispatches` returns these records.
    """

    trigger_id: str
    """ID of the trigger this dispatch belongs to."""

    idempotency_token: str
    """Token that identifies the matched platform event at the trigger's ``once_per``.

    It has the form ``<event type>|<once_per>:<value>``, such as ``file.uploaded|dataset:ds_12345``.
    """

    target_id: str
    """ID of the target this dispatch ran, unique within the trigger."""

    org_id: str
    """ID of the organization that owns the trigger."""

    target_type: TriggerTargetType
    """Kind of target this dispatch ran, which decides what ``result_ref`` holds."""

    event_type: PlatformEventType
    """Type of the matched platform event."""

    event_id: str
    """ID of the platform event that last claimed this slot.

    A retry can come from another platform event with the same token, such as an upload of another file to the same
    dataset at ``once_per=dataset``.
    """

    subject: str
    """Entity the platform event in ``event_id`` is about, as a ``roboto://`` URI such as ``roboto://file/fl_12345``."""

    dataset_id: typing.Optional[str] = None
    """ID of the dataset the platform event is about, or of the dataset that holds the file it is about.

    ``None`` for a platform event about anything else, such as an invocation or a session.
    """

    status: TriggerDispatchStatus
    """Status of the dispatch."""

    status_detail: typing.Optional[str] = None
    """Human-readable detail on ``status``, such as the error a failed target raised, or ``None`` if there is none."""

    result_ref: typing.Optional[str] = None
    """What the target produced, by ``target_type``: an invocation ID, an agent thread ID, or a Slack message timestamp.

    ``None`` until ``status`` is ``TriggerDispatchStatus.Dispatched``, after a failure, and when the action invocation
    or agent thread already existed for this slot, so the target did not run again.
    """

    claimed_at: datetime.datetime
    """Time the slot was last claimed."""

    finalized_at: typing.Optional[datetime.datetime] = None
    """Time the dispatch reached a final status.

    ``None`` while ``status`` is ``TriggerDispatchStatus.Claimed``.
    """

    @property
    def slot(self) -> DispatchSlot:
        """Slot this dispatch occupies."""
        return DispatchSlot(self.trigger_id, self.idempotency_token, self.target_id)

    @property
    def subject_uri(self) -> RobotoUri:
        """Same value as ``subject``, parsed as a :py:class:`~roboto.uri.RobotoUri`."""
        return RobotoUri.parse(self.subject)


__all__ = [
    "DispatchSlot",
    "TriggerDispatchRecord",
    "TriggerDispatchStatus",
]
