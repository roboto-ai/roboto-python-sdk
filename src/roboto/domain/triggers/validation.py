# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import typing

from ...query import ConditionType
from ...uri import RobotoUriType
from ..platform_events import (
    DEFAULT_PLATFORM_EVENT_CATALOG,
    RESERVED_ROOTS,
    OncePer,
    PlatformEventCatalog,
    PlatformEventType,
)
from .conditions import (
    explicit_root,
    iter_leaf_conditions,
)
from .record import TriggerRecord
from .sources import (
    EventSubscription,
    Schedule,
    TriggerSource,
)
from .targets import (
    InvokeActionTarget,
    TriggerTargetSpec,
)


class TriggerValidator:
    """Save-time validation for triggers.

    Enforces the cross-field rules that need the event catalog: a condition may only
    reference namespace roots exposed by *every* event the source fires for,
    ``once_per`` must be legal for every subscribed event, every target must act on
    the kind of entity the subscription is about, and every target template
    placeholder must resolve to a shared exposed root (or a reserved
    ``envelope.``/``trigger.`` context). A schedule fires for exactly one occurrence type,
    so the same rules apply to it with that occurrence's roots.

    Run before persistence so a trigger that could never fire — or could never
    resolve its templates — fails loudly with an actionable message instead of
    silently misbehaving at evaluation time.
    """

    def __init__(self, catalog: PlatformEventCatalog = DEFAULT_PLATFORM_EVENT_CATALOG) -> None:
        """Bind the validator to an event catalog.

        Args:
            catalog: Source of descriptors for the event types a source fires for.
        """
        self.__catalog = catalog

    def validate_record(self, record: TriggerRecord) -> None:
        """Validate a full trigger record.

        Raises:
            ValueError: Any rule in :meth:`validate` fails.
        """
        self.validate(fires_on=record.fires_on, condition=record.condition, targets=record.targets)

    def validate(
        self,
        *,
        fires_on: TriggerSource,
        condition: typing.Optional[ConditionType],
        targets: collections.abc.Sequence[TriggerTargetSpec],
    ) -> None:
        """Validate the cross-field rules for one trigger's parts.

        Args:
            fires_on: The trigger's firing source.
            condition: Optional predicate over the firing's namespace.
            targets: The trigger's target specs.

        Raises:
            ValueError: The first rule that fails, with a message naming the offending
                field, root, or event.
        """
        event_types = self.__event_types(fires_on)
        shared_roots = self.__shared_roots(event_types)
        self.__validate_condition(condition, event_types, shared_roots)
        self.__validate_targets(targets, fires_on, shared_roots, self.__subject_type(fires_on))

    def __event_types(self, fires_on: TriggerSource) -> list[PlatformEventType]:
        """The event types the source fires for, after validating the source itself."""
        if isinstance(fires_on, Schedule):
            return [PlatformEventType.ScheduleFired]
        self.__validate_subscription(fires_on)
        return list(fires_on.events)

    def __validate_subscription(self, subscription: EventSubscription) -> None:
        if not subscription.events:
            raise ValueError("A trigger must subscribe to at least one platform event.")
        for event_type in subscription.events:
            if event_type not in self.__catalog:
                raise ValueError(f"Unknown platform event type {event_type.value!r}.")
            descriptor = self.__catalog.descriptor(event_type)
            if not descriptor.subscribable:
                raise ValueError(
                    f"Platform event type {event_type.value!r} cannot be subscribed to; "
                    "a trigger fires on a schedule by declaring a schedule source."
                )
            if not descriptor.supports_once_per(subscription.once_per):
                supported = sorted(member.value for member in descriptor.supported_once_per)
                raise ValueError(
                    f"once_per={subscription.once_per.value!r} is not legal for subscribed event "
                    f"{event_type.value!r}; it supports: {supported}."
                )
        subject_types = {self.__catalog.descriptor(event_type).subject_type for event_type in subscription.events}
        if len(subject_types) > 1:
            # Every subscribed type must be about the same kind of entity. Otherwise the
            # condition has no root every event exposes, once_per collapses to
            # occurrence, and an action target has nothing to bind to on the events
            # that carry no dataset. One trigger per entity kind expresses the same intent.
            raise ValueError(
                f"A trigger subscribes to platform events about one kind of entity; "
                f"{sorted(event.value for event in subscription.events)} are about "
                f"{sorted(kind.value for kind in subject_types)}. Create one trigger per entity kind."
            )

    def __subject_type(self, fires_on: TriggerSource) -> typing.Optional[RobotoUriType]:
        """The one kind of entity the subscription's events are about; ``None`` for a schedule."""
        if isinstance(fires_on, Schedule):
            return None
        return self.__catalog.descriptor(fires_on.events[0]).subject_type

    def __shared_roots(self, event_types: collections.abc.Sequence[PlatformEventType]) -> frozenset[str]:
        shared = self.__catalog.exposed_roots(event_types[0])
        for event_type in event_types[1:]:
            shared &= self.__catalog.exposed_roots(event_type)
        return shared

    def __validate_condition(
        self,
        condition: typing.Optional[ConditionType],
        event_types: collections.abc.Sequence[PlatformEventType],
        shared_roots: frozenset[str],
    ) -> None:
        if condition is None:
            return
        default_roots = {self.__catalog.descriptor(event_type).default_root for event_type in event_types}
        for leaf in iter_leaf_conditions(condition):
            root = explicit_root(leaf)
            if root in ("topic", "message_path"):
                raise ValueError(
                    f"Condition field {leaf.field!r} references the {root!r} resource, "
                    "which trigger conditions do not support."
                )
            if root is None:
                if len(default_roots) > 1:
                    raise ValueError(
                        f"Condition field {leaf.field!r} is unqualified, but the subscribed events have "
                        f"different default roots ({sorted(default_roots)}); qualify the field with an "
                        "explicit root (e.g. 'dataset.')."
                    )
                continue
            if root not in shared_roots | RESERVED_ROOTS:
                raise ValueError(
                    f"Condition field {leaf.field!r} references namespace root {root!r}, which is not "
                    f"exposed by every event the trigger fires for; roots shared by "
                    f"{[e.value for e in event_types]}: {sorted(shared_roots)}."
                )

    def __validate_targets(
        self,
        targets: collections.abc.Sequence[TriggerTargetSpec],
        fires_on: TriggerSource,
        shared_roots: frozenset[str],
        subject_type: typing.Optional[RobotoUriType],
    ) -> None:
        if not targets:
            raise ValueError("A trigger must have at least one target.")
        seen_target_ids: set[str] = set()
        for target in targets:
            if target.target_id in seen_target_ids:
                raise ValueError(f"Duplicate target_id {target.target_id!r}; target ids must be unique in a trigger.")
            seen_target_ids.add(target.target_id)
            if (
                subject_type is not None
                and target.subject_types is not None
                and subject_type not in target.subject_types
            ):
                raise ValueError(
                    f"Target {target.target_id!r} ({target.type.value}) acts on "
                    f"{sorted(kind.value for kind in target.subject_types)}, but the subscribed platform events "
                    f"are about {subject_type.value!r}. Use another kind of target, or subscribe to platform "
                    "events about one of those entities."
                )
            if isinstance(fires_on, Schedule) and isinstance(target, InvokeActionTarget) and target.required_inputs:
                raise ValueError(
                    f"Target {target.target_id!r} sets required_inputs, which gate on the firing event's files; "
                    "a schedule fires with no files. Select inputs with invocation_input instead."
                )
            if (
                isinstance(fires_on, EventSubscription)
                and isinstance(target, InvokeActionTarget)
                and subject_type is RobotoUriType.File
                and fires_on.once_per is not OncePer.Dataset
                and not target.required_inputs
            ):
                raise ValueError(
                    f"Target {target.target_id!r} has no required_inputs, but at once_per={fires_on.once_per.value!r} "
                    "the firing event's file is the action's input and must match one of them, so the target "
                    "would never accept an event. Add a required_inputs pattern, or use once_per=dataset."
                )
            allowed_roots = shared_roots | RESERVED_ROOTS
            for placeholder in sorted(target.referenced_placeholders()):
                root = placeholder.split(".", 1)[0]
                if root not in allowed_roots:
                    raise ValueError(
                        f"Target {target.target_id!r} references placeholder {{{{{placeholder}}}}}, whose "
                        f"root {root!r} is not exposed by every event the trigger fires for; available roots: "
                        f"{sorted(allowed_roots)}."
                    )


__all__ = [
    "TriggerValidator",
]
