# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ...compat import StrEnum


class McpServerStatus(StrEnum):
    """Status of a registered MCP server."""

    ACTIVE = "active"
    """Server is registered and ready for use."""

    PENDING_SETUP = "pending_setup"
    """Server registration is in progress (e.g., awaiting Dynamic Client Registration)."""

    ERROR = "error"
    """Server registration encountered an error."""


class McpTokenStatus(StrEnum):
    """Status of a user's OAuth token for an MCP server."""

    VALID = "valid"
    """Token is valid and can be used for requests."""

    EXPIRED = "expired"
    """Access token has expired. May be refreshable via refresh token."""

    REFRESH_FAILED = "refresh_failed"
    """Refresh token failed. User must re-authorize."""


class McpServerRecord(pydantic.BaseModel):
    """A registered external MCP server. May be global or scoped to specific orgs."""

    server_id: str
    """Unique identifier for this server registration."""

    display_name: str
    """User-friendly display name (e.g., 'GitHub', 'GitLab')."""

    server_url: str
    """MCP server Streamable HTTP endpoint URL."""

    oauth_issuer_url: str
    """OAuth2 authorization server URL for this MCP server."""

    client_id: str
    """OAuth2 client ID."""

    scopes: list[str] = pydantic.Field(default_factory=list)
    """OAuth2 scopes requested during authorization."""

    status: McpServerStatus
    """Current status of the server registration."""

    registration_mode: str = "dcr"
    """How this server was registered: 'dcr' or 'manual'."""

    extra_auth_params: dict[str, str] = pydantic.Field(default_factory=dict)
    """Extra query parameters appended to the OAuth authorization URL (e.g. audience for Atlassian)."""

    org_ids: list[str] = pydantic.Field(default_factory=list)
    """Org IDs this server is scoped to. Empty = global (visible to all orgs)."""

    allowed_tools: typing.Optional[dict[str, bool]] = None
    """Map of tool name to enabled flag. None = not yet configured (auto-populates on first discovery).
    Keys are all known tools from the server; True = allowed, False = blocked."""

    created: datetime.datetime
    """Timestamp when this server was registered."""

    created_by: str
    """User who first registered this server."""

    modified: datetime.datetime
    """Timestamp when this server record was last modified."""

    modified_by: str
    """User who last modified this server record."""


class McpTokenRecord(pydantic.BaseModel):
    """Per-user, per-org OAuth token metadata for an MCP server.

    Token values (access_token, refresh_token) are never exposed — this record
    contains only status metadata for display in the UI.
    """

    server_id: str
    """Server this token is for."""

    user_id: str
    """User who authorized this token."""

    org_id: str
    """Org context this token is scoped to."""

    token_status: McpTokenStatus
    """Current status of the token."""

    expires_at: typing.Optional[datetime.datetime] = None
    """When the access token expires, if known."""

    scopes: list[str] = pydantic.Field(default_factory=list)
    """Scopes granted by this token."""

    created: datetime.datetime
    """Timestamp when this token was first created."""

    modified: datetime.datetime
    """Timestamp when this token was last refreshed or modified."""


class McpServerOrgContextRecord(pydantic.BaseModel):
    """Per-org context for an MCP server.

    Org admins set this plaintext to provide the AI with org-specific
    instructions about how the server should be used (e.g., which repos,
    project names, conventions).
    """

    server_id: str
    """Server this context applies to."""

    org_id: str
    """Org that owns this context."""

    context: str
    """Plaintext context injected into the AI system prompt."""

    created: datetime.datetime
    created_by: str
    modified: datetime.datetime
    modified_by: str


class McpToolInfo(pydantic.BaseModel):
    """Describes a tool discovered from a remote MCP server."""

    name: str
    """Tool name as reported by the MCP server."""

    description: str
    """Human-readable description of the tool."""

    input_schema: dict[str, typing.Any]
    """JSON Schema describing the tool's input parameters."""

    server_id: str
    """Server this tool belongs to."""
