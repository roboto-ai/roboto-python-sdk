# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Reusable, parameterized agent definitions.

An agent captures a parameterized
:py:class:`~roboto.ai.agent_session.StartAgentSessionRequest` alongside the
variables it declares, so the same workflow (triage, summary, etc.) can be
re-invoked against new subjects without re-authoring the request. Variables
appear as ``{{name}}`` placeholders in any string leaf of the request body and
are substituted client-side before the request is sent — unresolved or unknown
placeholders raise rather than reach the service.
"""

from .agent import Agent
from .record import (
    AgentRecord,
    CreateAgentRequest,
    InvokeAgentRequest,
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

# Note: ``SessionVisibility`` is intentionally not re-exported here. The
# canonical SDK path is :py:class:`roboto.ai.agent_session.SessionVisibility`,
# co-located with the request and record types that carry the field. Adding a
# third re-export here would fragment SDK reference docs and IDE auto-import
# suggestions across multiple paths for one symbol.

__all__ = [
    "Agent",
    "AgentRecord",
    "AgentResolutionError",
    "CreateAgentRequest",
    "InvokeAgentRequest",
    "TemplateVariable",
    "TemplateVariableType",
    "UnknownAgentVariablesError",
    "UnresolvedAgentVariablesError",
    "UpdateAgentRequest",
    "extract_placeholders",
    "resolve_agent",
]
