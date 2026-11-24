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
    DATASET_ROOT,
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
from .query_templates import (
    iter_query_templates,
    placeholders_outside_string_literals,
)
from .record import (
    ManagedBy,
    ManagedByKind,
    TriggerRecord,
)
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
    """Checker for the rules that span a trigger's source, condition and targets.

    Roboto runs these checks whenever a trigger is created or updated, and rejects a trigger that fails one with
    ``RobotoInvalidRequestException`` carrying the check's message, so a trigger that could never fire or never fill in
    its templates is refused when it is saved. Call ``validate`` to run the same checks before saving a trigger.

    A trigger passes when:

    - Its event subscription names at least one platform event, and each is a type the catalog knows, that triggers
      may subscribe to, and that supports the subscription's ``once_per``. All are about the same kind of entity.
    - Each condition field names a root that every subscribed event exposes, or ``envelope`` or ``trigger``, which
      every firing has. No field names ``topic.`` or ``msgpath.``, and a field that names no root is allowed only when
      every subscribed event has the same default root.
    - It has at least one target, and each ``target_id`` is unique within it.
    - An action target sets ``required_inputs`` or ``additional_inputs`` only when every subscribed event exposes
      ``dataset``, because those patterns match files of the event's dataset.
    - An action target on events about a file sets ``required_inputs`` unless ``once_per`` is
      :py:attr:`~roboto.domain.platform_events.OncePer.Dataset` or an ingestion rule manages the trigger, because the
      event's file is the action's input and must match one of them.
    - Every ``{{<name>}}`` placeholder in an ``invocation_input`` query sits inside a quoted value.
    - Every placeholder in a target names a root that every subscribed event exposes, or ``envelope`` or ``trigger``.

    A schedule fires for one platform event type,
    :py:attr:`~roboto.domain.platform_events.PlatformEventType.ScheduleFired`, so the same checks apply to it with
    that type's roots.

    Args:
        catalog: Descriptors of the platform event types, which give each type's roots and supported ``once_per``
            values. Defaults to :py:const:`~roboto.domain.platform_events.DEFAULT_PLATFORM_EVENT_CATALOG`.
    """

    def __init__(self, catalog: PlatformEventCatalog = DEFAULT_PLATFORM_EVENT_CATALOG) -> None:
        self.__catalog = catalog

    def validate_record(self, record: TriggerRecord) -> None:
        """Reject a trigger record that breaks one of the rules ``validate`` checks.

        It has no failures of its own; the ``ValueError`` that ``validate`` raises when a rule fails applies.

        Args:
            record: Trigger record to check.
        """
        self.validate(
            fires_on=record.fires_on,
            condition=record.condition,
            targets=record.targets,
            managed_by=record.managed_by,
        )

    def validate(
        self,
        *,
        fires_on: TriggerSource,
        condition: typing.Optional[ConditionType],
        targets: collections.abc.Sequence[TriggerTargetSpec],
        managed_by: typing.Optional[ManagedBy] = None,
    ) -> None:
        """Reject a trigger whose source, condition or targets break a rule, raising at the first rule that fails.

        Args:
            fires_on: What makes the trigger fire: an :py:class:`~roboto.domain.triggers.EventSubscription` or a
                :py:class:`~roboto.domain.triggers.Schedule`.
            condition: Condition over the variables a firing exposes. ``None`` skips the condition checks.
            targets: Targets the trigger runs when it fires.
            managed_by: Owner that manages the trigger, or ``None`` if the organization's members manage it. A trigger
                an ingestion rule manages runs only on the files the rule's path patterns match, so its action targets
                on events about a file need no ``required_inputs``.

        Raises:
            ValueError: A rule fails. The message names the field, root, or event at fault.
        """
        event_types = self.__event_types(fires_on)
        shared_roots = self.__shared_roots(event_types)
        self.__validate_condition(condition, event_types, shared_roots)
        owner_gates_files = managed_by is not None and managed_by.kind is ManagedByKind.IngestionRule
        self.__validate_targets(
            targets, fires_on, event_types, shared_roots, self.__subject_type(fires_on), owner_gates_files
        )

    def __event_types(self, fires_on: TriggerSource) -> list[PlatformEventType]:
        """Return the event types ``fires_on`` fires for, after checking an event subscription's own rules."""
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
            # __subject_type reads the kind of entity from the first subscribed event only, and the
            # required_inputs check in __validate_targets depends on that kind.
            raise ValueError(
                f"A trigger subscribes to platform events about one kind of entity; "
                f"{sorted(event.value for event in subscription.events)} are about "
                f"{sorted(kind.value for kind in subject_types)}. Create one trigger per entity kind."
            )

    def __subject_type(self, fires_on: TriggerSource) -> typing.Optional[RobotoUriType]:
        """Return the kind of entity the subscribed events are about, or ``None`` for a schedule."""
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

    def __no_dataset_clause(
        self,
        fires_on: TriggerSource,
        event_types: collections.abc.Sequence[PlatformEventType],
        shared_roots: frozenset[str],
    ) -> str:
        """Return the error-message clause saying why the firing names no dataset, worded for ``fires_on``."""
        if isinstance(fires_on, Schedule):
            return (
                f"the trigger fires on a schedule, which names no {DATASET_ROOT}; "
                f"available roots: {sorted(shared_roots)}"
            )
        without_dataset = sorted(
            event_type.value
            for event_type in event_types
            if DATASET_ROOT not in self.__catalog.exposed_roots(event_type)
        )
        return (
            f"the subscribed events {without_dataset} name no {DATASET_ROOT}; roots shared by "
            f"every event the trigger fires for: {sorted(shared_roots)}"
        )

    def __validate_targets(
        self,
        targets: collections.abc.Sequence[TriggerTargetSpec],
        fires_on: TriggerSource,
        event_types: collections.abc.Sequence[PlatformEventType],
        shared_roots: frozenset[str],
        subject_type: typing.Optional[RobotoUriType],
        owner_gates_files: bool,
    ) -> None:
        if not targets:
            raise ValueError("A trigger must have at least one target.")
        seen_target_ids: set[str] = set()
        for target in targets:
            if target.target_id in seen_target_ids:
                raise ValueError(f"Duplicate target_id {target.target_id!r}; target ids must be unique in a trigger.")
            seen_target_ids.add(target.target_id)
            if isinstance(target, InvokeActionTarget) and DATASET_ROOT not in shared_roots:
                pattern_fields = [
                    field
                    for field, patterns in (
                        ("required_inputs", target.required_inputs),
                        ("additional_inputs", target.additional_inputs),
                    )
                    if patterns
                ]
                if pattern_fields:
                    raise ValueError(
                        f"Target {target.target_id!r} sets {' and '.join(pattern_fields)}, which match files of the "
                        f"firing event's {DATASET_ROOT}, but "
                        f"{self.__no_dataset_clause(fires_on, event_types, shared_roots)}. "
                        "Select inputs with invocation_input instead."
                    )
            if (
                isinstance(fires_on, EventSubscription)
                and isinstance(target, InvokeActionTarget)
                and subject_type is RobotoUriType.File
                and fires_on.once_per is not OncePer.Dataset
                and not target.required_inputs
                and not owner_gates_files
            ):
                raise ValueError(
                    f"Target {target.target_id!r} has no required_inputs, but at once_per={fires_on.once_per.value!r} "
                    "the firing event's file is the action's input and must match one of them, so the target "
                    "would never accept an event. Add a required_inputs pattern, or use once_per=dataset."
                )
            if isinstance(target, InvokeActionTarget) and target.invocation_input is not None:
                for query in iter_query_templates(target.invocation_input.model_dump(mode="json")):
                    unquoted = placeholders_outside_string_literals(query)
                    if unquoted:
                        raise ValueError(
                            f"Target {target.target_id!r} references "
                            f"{', '.join('{{' + name + '}}' for name in unquoted)} outside a quoted value in the "
                            f"query {query!r}. A value resolved from the event is data, not query syntax, so a "
                            "placeholder must sit inside a quoted value, as in "
                            'dataset_id = "{{dataset.dataset_id}}". A comment does not count as one.'
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
