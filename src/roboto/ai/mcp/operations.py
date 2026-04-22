# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum
import typing

import pydantic


class RegistrationMode(str, enum.Enum):
    DCR = "dcr"
    MANUAL = "manual"


# Display name is concatenated with each tool name as `{display_name}__{tool_name}`
# and passed to the Bedrock/Claude API, which requires tool names to match
# `^[a-zA-Z0-9_-]{1,64}$`. Keep display_name well short of 64 so there's room
# for the tool name half after the `__` separator.
_DISPLAY_NAME_PATTERN = r"^[a-zA-Z0-9_-]+$"
_DISPLAY_NAME_MAX_LENGTH = 32


class RegisterMcpServerRequest(pydantic.BaseModel):
    """Request to register an MCP server. Used by org admins.

    In DCR mode, OAuth metadata is auto-discovered and client credentials are
    obtained via Dynamic Client Registration.

    In Manual mode, the caller provides all OAuth credentials upfront.
    """

    registration_mode: RegistrationMode = RegistrationMode.DCR

    server_url: str
    """MCP server Streamable HTTP endpoint URL."""

    display_name: str = pydantic.Field(pattern=_DISPLAY_NAME_PATTERN, max_length=_DISPLAY_NAME_MAX_LENGTH)
    """User-friendly display name (e.g., 'GitHub'). Alphanumerics, hyphens, and underscores only."""

    oauth_issuer_url: typing.Optional[str] = None
    """OAuth2 authorization server URL. Required for DCR if different from server_url.
    Required for Manual mode."""

    # Manual-mode fields (required when registration_mode=manual)
    authorization_endpoint: typing.Optional[str] = None
    """OAuth2 authorization endpoint URL."""

    token_endpoint: typing.Optional[str] = None
    """OAuth2 token endpoint URL."""

    client_id: typing.Optional[str] = None
    """OAuth2 client ID from the provider's developer settings."""

    client_secret: typing.Optional[str] = None
    """OAuth2 client secret from the provider's developer settings."""

    revocation_endpoint: typing.Optional[str] = None
    """OAuth2 token revocation endpoint URL, if supported."""

    scopes: list[str] = pydantic.Field(default_factory=list)
    """OAuth2 scopes to request during authorization."""

    extra_auth_params: dict[str, str] = pydantic.Field(default_factory=dict)
    """Extra query parameters appended to the OAuth authorization URL.
    For example, Atlassian requires {"audience": "api.atlassian.com", "prompt": "consent"}."""

    allowed_tools: typing.Optional[dict[str, bool]] = None
    """Tool allowlist: map of tool name to enabled flag. None = configure later (auto-populates on first discovery)."""


class StartOAuthFlowResponse(pydantic.BaseModel):
    """Response from starting an OAuth flow."""

    authorization_url: str
    """URL to redirect the user to for authorization."""

    state: str
    """CSRF state token. Must be passed back in the callback."""


class OAuthCallbackRequest(pydantic.BaseModel):
    """Request to complete an OAuth flow after the user has authorized."""

    code: str
    """Authorization code from the OAuth provider."""

    state: str
    """CSRF state token from the original flow start."""


class AdminRegisterMcpServerRequest(pydantic.BaseModel):
    """Admin request to register an MCP server. Supports both DCR and manual modes.

    Admins can scope the server to specific orgs via org_ids, or leave it empty
    for global visibility.
    """

    registration_mode: RegistrationMode = RegistrationMode.MANUAL

    server_url: str
    """MCP server Streamable HTTP endpoint URL."""

    display_name: str = pydantic.Field(pattern=_DISPLAY_NAME_PATTERN, max_length=_DISPLAY_NAME_MAX_LENGTH)
    """User-friendly display name (e.g., 'GitHub'). Alphanumerics, hyphens, and underscores only."""

    oauth_issuer_url: typing.Optional[str] = None
    """OAuth2 authorization server base URL (e.g., 'https://github.com')."""

    authorization_endpoint: typing.Optional[str] = None
    """OAuth2 authorization endpoint URL."""

    token_endpoint: typing.Optional[str] = None
    """OAuth2 token endpoint URL."""

    client_id: typing.Optional[str] = None
    """OAuth2 client ID from the provider's developer settings."""

    client_secret: typing.Optional[str] = None
    """OAuth2 client secret from the provider's developer settings."""

    scopes: list[str] = pydantic.Field(default_factory=list)
    """OAuth2 scopes to request during authorization."""

    revocation_endpoint: typing.Optional[str] = None
    """OAuth2 token revocation endpoint URL, if supported."""

    org_ids: list[str] = pydantic.Field(default_factory=list)
    """Org IDs this server is scoped to. Empty = global (visible to all orgs)."""

    extra_auth_params: dict[str, str] = pydantic.Field(default_factory=dict)
    """Extra query parameters appended to the OAuth authorization URL.
    For example, Atlassian requires {"audience": "api.atlassian.com", "prompt": "consent"}."""

    allowed_tools: typing.Optional[dict[str, bool]] = None
    """Tool allowlist: map of tool name to enabled flag. None = configure later (auto-populates on first discovery)."""


class UpdateMcpServerRequest(pydantic.BaseModel):
    """Request to update an MCP server registration."""

    display_name: typing.Optional[str] = pydantic.Field(
        default=None, pattern=_DISPLAY_NAME_PATTERN, max_length=_DISPLAY_NAME_MAX_LENGTH
    )
    """Updated display name. Alphanumerics, hyphens, and underscores only."""

    scopes: typing.Optional[list[str]] = None
    """Updated scopes."""


class UpdateMcpServerOrgsRequest(pydantic.BaseModel):
    """Admin request to update the org scoping for an MCP server.

    The provided org_ids fully replace the current set. An empty list makes
    the server global (visible to all orgs). Tokens for removed orgs are
    cascade-deleted.
    """

    org_ids: list[str] = pydantic.Field(default_factory=list)
    """New set of org IDs. Empty = global (visible to all orgs)."""


class UpdateMcpServerAllowedToolsRequest(pydantic.BaseModel):
    """Admin request to set the tool allowlist for an MCP server.

    Keys are tool names, values indicate whether the tool is enabled (True) or blocked (False).
    Set to None to clear the allowlist (reverts to auto-populate on first discovery).
    """

    allowed_tools: typing.Optional[dict[str, bool]] = None


class CopyMcpServerAllowedToolsRequest(pydantic.BaseModel):
    """Admin request to copy the tool allowlist from another server."""

    source_server_id: str
    """Server ID to copy the allowed_tools dict from."""


_ORG_CONTEXT_MAX_LENGTH = 4000


class SetMcpServerOrgContextRequest(pydantic.BaseModel):
    """Request to set per-org context for an MCP server.

    The context is plaintext that gets injected into the AI system prompt
    so the AI knows how the org uses this server. Bounded to keep prompt
    size predictable and to limit the blast radius of injection from
    org-controlled text.
    Set to empty string to clear.
    """

    context: str = pydantic.Field(default="", max_length=_ORG_CONTEXT_MAX_LENGTH)
    """Plaintext context (max 4000 chars). Empty string clears it."""
