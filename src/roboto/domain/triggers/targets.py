# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...ai.agent_thread.record import (
    ThreadVisibility,
)
from ...ai.core import AnalysisScope
from ...compat import StrEnum
from ...pydantic import (
    validate_nonzero_gitpath_specs,
)
from ...templating import collect_placeholders
from ..actions.action_record import (
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
)
from ..actions.invocation_record import (
    InvocationInput,
    InvocationUploadDestination,
)

_FROZEN = pydantic.ConfigDict(frozen=True)


class TriggerTargetType(StrEnum):
    """Kind of target, the ``type`` of each ``TriggerTargetSpec``."""

    InvokeAction = "invoke_action"
    """Invocation of an action."""

    StartAgent = "start_agent"
    """Agent thread started from a saved agent."""

    SendSlackMessage = "send_slack_message"
    """Message posted to a Slack channel the organization allows Roboto to post to."""


class _TargetSpecBase(pydantic.BaseModel):
    """Common base for targets.

    Marks ``type`` as set at construction, because the SDK serializes request bodies with ``exclude_unset``, and a
    target sent without ``type`` cannot be parsed back into :py:const:`~roboto.domain.triggers.TriggerTargetSpec`.
    """

    def model_post_init(self, __context: typing.Any) -> None:
        self.__pydantic_fields_set__.add("type")


class ActionInvocationSpec(pydantic.BaseModel):
    """How to invoke an action: the action, its parameter values, its inputs, and overrides of its settings.

    It says what to run but not when. ``InvokeActionTarget`` extends it with a target's ID and file patterns, and an
    ingestion rule stores one for the action it runs on the files it matches.

    Strings in ``parameter_values`` and ``invocation_input`` may contain ``{{...}}`` placeholders, such as
    ``{{dataset.dataset_id}}``, which Roboto fills from the platform event that fired the trigger; see
    :py:class:`~roboto.domain.triggers.EventNamespace`.
    """

    model_config = _FROZEN

    action: ActionReference
    """Action to invoke.

    An ``owner`` of ``None`` means the trigger's organization, and a ``digest`` of ``None`` the action's latest version.
    """

    invocation_input: typing.Optional[InvocationInput] = None
    """Files, topics, or sessions the invocation reads, chosen by query, ID, or name when it runs.

    For example, ``InvocationInput.file_query('tags CONTAINS "{{event.name}}"')``. A trigger whose platform events
    name no dataset selects its inputs only this way. On an event that names a dataset, these inputs are read along
    with the files the target's patterns match.
    """

    parameter_values: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Values of the action's parameters, keyed by parameter name. Any string among them may contain placeholders."""

    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    """Compute requirements, such as vCPU and memory, that replace the action's own.

    ``None`` uses the action's own.
    """

    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    """Container parameters, such as the entry point and environment variables, that replace the action's own.

    ``None`` uses the action's own.
    """

    timeout: typing.Optional[int] = None
    """Maximum time the invocation may run, in minutes. ``None`` uses the action's own."""

    upload_destination: typing.Optional[InvocationUploadDestination] = None
    """Where Roboto uploads the files the invocation writes to its output directory.

    ``None`` uploads them to the dataset the platform event names. On an event that names no dataset, ``None``
    uploads them to the dataset the inputs come from when they all come from one, and otherwise not at all.
    """

    def referenced_placeholders(self) -> set[str]:
        """Return the name of every placeholder in ``parameter_values`` and ``invocation_input``.

        Returns:
            Placeholder names without their braces, such as ``dataset.dataset_id``.

        Raises:
            ValueError: A key in ``parameter_values`` contains placeholder syntax.
        """
        return collect_placeholders(self.parameter_values) | collect_placeholders(
            self.invocation_input.model_dump(mode="json") if self.invocation_input is not None else {}
        )


class InvokeActionTarget(ActionInvocationSpec, _TargetSpecBase):
    """Target that invokes an action when its trigger fires.

    The fields it shares with ``ActionInvocationSpec`` say how to run the action.
    This class adds the target's ID and the gitignore-style patterns that pick files from the platform event's
    dataset, whose strings may contain placeholders too. What the invocation reads depends on the platform event:

    - An event that names a dataset, such as a file upload, invokes the action on that dataset. ``required_inputs``
      decides whether the target runs, and the files it and ``additional_inputs`` match are inputs, along with any
      ``invocation_input``.
    - An event that names no dataset, such as a schedule firing or an invocation finishing, invokes the action on no
      dataset, and it reads what ``invocation_input`` selects. ``required_inputs`` and ``additional_inputs`` must be
      empty.

    Constructing a target whose ``type`` is not ``InvokeAction``, or whose ``required_inputs`` or
    ``additional_inputs`` holds only blank patterns, raises ``pydantic.ValidationError``.
    """

    model_config = _FROZEN

    type: typing.Literal[TriggerTargetType.InvokeAction] = TriggerTargetType.InvokeAction
    """Kind of target, always ``TriggerTargetType.InvokeAction``."""

    target_id: str
    """ID of the target, unique within its trigger.

    Roboto keeps which entities the target already fired for under this ID, so a target given a new ID, even one
    otherwise identical, fires again for them.
    """

    required_inputs: list[str] = pydantic.Field(default_factory=list)
    """Gitignore-style patterns, such as ``**/*.bag``, for the files the action needs.

    When the trigger fires for one file (a file event at a ``once_per`` finer than
    :py:attr:`~roboto.domain.platform_events.OncePer.Dataset`), the list must not be empty, and the target runs only if
    that file matches one of the patterns. When it fires for a whole dataset, the target runs only if each pattern
    matches a file of its own in the dataset, and on
    :py:attr:`~roboto.domain.platform_events.PlatformEventType.FileIngested` only once every matching file is ingested.
    Must be empty when the trigger's platform events name no dataset.
    """

    additional_inputs: typing.Optional[list[str]] = None
    """Gitignore-style patterns for more of the dataset's files to give the invocation.

    They add to the files ``required_inputs`` match and do not decide whether the target runs. Must be empty when the
    trigger's platform events name no dataset.
    """

    @classmethod
    def from_invocation(
        cls,
        invocation: ActionInvocationSpec,
        *,
        target_id: str,
        required_inputs: typing.Optional[list[str]] = None,
        additional_inputs: typing.Optional[list[str]] = None,
    ) -> "InvokeActionTarget":
        """Build a target that runs ``invocation``, with the given ID and file patterns.

        Args:
            invocation: How to invoke the action.
            target_id: ID of the target, unique within its trigger.
            required_inputs: Patterns for the files the action needs. ``None`` sets none.
            additional_inputs: Patterns for more files to give the invocation. ``None`` sets none.
        """
        return cls(
            **{field: getattr(invocation, field) for field in ActionInvocationSpec.model_fields},
            target_id=target_id,
            required_inputs=required_inputs or [],
            additional_inputs=additional_inputs,
        )

    def invocation(self) -> ActionInvocationSpec:
        """Return how this target invokes its action, without the target's ID or file patterns."""
        return ActionInvocationSpec(**{field: getattr(self, field) for field in ActionInvocationSpec.model_fields})

    @pydantic.field_validator("required_inputs")
    @classmethod
    def _validate_required_inputs(cls, value: list[str]) -> list[str]:
        return validate_nonzero_gitpath_specs(value) if value else value

    @pydantic.field_validator("additional_inputs")
    @classmethod
    def _validate_additional_inputs(cls, value: typing.Optional[list[str]]) -> typing.Optional[list[str]]:
        return validate_nonzero_gitpath_specs(value) if value else value

    def referenced_placeholders(self) -> set[str]:
        """Return the name of every placeholder in this target's templated fields.

        Those are ``parameter_values``, ``invocation_input``, ``required_inputs`` and ``additional_inputs``.

        Returns:
            Placeholder names without their braces, such as ``dataset.dataset_id``.

        Raises:
            ValueError: A key in ``parameter_values`` contains placeholder syntax.
        """
        return (
            super().referenced_placeholders()
            | collect_placeholders(self.required_inputs)
            | collect_placeholders(self.additional_inputs or [])
        )


class StartAgentTarget(_TargetSpecBase):
    """Target that starts a thread from a saved agent when its trigger fires.

    Roboto fills the ``{{...}}`` placeholders in each of ``values`` from the platform event that fired the trigger,
    then starts the agent with the results as the values of its variables. Constructing a target with any other
    ``type`` raises ``pydantic.ValidationError``.
    """

    model_config = _FROZEN

    type: typing.Literal[TriggerTargetType.StartAgent] = TriggerTargetType.StartAgent
    """Kind of target, always ``TriggerTargetType.StartAgent``."""

    target_id: str
    """ID of the target, unique within its trigger.

    Roboto keeps which entities the target already fired for under this ID, so a target given a new ID fires again for
    them.
    """

    agent_id: str
    """ID of the saved agent to start a thread from. The agent must belong to the trigger's organization."""

    values: dict[str, str] = pydantic.Field(default_factory=dict)
    """Values of the agent's variables, keyed by variable name, each a template that may contain placeholders.

    Variables left out take the agent's defaults.
    """

    visibility: ThreadVisibility = ThreadVisibility.ORG
    """Who may read the threads the target starts. Defaults to every member of the organization."""

    analysis_scope: typing.Optional[AnalysisScope] = None
    """Time window the agent analyzes.

    Each bound set here replaces the agent's own, and each bound left ``None`` keeps it. ``None`` uses the agent's own
    scope.
    """

    def referenced_placeholders(self) -> set[str]:
        """Return the name of every placeholder in ``values``.

        Returns:
            Placeholder names without their braces, such as ``dataset.dataset_id``.
        """
        return collect_placeholders(self.values)


class SendSlackMessageTarget(_TargetSpecBase):
    """Target that posts a message to a Slack channel when its trigger fires.

    Each time it runs, Roboto checks that the organization allows it to post to the channel, and fails the target if
    not. A platform event Roboto delivers twice can post the message twice. Constructing a target with any other
    ``type`` raises ``pydantic.ValidationError``.
    """

    model_config = _FROZEN

    type: typing.Literal[TriggerTargetType.SendSlackMessage] = TriggerTargetType.SendSlackMessage
    """Kind of target, always ``TriggerTargetType.SendSlackMessage``."""

    target_id: str
    """ID of the target, unique within its trigger.

    Roboto keeps which entities the target already fired for under this ID, so a target given a new ID fires again for
    them.
    """

    channel_id: str
    """ID of the Slack channel to post to, such as ``C0123``."""

    text: str
    """Message to post. Roboto fills its ``{{...}}`` placeholders from the platform event that fired the trigger."""

    def referenced_placeholders(self) -> set[str]:
        """Return the name of every placeholder in ``text``.

        Returns:
            Placeholder names without their braces, such as ``dataset.dataset_id``.
        """
        return collect_placeholders(self.text)


TriggerTargetSpec = typing.Annotated[
    typing.Union[InvokeActionTarget, StartAgentTarget, SendSlackMessageTarget],
    pydantic.Field(discriminator="type"),
]
"""Target of any kind: one of the target models, told apart by ``type``.

A target is what a trigger runs when it fires. The models are ``InvokeActionTarget``, ``StartAgentTarget`` and
``SendSlackMessageTarget``.
"""


def target_catalog_manifest() -> dict[str, typing.Any]:
    """Return the kinds of target a trigger can have, keyed by their ``type``.

    Roboto calls this when it regenerates ``target_catalog.json`` in this package, the list of target kinds that the
    Roboto web app mirrors.

    Returns:
        Dictionary keyed by each kind's ``type`` value. Each value is an empty dictionary, because no kind of target is
        limited to some platform events.
    """
    spec_classes = typing.get_args(typing.get_args(TriggerTargetSpec)[0])
    return {spec.model_fields["type"].default.value: {} for spec in spec_classes}


__all__ = [
    "target_catalog_manifest",
    "ActionInvocationSpec",
    "InvokeActionTarget",
    "SendSlackMessageTarget",
    "StartAgentTarget",
    "TriggerTargetSpec",
    "TriggerTargetType",
]
