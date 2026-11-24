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

TRIGGER_NAME_PATTERN = r"^[\w\-]+$"
"""Regular expression a trigger name must match: letters, digits, underscores and hyphens only."""

MAX_TRIGGER_NAME_LENGTH = 256
"""Maximum length of a trigger name, in characters."""


class CreateTriggerRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.triggers.Trigger.create`.

    Roboto assigns the trigger's ID, creator and timestamps. It rejects a trigger whose parts do not fit together,
    by the rules :py:class:`~roboto.domain.triggers.TriggerValidator` checks: for example, a condition or target
    placeholder that names a record some subscribed event does not expose, or a ``once_per`` that some subscribed
    event does not support.

    Building the request raises ``pydantic.ValidationError`` when ``name`` breaks its character or length limit.

    The trigger's targets run as the organization's actions service user, never as the trigger's creator or anyone
    else.
    """

    name: str = pydantic.Field(pattern=TRIGGER_NAME_PATTERN, max_length=MAX_TRIGGER_NAME_LENGTH)
    """Human-readable name of the trigger, unique within its organization.

    It may contain letters, digits, underscores and hyphens only, and is at most 256 characters long
    (:py:const:`~roboto.domain.triggers.MAX_TRIGGER_NAME_LENGTH`).
    """

    fires_on: TriggerSource
    """What makes the trigger fire: a subscription to platform events, or a cron schedule."""

    condition: typing.Optional[ConditionType] = None
    """Condition a firing must meet for the trigger to dispatch its targets.

    The condition is evaluated over the records the firing's event exposes, such as fields under ``dataset.``.
    ``None`` dispatches on every firing.
    """

    targets: list[TriggerTargetSpec]
    """Targets the trigger dispatches when it fires.

    At least one, each with a ``target_id`` unique within the trigger.
    """

    enabled: bool = True
    """Whether the trigger is active once created.

    If enabling it would put the organization over its limit of active triggers, Roboto creates it disabled instead.
    """


class UpdateTriggerRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.triggers.Trigger.update`.

    A field left unset (``NotSet``) is unchanged. The updated trigger must still pass every rule
    :py:class:`~roboto.domain.triggers.TriggerValidator` checks.

    Building the request raises ``pydantic.ValidationError`` when ``name`` breaks its character or length limit.
    """

    name: typing.Union[
        typing.Annotated[
            str, pydantic.StringConstraints(pattern=TRIGGER_NAME_PATTERN, max_length=MAX_TRIGGER_NAME_LENGTH)
        ],
        NotSetType,
    ] = NotSet
    """New human-readable name of the trigger, unique within its organization.

    The same character and length limits apply as on create. Afterward
    :py:meth:`~roboto.domain.triggers.Trigger.from_name` finds the trigger only under this name; its ``trigger_id``
    does not change.
    """

    fires_on: typing.Union[TriggerSource, NotSetType] = NotSet
    """Firing source that replaces the current one whole.

    An event subscription's events and ``once_per`` change together, and the trigger may switch between platform
    events and a schedule.
    """

    condition: typing.Optional[typing.Union[ConditionType, NotSetType]] = NotSet
    """New condition. ``None`` clears it, so the trigger dispatches on every firing."""

    targets: typing.Union[list[TriggerTargetSpec], NotSetType] = NotSet
    """Target list that replaces the current one.

    Roboto keeps which entities a target already fired for under its ``target_id``, so a target given a new
    ``target_id`` fires again for them.
    """

    enabled: typing.Union[bool, NotSetType] = NotSet
    """Whether the trigger is active.

    Enabling it fails with ``RobotoLimitExceededException`` when the organization is at its limit of active triggers.
    """

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


__all__ = [
    "MAX_TRIGGER_NAME_LENGTH",
    "TRIGGER_NAME_PATTERN",
    "CreateTriggerRequest",
    "UpdateTriggerRequest",
]
