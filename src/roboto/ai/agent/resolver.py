# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ...templating import MappingResolver, substitute
from ..agent_thread.record import StartAgentThreadRequest
from .record import AgentRecord, TemplateVariable


class AgentResolutionError(ValueError):
    """Base class of the exceptions the SDK raises when the values for a launch of an agent do not match its variables.

    ``resolve_agent`` raises its two subclasses, ``UnknownAgentVariablesError`` and ``UnresolvedAgentVariablesError``.
    :py:meth:`~roboto.ai.agent.Agent.launch` reports either one as ``RobotoInvalidRequestException``, with the same
    message.
    """


class UnresolvedAgentVariablesError(AgentResolutionError):
    """A launch of an agent has no value for a required variable that has no default.

    ``resolve_agent`` raises it, and its message names every such variable.
    """

    def __init__(self, names: list[str]) -> None:
        self.names = sorted(names)
        """Names of the required variables that have no value, sorted."""
        super().__init__("Missing required values for agent variables: " + ", ".join(self.names) + ".")


class UnknownAgentVariablesError(AgentResolutionError):
    """A launch of an agent has a value for a name that is not one of the agent's variables.

    ``resolve_agent`` raises it, and its message names every such name. A launch form loaded before someone removed a
    variable from the agent sends one.
    """

    def __init__(self, names: list[str]) -> None:
        self.names = sorted(names)
        """Names in the launch's values that are not variables of the agent, sorted."""
        super().__init__("Received values for variables not declared by the agent: " + ", ".join(self.names) + ".")


def resolve_agent(
    agent: AgentRecord,
    values: dict[str, str],
) -> StartAgentThreadRequest:
    """Build the request that starts a thread for one launch of an agent, with ``values`` in its placeholders.

    Roboto calls this when :py:meth:`~roboto.ai.agent.Agent.launch` or a trigger with a
    :py:class:`~roboto.domain.triggers.StartAgentTarget` launches an agent.

    Each ``{{name}}`` placeholder in a string value of the agent's ``request_template`` becomes its variable's value,
    including a placeholder within longer text. Dictionary keys are left unchanged.

    Args:
        agent: Record of the agent to launch.
        values: Value of each variable, keyed by variable name. A variable left out uses its default.

    Raises:
        UnknownAgentVariablesError: A key in ``values`` names no variable of the agent.
        UnresolvedAgentVariablesError: A required variable has no value in ``values`` and no default.
        pydantic.ValidationError: The request with the values filled in is not a valid
            :py:class:`~roboto.ai.agent_thread.StartAgentThreadRequest`, such as when a value does not match a
            field's pattern.
    """
    merged = _merge_values_and_defaults(agent.variables, values)
    raw = agent.request_template.model_dump(mode="json")
    resolved = substitute(raw, MappingResolver(merged))
    return StartAgentThreadRequest.model_validate(resolved)


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
            # Only a required variable reaches this branch: TemplateVariable rejects an optional variable
            # with no default.
            missing_required.append(variable.name)

    if missing_required:
        raise UnresolvedAgentVariablesError(missing_required)

    return merged


__all__ = [
    "AgentResolutionError",
    "UnknownAgentVariablesError",
    "UnresolvedAgentVariablesError",
    "resolve_agent",
]
