# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
from typing import Optional, Union

import pydantic

from ...compat import StrEnum
from ...domain.collections.record import CollectionResourceType
from ...sentinels import NotSet, NotSetType
from ...templating import VARIABLE_NAME_RE, collect_placeholders
from ..agent_thread.record import StartAgentThreadRequest, ThreadVisibility
from ..core import AnalysisScope


class TemplateVariableType(StrEnum):
    """Type of a template variable's value: how Roboto checks it when the agent is launched.

    Every value fills its placeholders as text, whatever its type. When the agent is launched, Roboto checks that the
    resource an ID-typed value names exists in the agent's organization, and rejects the launch before it starts a
    thread when it does not. The Roboto web app offers a picker for a dataset or collection ID, and a text box for any
    other type.
    """

    STRING = "string"
    """Free-form text, which Roboto does not check."""

    DATASET_ID = "dataset_id"
    """ID of a dataset."""

    DEVICE_ID = "device_id"
    """ID of a device."""

    COLLECTION_ID = "collection_id"
    """ID of a collection."""

    SESSION_ID = "session_id"
    """ID of a session."""


class AgentSubject(StrEnum):
    """Subject of an agent: the kind of resource it is launched on.

    An agent acts on a dataset or on a session, never both, because all of its goals must act on the same kind of
    resource. Roboto works the subject out from the agent's goals and variables, with
    :py:func:`~roboto.ai.agent.infer_agent_subject`, instead of storing it.
    """

    DATASET = "dataset"
    """Datasets (:py:class:`~roboto.domain.datasets.Dataset`)."""

    SESSION = "session"
    """Sessions (:py:class:`~roboto.experimental.sessions.Session`)."""


class TemplateVariable(pydantic.BaseModel):
    """Variable of an agent: a named value that each launch fills into the agent's ``{{name}}`` placeholders.

    Carried in ``AgentRecord.variables``. Because an agent declares its variables instead of Roboto inferring them
    from its placeholders, the Roboto web app can show a typed input for each one, and a misspelled placeholder fails
    when the agent is saved instead of when it is launched.

    Building it raises ``pydantic.ValidationError`` when:

    - ``name`` does not match :py:const:`~roboto.templating.VARIABLE_NAME_RE`.
    - ``required`` is ``False`` and ``default`` is ``None``.
    - ``collection_content_type`` is set and ``type`` is not ``TemplateVariableType.COLLECTION_ID``.
    """

    name: str
    """Name of the variable, which the agent's request template writes as ``{{name}}``. Unique within the agent.

    A dotted name such as ``dataset.id`` is one name: ``dataset.id`` and ``dataset.name`` are two unrelated variables
    with two inputs at launch.
    """

    type: TemplateVariableType = TemplateVariableType.STRING
    """Type of the variable's value, which decides how Roboto checks it at launch. Defaults to free-form text."""

    description: Optional[str] = None
    """Human-readable description of the variable, shown next to its input in the Roboto web app's launch form."""

    required: bool = True
    """Whether a launch must have a value for the variable.

    A launch that leaves the variable out uses ``default``, and :py:meth:`~roboto.ai.agent.Agent.launch` raises
    ``RobotoInvalidRequestException`` when there is none. ``False`` requires a ``default``.
    """

    default: Optional[str] = None
    """Value used when a launch leaves the variable out, or ``None`` if the variable has none."""

    collection_content_type: Optional[CollectionResourceType] = None
    """Kind of resource a collection must hold to appear in the Roboto web app's collection picker for this variable.

    For example, a variable for a goal that creates events can require event collections. ``None`` offers every
    collection.

    Roboto does not check it at launch. Used only with ``TemplateVariableType.COLLECTION_ID``.
    """

    @pydantic.field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not VARIABLE_NAME_RE.match(value):
            raise ValueError(
                f"TemplateVariable name {value!r} must match {VARIABLE_NAME_RE.pattern!r}: "
                "start with a letter or underscore, then letters, digits, underscores, or dots. "
                "Dotted names are a namespace convention for entity-bound expansion at the "
                "caller boundary; the resolver itself treats the full dotted name as one opaque key."
            )
        return value

    @pydantic.model_validator(mode="after")
    def _validate_resolvable(self) -> "TemplateVariable":
        if not self.required and self.default is None:
            raise ValueError(
                f"TemplateVariable {self.name!r}: an optional variable must carry a default "
                "(required=False, default=None has no defined resolution)."
            )
        if self.collection_content_type is not None and self.type is not TemplateVariableType.COLLECTION_ID:
            raise ValueError(
                f"TemplateVariable {self.name!r}: collection_content_type is only valid when type is "
                f"COLLECTION_ID (got type={self.type!r})."
            )
        return self


class AgentRecord(pydantic.BaseModel):
    """Data record of an agent, as the Roboto API returns it.

    An agent is an AI worker an organization defines and runs on its data: a saved request to start a thread, with
    typed ``{{name}}`` placeholders, optionally paired with goals. Each launch fills the placeholders with its own
    values and starts a thread, so one agent, such as a triage agent with a fixed label vocabulary and a dataset ID
    placeholder, can run on many datasets. :py:class:`~roboto.ai.agent.Agent` wraps this record with methods that act
    on the agent.

    Building it raises ``pydantic.ValidationError`` when:

    - ``variables`` and the placeholders in ``request_template`` do not name the same set of variables.
    - Two variables share a name.
    - A dictionary key in ``request_template`` holds a placeholder.
    """

    agent_id: str
    """Unique ID of the agent, beginning with ``agt_``."""

    org_id: str
    """ID of the organization that owns the agent."""

    name: str
    """Human-readable name of the agent, unique within its organization."""

    description: Optional[str] = None
    """Human-readable description of the agent, or ``None`` if it has none."""

    request_template: StartAgentThreadRequest
    """Request that starts each of the agent's threads, with ``{{name}}`` placeholders where launch values go.

    A placeholder can appear anywhere in a string value, but not in a dictionary key, and fields of other types cannot
    hold one. Each launch fills the placeholders and starts a thread with the resulting
    :py:class:`~roboto.ai.agent_thread.StartAgentThreadRequest`.
    """

    variables: list[TemplateVariable] = pydantic.Field(default_factory=list)
    """Variables of the agent, exactly one for each placeholder name in ``request_template``."""

    created: datetime.datetime
    """Time the agent was created."""

    created_by: str
    """ID of the user who created the agent."""

    modified: datetime.datetime
    """Time the agent was last modified."""

    modified_by: str
    """ID of the user who last modified the agent."""

    subject: Optional[AgentSubject] = None
    """Kind of resource the agent is launched on, or ``None`` for an agent with no subject.

    A chat agent that takes no dataset or session ID, for example, has no subject.

    Roboto computes it from ``request_template`` and ``variables`` with
    :py:func:`~roboto.ai.agent.infer_agent_subject` each time it returns the record. It is not stored, and create and
    update requests do not take it.
    """

    @pydantic.model_validator(mode="after")
    def _validate_variables_match_placeholders(self) -> "AgentRecord":
        body_placeholders = extract_placeholders(self.request_template)
        declared = {v.name for v in self.variables}

        missing_declarations = sorted(body_placeholders - declared)
        unused_declarations = sorted(declared - body_placeholders)

        if missing_declarations or unused_declarations:
            parts: list[str] = []
            if missing_declarations:
                parts.append(
                    f"placeholders referenced in request_template but not declared in variables: {missing_declarations}"
                )
            if unused_declarations:
                parts.append(f"variables declared but never referenced in request_template: {unused_declarations}")
            raise ValueError(
                "Agent variable declarations must match the placeholders in request_template "
                "exactly. " + "; ".join(parts) + "."
            )

        seen: set[str] = set()
        for v in self.variables:
            if v.name in seen:
                raise ValueError(f"Duplicate TemplateVariable name: {v.name!r}.")
            seen.add(v.name)
        return self


def extract_placeholders(body: StartAgentThreadRequest) -> set[str]:
    """Return the name of every ``{{name}}`` placeholder in the string values of ``body``.

    Scans every string value in the request's JSON form, such as message text, the system prompt, and the values of a
    goal's label vocabulary.

    Args:
        body: Request to scan, such as an agent's request template.

    Raises:
        ValueError: A dictionary key in ``body`` holds a placeholder.
    """
    return collect_placeholders(body.model_dump(mode="json"))


class CreateAgentRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.ai.agent.Agent.create`.

    Roboto sets the agent's ID, organization, and creation and modification fields.
    """

    name: str
    """Human-readable name of the agent, unique within its organization."""

    description: Optional[str] = None
    """Human-readable description of the agent. ``None`` sets none."""

    request_template: StartAgentThreadRequest
    """Request that starts each of the agent's threads, as ``AgentRecord.request_template`` describes."""

    variables: list[TemplateVariable] = pydantic.Field(default_factory=list)
    """Variables of the agent, exactly one for each placeholder name in ``request_template``. Defaults to none."""


class UpdateAgentRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.ai.agent.Agent.update`.

    A field left unset (``NotSet``) is unchanged. Roboto checks the agent's variables against its placeholders after
    applying the update, so a request that changes the placeholders in ``request_template`` must also send the
    matching ``variables``.
    """

    name: Union[str, NotSetType] = NotSet
    """Human-readable name of the agent, unique within its organization."""

    description: Union[Optional[str], NotSetType] = NotSet
    """Human-readable description of the agent. ``None`` clears it."""

    request_template: Union[StartAgentThreadRequest, NotSetType] = NotSet
    """Request that starts each of the agent's threads, as ``AgentRecord.request_template`` describes."""

    variables: Union[list[TemplateVariable], NotSetType] = NotSet
    """Variables of the agent, exactly one for each placeholder name in ``request_template``."""

    model_config = pydantic.ConfigDict(
        extra="ignore",
        json_schema_extra=NotSetType.openapi_schema_modifier,
    )


class LaunchAgentRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.ai.agent.Agent.launch`.

    Roboto fills ``values`` into the agent's request template and starts a thread in the agent's organization, whose
    ``created_from_agent_id`` names the agent.
    """

    values: dict[str, str] = pydantic.Field(default_factory=dict)
    """Value of each variable, keyed by variable name. A variable left out uses its default. Defaults to none.

    A key that names no variable of the agent raises ``RobotoInvalidRequestException``.
    """

    visibility: ThreadVisibility = ThreadVisibility.ORG
    """Visibility of the new thread, which replaces the ``visibility`` in the agent's request template.

    Defaults to :py:attr:`~roboto.ai.agent_thread.ThreadVisibility.ORG`, which lets every member of the organization
    read the thread. ``PRIVATE`` limits it to the user who launches the agent.
    """

    analysis_scope: Optional[AnalysisScope] = None
    """Data the new thread analyzes, combined with the ``analysis_scope`` in the agent's request template.

    Each field set here replaces the template's, and each field left ``None`` keeps the template's. ``None`` keeps the
    template's scope unchanged.
    """


__all__ = [
    "AgentRecord",
    "AgentSubject",
    "CreateAgentRequest",
    "LaunchAgentRequest",
    "TemplateVariable",
    "TemplateVariableType",
    "UpdateAgentRequest",
    "extract_placeholders",
]
