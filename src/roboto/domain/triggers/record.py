# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...query import ConditionType
from .sources import TriggerSource
from .targets import TriggerTargetSpec


class TriggerRecord(pydantic.BaseModel):
    """Wire-transmissible representation of a trigger.

    A firing source (a platform event subscription or a schedule), an optional
    condition over the firing's namespace, and the targets to dispatch on a match.
    Cross-field rules — exposed roots, ``once_per`` legality, template placeholders —
    are enforced when the trigger is saved, by
    :class:`~roboto.domain.triggers.TriggerValidator`.

    Triggered work runs as the organization's actions service user; a trigger cannot
    run its targets as anyone else.
    """

    trigger_id: str
    """Unique identifier for the trigger."""

    org_id: str
    """Organization that owns the trigger and whose events it sees."""

    name: str
    """Human-readable name. Unique within :attr:`org_id`."""

    enabled: bool = True
    """Whether the trigger is active."""

    fires_on: TriggerSource
    """What makes the trigger fire: an :class:`~roboto.domain.triggers.EventSubscription`
    (which also carries ``once_per``) or a :class:`~roboto.domain.triggers.Schedule`."""

    condition: typing.Optional[ConditionType] = None
    """Optional predicate over the firing's namespace; the trigger fires only when it
    holds. Same :class:`~roboto.query.Condition` wire format the query system uses."""

    targets: list[TriggerTargetSpec]
    """What the trigger dispatches when it fires, in order. At least one; each
    ``target_id`` is unique within the trigger."""

    engine: str = "v1"
    """Which engine evaluates this trigger: ``"v2"`` for the events/``once_per``/targets
    engine this module models (every trigger, once a deployment has cut over),
    ``"v1"`` for a trigger the older ``causes``/``for_each`` engine still evaluates,
    projected onto this shape. Server-assigned and read-only; no request model
    carries it. Defaults to ``"v1"`` for a response that omits it, which is what a
    Roboto deployment older than the field sends."""

    created: datetime.datetime
    """Timestamp when the trigger was created."""

    created_by: str
    """User ID who created the trigger."""

    modified: datetime.datetime
    """Timestamp when the trigger was last modified."""

    modified_by: str
    """User ID who last modified the trigger."""


__all__ = ["TriggerRecord"]
