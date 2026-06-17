# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import re
from typing import Any, Optional, Union

import pydantic

from ...compat import StrEnum
from ...domain.collections.record import CollectionResourceType
from ...sentinels import NotSet, NotSetType
from ..agent_thread.record import StartAgentThreadRequest, ThreadVisibility
from ..core import AnalysisScope

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*\}\}")
"""Recognizes ``{{name}}`` placeholders. Names start with a letter or
underscore; dots are allowed so dotted names (``{{dataset.id}}``,
``{{dataset.name}}``) work as a namespace convention for entity-bound
expansion by upstream context providers (triggers, smart-UI auto-fill).
The resolver treats the full dotted string as one opaque key — a caller
holding an entity flattens it into ``{"dataset.id": ds.id, ...}`` before
invoking."""

_VARIABLE_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")
"""Mirrors :data:`_PLACEHOLDER_RE` so every declared variable name is
referenceable by ``{{name}}``."""


class TemplateVariableType(StrEnum):
    """How a variable is interpreted by the invoke-page UI and the invoke-time
    existence validator.

    The substitution engine itself is type-agnostic: every value gets spliced
    in as a string. The type drives two separate consumers: the UI picks a
    richer input control (dataset picker, device picker), and the service-side
    invoke handler runs an existence check on typed values so a bad id fails
    at the invoke boundary instead of inside the agent's first tool call.
    See :data:`roboto_service.routes.ai_router._VALUE_VALIDATORS`.
    """

    STRING = "string"
    """Free-form text. The default; renders as a plain text input. No existence
    check (no entity to check against)."""

    DATASET_ID = "dataset_id"
    """A Roboto dataset identifier. UI renders a dataset picker; invoke-time
    validator asserts the dataset exists in the caller's org."""

    DEVICE_ID = "device_id"
    """A Roboto device identifier. UI renders a device picker; invoke-time
    validator asserts the device is registered in the caller's org."""

    COLLECTION_ID = "collection_id"
    """A Roboto collection identifier. UI renders a collection picker; invoke-time
    validator asserts the collection exists in the caller's org."""


class TemplateVariable(pydantic.BaseModel):
    """A named slot in an :class:`AgentRecord` that must be filled before the
    agent can be invoked.

    Variables are declared up-front rather than inferred from the body so that
    the invoke UI can render typed inputs (dataset pickers, etc.) and so that
    a typo in the body (``{{dataste.id}}``) surfaces as a save-time validation
    error rather than a silent extra prompt at invoke time. The declared set
    and the set of placeholders parsed from the body must match exactly - see
    :meth:`AgentRecord._validate_variables_match_placeholders`.
    """

    name: str
    """Lookup key for substitution. Must match :data:`_VARIABLE_NAME_RE`; see
    that pattern for the dotted-name namespace convention. Two variables sharing
    a prefix (``dataset.id`` + ``dataset.name``) without an upstream expander
    produce two unlinked inputs at invoke time — that's a UI-authoring footgun,
    not an SDK contract."""

    type: TemplateVariableType = TemplateVariableType.STRING
    """UI hint for the invoke page. See :class:`TemplateVariableType`."""

    description: Optional[str] = None
    """Human-readable explanation rendered next to the input on the invoke page."""

    required: bool = True
    """If ``True`` the resolver raises :class:`UnresolvedAgentVariablesError`
    when no value is supplied and no :attr:`default` is set."""

    default: Optional[str] = None
    """Default value substituted when the caller omits the variable. Coerced
    to ``str``; types are a UI concern."""

    collection_content_type: Optional[CollectionResourceType] = None
    """Only meaningful when :attr:`type` is :attr:`TemplateVariableType.COLLECTION_ID`: constrains
    the invoke-page collection picker to collections holding this resource type (e.g. ``event``
    collections for a create-events goal). ``None`` leaves the picker unconstrained. Must be ``None``
    for every other variable type — see :meth:`_validate_resolvable`."""

    @pydantic.field_validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        if not _VARIABLE_NAME_RE.match(value):
            raise ValueError(
                f"TemplateVariable name {value!r} must match {_VARIABLE_NAME_RE.pattern!r}: "
                "start with a letter or underscore, then letters, digits, underscores, or dots. "
                "Dotted names are a namespace convention for entity-bound expansion at the "
                "caller boundary; the resolver itself treats the full dotted name as one opaque key."
            )
        return value

    @pydantic.model_validator(mode="after")
    def _validate_resolvable(self) -> "TemplateVariable":
        """Reject two malformed shapes: ``required=False`` paired with
        ``default=None`` (an optional variable with no default has no resolution
        path at invoke time), and a :attr:`collection_content_type` set on a
        variable whose :attr:`type` is not ``COLLECTION_ID`` (the annotation only
        has meaning for the collection picker)."""
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
    """A pre-filled :class:`StartAgentThreadRequest` plus declared variables.

    An :class:`AgentRecord` captures *most* of what an :class:`AgentThread`
    needs to start - system prompt, model profile, seeded messages, declared
    goals - and leaves a small set of named holes that callers must fill at
    invoke time. The canonical example is a triage agent whose goal carries a
    fixed ``label_vocabulary`` but a ``{{dataset.id}}`` placeholder, so the
    same agent can be re-run against many datasets without re-declaring the
    vocabulary.

    The record's main invariant - enforced by
    :meth:`_validate_variables_match_placeholders` - is that the set of
    ``{{...}}`` placeholders found anywhere in :attr:`request_template`
    equals exactly ``{v.name for v in variables}``. A mismatch fails at
    save time so stale invoke forms can't paper over typos.
    """

    agent_id: str
    """Canonical handle. Generated server-side (``agt_<short>``); stable across renames."""

    org_id: str
    """Organization that owns the agent. All CRUD and invoke calls must
    come from a member of this org."""

    name: str
    """Human-readable display name. Mutable. Unique per ``(org_id, name)`` -
    enforced at the persistence layer, not on the record."""

    description: Optional[str] = None
    """Free-form description rendered on the agents list and detail pages."""

    request_template: StartAgentThreadRequest
    """The body that will be cloned and resolved into a real
    :class:`StartAgentThreadRequest` at invoke time. Any string leaf may
    contain ``{{name}}`` placeholders; non-string fields cannot be templated
    in v1 (the substitution engine never visits them)."""

    variables: list[TemplateVariable] = pydantic.Field(default_factory=list)
    """Declared variables. The set of names here must equal the set of
    placeholder names parsed from :attr:`request_template`."""

    created: datetime.datetime
    """Wall-clock time the record was first persisted."""

    created_by: str
    """User id of the agent's original author."""

    modified: datetime.datetime
    """Wall-clock time of the most recent successful update."""

    modified_by: str
    """User id who applied the most recent update; equals :attr:`created_by`
    on records that have not been edited since creation."""

    @pydantic.model_validator(mode="after")
    def _validate_variables_match_placeholders(self) -> "AgentRecord":
        """Raise ``ValueError`` if declared variables don't match the body's
        placeholders. Three failure modes: a placeholder is referenced but
        not declared, a variable is declared but not referenced, or two
        variables share a name."""
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
    """Return every ``{{name}}`` placeholder referenced anywhere in ``body``.

    Walks the JSON form of the request rather than the Pydantic model so the
    traversal is type-agnostic - placeholders inside ``label_vocabulary``
    values, message text, system prompt, etc. all get picked up without
    needing per-field logic. Only string *values* are scanned; dict keys are
    intentionally ignored so key-collision footguns never arise.
    """
    raw = body.model_dump(mode="json")
    found: set[str] = set()
    _collect_placeholders(raw, found)
    return found


def _collect_placeholders(node: Any, sink: set[str]) -> None:
    if isinstance(node, str):
        for match in _PLACEHOLDER_RE.finditer(node):
            sink.add(match.group(1))
    elif isinstance(node, list):
        for item in node:
            _collect_placeholders(item, sink)
    elif isinstance(node, dict):
        for key, value in node.items():
            # The resolver never substitutes into dict keys (templating a key
            # would silently produce duplicate keys that overwrite each other),
            # so reject placeholder syntax in keys at save time rather than
            # passing it through as a literal.
            if isinstance(key, str) and _PLACEHOLDER_RE.search(key):
                raise ValueError(
                    f"Placeholder syntax is not permitted in dict keys: found {key!r}. "
                    "Move the ``{{...}}`` placeholder into the value or rename the key."
                )
            _collect_placeholders(value, sink)


class CreateAgentRequest(pydantic.BaseModel):
    """Wire payload for ``POST /v1/ai/agents``.

    The server fills :attr:`AgentRecord.agent_id`, ``org_id``,
    ``created_by``, ``created``, ``modified``, and ``modified_by`` from the
    caller's identity; everything else comes from this request.
    """

    name: str
    description: Optional[str] = None
    request_template: StartAgentThreadRequest
    variables: list[TemplateVariable] = pydantic.Field(default_factory=list)


class UpdateAgentRequest(pydantic.BaseModel):
    """Wire payload for ``PUT /v1/ai/agents/<agent_id>``.

    Uses the :class:`NotSetType` sentinel to distinguish "field omitted" from
    "field explicitly set to ``None``" so partial updates don't accidentally
    null out unrelated fields.
    """

    name: Union[str, NotSetType] = NotSet
    description: Union[Optional[str], NotSetType] = NotSet
    request_template: Union[StartAgentThreadRequest, NotSetType] = NotSet
    variables: Union[list[TemplateVariable], NotSetType] = NotSet

    model_config = pydantic.ConfigDict(
        extra="ignore",
        json_schema_extra=NotSetType.openapi_schema_modifier,
    )


class LaunchAgentRequest(pydantic.BaseModel):
    """Wire payload for ``POST /v1/ai/agents/<agent_id>/launch``.

    The route resolves the named agent, substitutes ``values`` into its
    body, and starts a new :class:`AgentThread` whose visibility comes from
    :attr:`visibility` and whose ``created_from_agent_id`` points back at
    the source agent.
    """

    values: dict[str, str] = pydantic.Field(default_factory=dict)
    """Variable name to caller-supplied value. Keys must match declared
    :class:`TemplateVariable` names; values are coerced to ``str`` before
    being spliced into placeholders."""

    visibility: ThreadVisibility = ThreadVisibility.ORG
    """Visibility of the resulting :class:`AgentThread`. Invoke-time wins:
    this value overrides whatever the agent's ``request_template.visibility``
    field carries. Agents cannot pin visibility — authors who need to convey
    recommended visibility do so in the agent's ``description``. Defaults to
    ``ORG`` because agents exist to share workflows across teammates;
    ``PRIVATE`` is an explicit opt-out per invocation."""

    analysis_scope: Optional[AnalysisScope] = None
    """Optional :class:`~roboto.ai.core.AnalysisScope` for the resulting
    thread. When provided, it is zipper-merged onto whatever the agent's
    ``request_template.analysis_scope`` field carries: each dimension the
    caller set wins, and the rest inherit from the template. When ``None``,
    the authored template's scope (usually none) is left untouched."""


__all__ = [
    "AgentRecord",
    "CreateAgentRequest",
    "LaunchAgentRequest",
    "TemplateVariable",
    "TemplateVariableType",
    "UpdateAgentRequest",
    "extract_placeholders",
]
