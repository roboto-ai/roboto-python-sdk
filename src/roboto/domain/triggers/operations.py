# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...query import ConditionType
from ...sentinels import NotSet, NotSetType
from .sources import TriggerSource
from .targets import TriggerTargetSpec

TRIGGER_NAME_PATTERN = r"[\w\-]+"
"""Legal trigger names: word characters and hyphens."""

MAX_TRIGGER_NAME_LENGTH = 256
"""Maximum trigger name length."""


class CreateTriggerRequest(pydantic.BaseModel):
    """Request payload to create a trigger.

    The server assigns identity and audit fields, and runs
    :class:`~roboto.domain.triggers.TriggerValidator` over the cross-field rules
    (exposed roots, ``once_per`` legality, target placeholders) before persisting.

    Triggered work runs as the organization's actions service user; a trigger cannot
    run its targets as anyone else.
    """

    name: str = pydantic.Field(pattern=TRIGGER_NAME_PATTERN, max_length=MAX_TRIGGER_NAME_LENGTH)
    """Trigger name. Unique within the caller's organization."""

    fires_on: TriggerSource
    """What makes the trigger fire: an event subscription or a schedule."""

    condition: typing.Optional[ConditionType] = None
    """Optional predicate over the firing's namespace."""

    targets: list[TriggerTargetSpec]
    """What the trigger dispatches when it fires. At least one."""

    enabled: bool = True
    """Whether the trigger should be active immediately after creation."""


class UpdateTriggerRequest(pydantic.BaseModel):
    """Request payload to update a trigger.

    Only fields explicitly provided are changed; the :class:`~roboto.sentinels.NotSetType`
    sentinel distinguishes "field omitted" from "field set to ``None``". The updated
    record must still satisfy every :class:`~roboto.domain.triggers.TriggerValidator`
    rule.
    """

    fires_on: typing.Union[TriggerSource, NotSetType] = NotSet
    """New firing source. Replaces the whole source: an event subscription's events
    and ``once_per`` change together, and a trigger may switch between events and a
    schedule."""

    condition: typing.Optional[typing.Union[ConditionType, NotSetType]] = NotSet
    """New condition; explicit ``None`` clears it."""

    targets: typing.Union[list[TriggerTargetSpec], NotSetType] = NotSet
    """New target list. A target whose ``target_id`` is referenced by existing
    dispatches must keep that id."""

    enabled: typing.Union[bool, NotSetType] = NotSet
    """New enabled status."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


__all__ = [
    "MAX_TRIGGER_NAME_LENGTH",
    "TRIGGER_NAME_PATTERN",
    "CreateTriggerRequest",
    "UpdateTriggerRequest",
]
