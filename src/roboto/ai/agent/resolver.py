# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any

from ..agent_session.record import StartAgentSessionRequest
from .record import _PLACEHOLDER_RE, AgentRecord, TemplateVariable


class AgentResolutionError(ValueError):
    """Base class for resolver-raised errors. Routes map subclasses to 4xx."""


class UnresolvedAgentVariablesError(AgentResolutionError):
    """Required variables had no supplied value and no default. Mapped to 400
    with the names so the invoke page can highlight the empty inputs."""

    def __init__(self, names: list[str]) -> None:
        self.names = sorted(names)
        super().__init__("Missing required values for agent variables: " + ", ".join(self.names) + ".")


class UnknownAgentVariablesError(AgentResolutionError):
    """Caller supplied values for variables the agent no longer declares —
    almost always a stale invoke form. Mapped to 400 so the UI can refetch."""

    def __init__(self, names: list[str]) -> None:
        self.names = sorted(names)
        super().__init__("Received values for variables not declared by the agent: " + ", ".join(self.names) + ".")


def resolve_agent(
    agent: AgentRecord,
    values: dict[str, str],
) -> StartAgentSessionRequest:
    """Substitute ``values`` into ``agent.request_template`` and return a
    fully-validated :class:`StartAgentSessionRequest`.

    Walks the body's JSON form swapping every ``{{name}}`` occurrence in a
    string leaf. Embedded substitution is supported. Dict keys are never
    touched — placeholder syntax in keys is rejected at save time.

    Raises:
        UnknownAgentVariablesError: ``values`` contains keys not declared on
            the agent (typically a stale invoke form).
        UnresolvedAgentVariablesError: a required variable has neither a
            supplied value nor a default; carries the offending names.
        pydantic.ValidationError: the substituted body failed
            :class:`StartAgentSessionRequest` validation — e.g. a resolved
            value doesn't match a field-level regex or enum.
    """
    merged = _merge_values_and_defaults(agent.variables, values)
    raw = agent.request_template.model_dump(mode="json")
    resolved = _walk_and_sub(raw, merged)
    return StartAgentSessionRequest.model_validate(resolved)


def _merge_values_and_defaults(
    variables: list[TemplateVariable],
    supplied: dict[str, str],
) -> dict[str, str]:
    declared_names = {v.name for v in variables}

    unknown = supplied.keys() - declared_names
    if unknown:
        raise UnknownAgentVariablesError(list(unknown))

    merged: dict[str, str] = {}
    missing_required: list[str] = []
    for variable in variables:
        if variable.name in supplied:
            merged[variable.name] = supplied[variable.name]
        elif variable.default is not None:
            merged[variable.name] = variable.default
        else:
            # Reaching this branch means required=True and the caller omitted
            # a value: TemplateVariable._validate_resolvable rejects the
            # (required=False, default=None) combination at record-save time,
            # so an optional variable always has a default to fall back to.
            missing_required.append(variable.name)

    if missing_required:
        raise UnresolvedAgentVariablesError(missing_required)

    return merged


def _walk_and_sub(node: Any, values: dict[str, str]) -> Any:
    if isinstance(node, str):
        return _PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), node)
    if isinstance(node, list):
        return [_walk_and_sub(item, values) for item in node]
    if isinstance(node, dict):
        return {key: _walk_and_sub(value, values) for key, value in node.items()}
    return node


__all__ = [
    "AgentResolutionError",
    "UnknownAgentVariablesError",
    "UnresolvedAgentVariablesError",
    "resolve_agent",
]
