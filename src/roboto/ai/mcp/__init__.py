# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""MCP servers: external servers that offer tools over the Model Context Protocol (MCP), which Roboto's AI can call.

:py:class:`~roboto.ai.mcp.McpServerRecord` describes a registered server, and
:py:class:`~roboto.ai.mcp.McpTokenRecord` a user's OAuth connection to it. Request classes such as
:py:class:`~roboto.ai.mcp.RegisterMcpServerRequest` are the bodies of the ``/v1/mcp`` routes that register, connect
and configure a server. No SDK method sends or returns these models.
"""

from .operations import (
    AdminRegisterMcpServerRequest,
    CopyMcpServerAllowedToolsRequest,
    OAuthCallbackRequest,
    RegisterMcpServerRequest,
    RegistrationMode,
    SetMcpServerOrgContextRequest,
    SetMcpServerOrgCredentialRequest,
    StartOAuthFlowResponse,
    UpdateMcpServerAllowedToolsRequest,
    UpdateMcpServerOrgsRequest,
    UpdateMcpServerRequest,
)
from .record import (
    McpServerOrgContextRecord,
    McpServerOrgCredentialRecord,
    McpServerRecord,
    McpServerStatus,
    McpTokenRecord,
    McpTokenStatus,
    McpToolInfo,
)

__all__ = [
    "AdminRegisterMcpServerRequest",
    "CopyMcpServerAllowedToolsRequest",
    "McpServerOrgContextRecord",
    "McpServerOrgCredentialRecord",
    "McpServerRecord",
    "McpServerStatus",
    "McpTokenRecord",
    "McpTokenStatus",
    "McpToolInfo",
    "OAuthCallbackRequest",
    "RegisterMcpServerRequest",
    "RegistrationMode",
    "SetMcpServerOrgContextRequest",
    "SetMcpServerOrgCredentialRequest",
    "StartOAuthFlowResponse",
    "UpdateMcpServerAllowedToolsRequest",
    "UpdateMcpServerOrgsRequest",
    "UpdateMcpServerRequest",
]
