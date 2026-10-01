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
    """The kind of thing a trigger does when it fires."""

    InvokeAction = "invoke_action"
    """Invoke a containerized action."""

    StartAgent = "start_agent"
    """Start an AI agent thread from a saved agent definition."""

    SendSlackMessage = "send_slack_message"
    """Post a message to a Slack channel on the org's allowlist."""


class _TargetSpecBase(pydantic.BaseModel):
    """Common base for target specs.

    Marks the ``type`` discriminator as explicitly set at construction so it
    survives ``exclude_unset`` serialization — the SDK's HTTP client serializes
    request bodies that way, and a spec whose discriminator is dropped cannot be
    parsed back out of the union on the server.
    """

    def model_post_init(self, __context: typing.Any) -> None:
        self.__pydantic_fields_set__.add("type")


class InvokeActionTarget(_TargetSpecBase):
    """Stored configuration for invoking an action when a trigger fires.

    Spec only — dispatch behavior lives server-side. String leaves of
    :attr:`parameter_values`, :attr:`required_inputs`, :attr:`additional_inputs`, and
    :attr:`invocation_input` may contain ``{{...}}`` placeholders resolved against the
    event namespace at dispatch time.

    An event that names a dataset invokes the action against that dataset, with inputs
    matched from its files by the file patterns. An event that names no dataset has no
    files to match: the invocation has no data source and selects its inputs with
    :attr:`invocation_input`.
    """

    model_config = _FROZEN

    type: typing.Literal[TriggerTargetType.InvokeAction] = TriggerTargetType.InvokeAction
    """Discriminator for :data:`TriggerTargetSpec`."""

    target_id: str
    """Stable id of this target within its trigger. Part of the dispatch idempotency
    key: the target's once-per history is kept under this id, so renaming it (or
    replacing it with an identical target under a new id) starts a fresh history and
    the target fires again for subjects the old id already fired for."""

    action: ActionReference
    """The action to invoke. ``owner`` defaults to the trigger's org when omitted and
    ``digest`` to the action's latest version."""

    required_inputs: list[str] = pydantic.Field(default_factory=list)
    """File patterns (e.g. ``**/*.bag``) that gate dispatch on the firing event's files.
    Only for events that name a dataset; must be empty otherwise."""

    additional_inputs: typing.Optional[list[str]] = None
    """Optional extra file patterns passed as invocation inputs beyond the required ones.
    Only for events that name a dataset; must be empty otherwise."""

    invocation_input: typing.Optional[InvocationInput] = None
    """Optional query-based input selection (files, topics, sessions) resolved when the
    invocation runs, e.g. ``InvocationInput.from_session_id("{{session.session_id}}")``.
    The way a trigger on an event that names no dataset selects its inputs; may also
    accompany the file patterns of an event that names one."""

    parameter_values: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Parameter values passed to the action; string leaves may be templated."""

    compute_requirement_overrides: typing.Optional[ComputeRequirements] = None
    """Optional compute requirement overrides for the invocation."""

    container_parameter_overrides: typing.Optional[ContainerParameters] = None
    """Optional container parameter overrides for the invocation."""

    timeout: typing.Optional[int] = None
    """Optional invocation timeout override, in minutes."""

    upload_destination: typing.Optional[InvocationUploadDestination] = None
    """Optional destination for the invocation's output files."""

    @pydantic.field_validator("required_inputs")
    @classmethod
    def _validate_required_inputs(cls, value: list[str]) -> list[str]:
        return validate_nonzero_gitpath_specs(value) if value else value

    @pydantic.field_validator("additional_inputs")
    @classmethod
    def _validate_additional_inputs(cls, value: typing.Optional[list[str]]) -> typing.Optional[list[str]]:
        return validate_nonzero_gitpath_specs(value) if value else value

    def referenced_placeholders(self) -> set[str]:
        """Return every ``{{name}}`` placeholder referenced by this target's templated fields."""
        return (
            collect_placeholders(self.parameter_values)
            | collect_placeholders(self.required_inputs)
            | collect_placeholders(self.additional_inputs or [])
            | collect_placeholders(
                self.invocation_input.model_dump(mode="json") if self.invocation_input is not None else {}
            )
        )


class StartAgentTarget(_TargetSpecBase):
    """Stored configuration for starting an agent thread when a trigger fires.

    Spec only — dispatch behavior lives server-side. Each value in :attr:`values` is a
    template resolved against the event namespace, then handed to the agent's own
    variable resolution as a plain value.
    """

    model_config = _FROZEN

    type: typing.Literal[TriggerTargetType.StartAgent] = TriggerTargetType.StartAgent
    """Discriminator for :data:`TriggerTargetSpec`."""

    target_id: str
    """Stable id of this target within its trigger; part of the dispatch idempotency key."""

    agent_id: str
    """The agent definition to launch."""

    values: dict[str, str] = pydantic.Field(default_factory=dict)
    """Agent variable name to a template string resolved against the event namespace."""

    visibility: ThreadVisibility = ThreadVisibility.ORG
    """Visibility of the resulting agent thread."""

    analysis_scope: typing.Optional[AnalysisScope] = None
    """Optional analysis scope for the resulting thread."""

    def referenced_placeholders(self) -> set[str]:
        """Return every ``{{name}}`` placeholder referenced by this target's templated values."""
        return collect_placeholders(self.values)


class SendSlackMessageTarget(_TargetSpecBase):
    """Stored configuration for posting a Slack message when a trigger fires.

    Spec only — dispatch behavior lives server-side. The channel must be on the org's
    Slack outbound allowlist at dispatch time.
    """

    model_config = _FROZEN

    type: typing.Literal[TriggerTargetType.SendSlackMessage] = TriggerTargetType.SendSlackMessage
    """Discriminator for :data:`TriggerTargetSpec`."""

    target_id: str
    """Stable id of this target within its trigger; part of the dispatch idempotency key."""

    channel_id: str
    """Slack channel to post to."""

    text: str
    """Message body; may contain ``{{...}}`` placeholders resolved against the event namespace."""

    def referenced_placeholders(self) -> set[str]:
        """Return every ``{{name}}`` placeholder referenced by this target's templated text."""
        return collect_placeholders(self.text)


TriggerTargetSpec = typing.Annotated[
    typing.Union[InvokeActionTarget, StartAgentTarget, SendSlackMessageTarget],
    pydantic.Field(discriminator="type"),
]
"""A trigger target spec, discriminated on ``type``."""


def target_catalog_manifest() -> dict[str, typing.Any]:
    """The kinds of target a trigger can have, as the web UI's target picker reads them.

    ``target_catalog.json`` in this package is this function's output, written by
    ``scripts/gen_trigger_manifests.py`` and drift-checked by a test on each side. Each
    entry's body is empty: a target carries no save-time constraint of its own, so the
    picker offers every type for every event.
    """
    spec_classes = typing.get_args(typing.get_args(TriggerTargetSpec)[0])
    return {spec.model_fields["type"].default.value: {} for spec in spec_classes}


__all__ = [
    "target_catalog_manifest",
    "InvokeActionTarget",
    "SendSlackMessageTarget",
    "StartAgentTarget",
    "TriggerTargetSpec",
    "TriggerTargetType",
]
