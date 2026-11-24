# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum
from ...query import ConditionType
from .sources import TriggerSource
from .targets import TriggerTargetSpec


class ManagedByKind(StrEnum):
    """Kind of owner that manages a trigger in place of the organization's members."""

    System = "system"
    """Roboto, which installed the trigger to run one of its own features, such as computing session metrics."""

    IngestionRule = "ingestion_rule"
    """Ingestion rules (``roboto.experimental.ingestion_rules.IngestionRuleRecord``).

    Each rule owns the trigger that ingests the files the rule matches.
    """


class ManagedBy(pydantic.BaseModel):
    """Owner that manages a trigger's definition in place of the organization's members.

    A managed trigger cannot be deleted, or have its definition changed, through
    :py:class:`~roboto.domain.triggers.Trigger`. Members of the organization can still enable or disable a trigger
    Roboto manages. A trigger an ingestion rule owns cannot be enabled, disabled, edited or deleted directly; change
    the rule instead, such as by turning its auto-ingest off. An organization has at most one trigger per owner.

    Carried in ``TriggerRecord.managed_by``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    kind: ManagedByKind
    """Kind of owner that manages the trigger."""

    id: str
    """ID of the owner, whose meaning depends on the owner's kind.

    For ``ManagedByKind.System``, it is the key of the Roboto feature, such as ``"session_metrics"``; for
    ``ManagedByKind.IngestionRule``, it is the rule's ID.
    """


class TriggerRecord(pydantic.BaseModel):
    """Data record of a trigger, as the Roboto API returns it.

    A trigger is a rule that responds to activity in an organization. It has a firing source (a subscription to
    platform events, or a schedule), an optional condition over the variables a firing exposes, and the targets to
    run when the condition holds. :py:class:`~roboto.domain.triggers.Trigger` wraps this record with methods that act
    on the trigger, and exposes it as :py:attr:`~roboto.domain.triggers.Trigger.record`.

    When a trigger is saved, Roboto checks the rules that span its fields with
    :py:class:`~roboto.domain.triggers.TriggerValidator`: the condition references only variables every subscribed
    platform event exposes, :py:attr:`~roboto.domain.triggers.EventSubscription.once_per` is legal for every
    subscribed event, and every target template placeholder resolves. A trigger's targets run as its organization's
    service user, never as the user who created the trigger.
    """

    trigger_id: str
    """Unique ID of the trigger."""

    org_id: str
    """ID of the organization that owns the trigger.

    An event-fired trigger fires only on that organization's platform events.
    """

    name: str
    """Human-readable name of the trigger, unique within its organization."""

    enabled: bool = True
    """Whether the trigger is enabled. A disabled trigger does not fire."""

    fires_on: TriggerSource
    """What makes the trigger fire: a subscription to platform events, or a schedule.

    The value is an :py:class:`~roboto.domain.triggers.EventSubscription`, which also carries
    :py:attr:`~roboto.domain.triggers.EventSubscription.once_per`, or a
    :py:class:`~roboto.domain.triggers.Schedule`.
    """

    condition: typing.Optional[ConditionType] = None
    """Condition over the variables a firing exposes, which must hold for the trigger to run its targets.

    It takes the :py:class:`~roboto.query.Condition` format Roboto's queries use. ``None`` runs the targets on every
    firing.
    """

    targets: list[TriggerTargetSpec]
    """Targets the trigger runs when it fires. At least one; each ``target_id`` is unique within the trigger."""

    engine: str = "v1"
    """Trigger model Roboto evaluates the trigger with, ``"v2"`` or ``"v1"``.

    ``"v2"`` is the model of this package; ``"v1"`` is the deprecated ``causes``/``for_each`` model of
    :py:class:`~roboto.domain.actions.Trigger`.

    Roboto sets it; no request does. It defaults to ``"v1"`` when a response omits it, as a response from a
    Roboto deployment that predates the field does.
    """

    managed_by: typing.Optional[ManagedBy] = None
    """Owner that manages the trigger's definition, or ``None`` if the organization's members manage it.

    One such owner is the ingestion rule the trigger ingests files for. Roboto sets it; no request does.
    """

    created: datetime.datetime
    """Time the trigger was created."""

    created_by: str
    """ID of the user who created the trigger.

    Roboto's own system user when Roboto made the change.
    """

    modified: datetime.datetime
    """Time the trigger was last modified."""

    modified_by: str
    """ID of the user who last modified the trigger.

    Roboto's own system user when Roboto made the change. Roboto modifies a trigger when it disables the trigger,
    such as after one of its targets' actions was deleted.
    """


__all__ = ["ManagedBy", "ManagedByKind", "TriggerRecord"]
