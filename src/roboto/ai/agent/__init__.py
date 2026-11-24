# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Agents: AI workers an organization defines and runs on its data, each a saved request to start a thread.

Each launch fills the agent's typed ``{{name}}`` placeholders with its own values and starts a thread, so one agent can
be launched repeatedly with different inputs. Use :py:class:`~roboto.ai.agent.Agent` to create, find, update, and
launch agents.
"""

from .agent import Agent
from .record import (
    AgentRecord,
    AgentSubject,
    CreateAgentRequest,
    LaunchAgentRequest,
    TemplateVariable,
    TemplateVariableType,
    UpdateAgentRequest,
    extract_placeholders,
)
from .resolver import (
    AgentResolutionError,
    UnknownAgentVariablesError,
    UnresolvedAgentVariablesError,
    resolve_agent,
)
from .subject import infer_agent_subject

# ThreadVisibility is not re-exported here, so the SDK reference and IDE auto-import suggestions give it one import
# path: roboto.ai.agent_thread, next to the requests and records that carry it.

__all__ = [
    "Agent",
    "AgentRecord",
    "AgentResolutionError",
    "AgentSubject",
    "CreateAgentRequest",
    "LaunchAgentRequest",
    "TemplateVariable",
    "TemplateVariableType",
    "UnknownAgentVariablesError",
    "UnresolvedAgentVariablesError",
    "UpdateAgentRequest",
    "extract_placeholders",
    "infer_agent_subject",
    "resolve_agent",
]
