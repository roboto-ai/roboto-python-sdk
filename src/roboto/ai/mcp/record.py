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
    """Status of an MCP server registration: whether Roboto's AI can use the server."""

    ACTIVE = "active"
    """Ready for use. Roboto's AI calls only servers with this status."""

    PENDING_SETUP = "pending_setup"
    """Unused. Roboto registers every server as ``ACTIVE`` and never changes its status."""

    ERROR = "error"
    """Unused. Roboto registers every server as ``ACTIVE`` and never changes its status."""


class McpTokenStatus(StrEnum):
    """Status of a user's OAuth connection to an MCP server: whether Roboto can still get an access token from it."""

    VALID = "valid"
    """Roboto can get an access token from the connection.

    An access token past its expiry keeps this status until Roboto next needs it, when Roboto renews it with the
    connection's refresh token or changes the status.
    """

    EXPIRED = "expired"
    """The access token expired and the connection has no refresh token to renew it, so the user must connect again."""

    REFRESH_FAILED = "refresh_failed"
    """Renewing the access token with the connection's refresh token failed, so the user must connect again."""


class McpServerRecord(pydantic.BaseModel):
    """Data record of a registered MCP server, as ``GET /v1/mcp/servers/{server_id}`` returns it.

    ``POST /v1/mcp/servers`` and ``GET /v1/mcp/servers`` also return it. An MCP server is an external server that
    offers tools over the Model Context Protocol (MCP), which Roboto's AI can call in the organizations the server is
    registered for. An organization administrator registers a server for their own organization; a Roboto
    administrator can register one for several organizations, or for every organization. Users connect to it with
    OAuth (:py:class:`~roboto.ai.mcp.McpTokenRecord`), or Roboto's AI uses a token the organization sets
    (:py:class:`~roboto.ai.mcp.McpServerOrgCredentialRecord`).
    """

    server_id: str
    """Unique ID of the MCP server, beginning with ``mcp_``."""

    display_name: str
    """Human-readable name of the MCP server, such as ``GitHub``."""

    server_url: str
    """URL of the server's MCP endpoint, which Roboto connects to over MCP's Streamable HTTP transport."""

    oauth_issuer_url: str
    """URL of the OAuth 2.0 authorization server that issues tokens for the MCP server."""

    client_id: str
    """OAuth client ID Roboto presents to the authorization server. Roboto never returns the client secret."""

    scopes: list[str] = pydantic.Field(default_factory=list)
    """OAuth scopes Roboto requests when a user connects the server. An empty list requests no particular scopes."""

    status: McpServerStatus
    """Status of the MCP server registration."""

    registration_mode: str = "dcr"
    """How Roboto got its OAuth client for the server, as the value of a :py:class:`~roboto.ai.mcp.RegistrationMode`.

    - ``"dcr"``: Roboto registered itself with the authorization server through OAuth Dynamic Client Registration.
    - ``"manual"``: whoever registered the server supplied the client ID and secret.
    """

    extra_auth_params: dict[str, str] = pydantic.Field(default_factory=dict)
    """Further query parameters Roboto adds to the authorization URL when a user connects the server.

    Some providers require one, such as Atlassian's ``audience``. They cannot override the OAuth parameters Roboto
    sets itself.
    """

    org_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the organizations the MCP server is registered for. Empty when every organization can use it.

    A response to a request made in one organization lists only that organization, even when the server is registered
    for others too. Only the routes for Roboto administrators list every organization.
    """

    allowed_tools: typing.Optional[dict[str, bool]] = None
    """Each tool name the server offers, mapped to ``True`` if Roboto's AI may call it or ``False`` if it is blocked.

    ``None`` until Roboto's AI first loads the server's tools. On that first load, Roboto fills it in. If any of the
    server's tools carries MCP's ``readOnlyHint`` annotation, only tools annotated read-only are allowed; otherwise
    every tool is. A tool missing from the map, such as one the server added later, is blocked. Only a Roboto
    administrator can change it.
    """

    created: datetime.datetime
    """Time the MCP server was registered."""

    created_by: str
    """Principal that registered the MCP server, as ``<type>:<id>``, such as ``user:<user_id>``."""

    modified: datetime.datetime
    """Time the MCP server was last modified. Changing the organizations it is registered for does not update it."""

    modified_by: str
    """Principal that last modified the MCP server, in the same ``<type>:<id>`` form as ``created_by``.

    It is ``system`` when Roboto filled in ``allowed_tools``.
    """


class McpTokenRecord(pydantic.BaseModel):
    """Data record of a user's OAuth connection to an MCP server, as ``GET /v1/mcp/tokens`` returns it.

    ``POST /v1/mcp/oauth/callback`` also returns it, when the user finishes connecting the server. A user connects a
    server separately in each organization, and Roboto's AI then calls the server's tools as that user. The record
    holds the connection's status only; Roboto never returns its access or refresh token.
    """

    server_id: str
    """ID of the MCP server the user connected."""

    user_id: str
    """ID of the user who connected the server, which for a person is their email address."""

    org_id: str
    """ID of the organization the connection belongs to."""

    token_status: McpTokenStatus
    """Status of the connection."""

    expires_at: typing.Optional[datetime.datetime] = None
    """Time the access token expires, or ``None`` if the authorization server did not say."""

    scopes: list[str] = pydantic.Field(default_factory=list)
    """OAuth scopes the authorization server granted, or the MCP server's requested scopes when it did not list them."""

    created: datetime.datetime
    """Time the user connected the server in this organization."""

    modified: datetime.datetime
    """Time the connection was last modified, as when Roboto renewed its access token or changed its status."""


class McpServerOrgContextRecord(pydantic.BaseModel):
    """Data record of an organization's instructions to Roboto's AI about an MCP server.

    ``GET /v1/mcp/servers/{server_id}/context`` returns it, and ``PUT /v1/mcp/servers/{server_id}/context`` returns
    it after setting the instructions. An organization administrator writes the instructions, such as which
    repositories or project names to use, and Roboto's AI reads them in every chat in the organization, whether or
    not the user has connected the server.
    """

    server_id: str
    """ID of the MCP server the instructions are for."""

    org_id: str
    """ID of the organization that owns the instructions."""

    context: str
    """Plain-text instructions for Roboto's AI, at most 4000 characters. An empty string gives Roboto's AI none."""

    created: datetime.datetime
    """Time the instructions were first set."""

    created_by: str
    """Principal that first set the instructions, as ``<type>:<id>``, such as ``user:<user_id>``."""

    modified: datetime.datetime
    """Time the instructions were last set."""

    modified_by: str
    """Principal that last set the instructions, in the same ``<type>:<id>`` form as ``created_by``."""


class McpToolInfo(pydantic.BaseModel):
    """A tool an MCP server offers to Roboto's AI.

    No SDK method or Roboto route uses this model.
    """

    name: str
    """Name of the tool, as the MCP server reports it."""

    description: str
    """Human-readable description of the tool."""

    input_schema: dict[str, typing.Any]
    """JSON Schema of the tool's input parameters."""

    server_id: str
    """ID of the MCP server that offers the tool."""


class McpServerOrgCredentialRecord(pydantic.BaseModel):
    """Data record of an organization's own token for an MCP server, as ``GET /v1/mcp/org-credentials`` returns it.

    ``PUT /v1/mcp/servers/{server_id}/org-credential`` also returns it. An organization administrator sets the token
    by naming one of the organization's secrets that holds it. Roboto's AI calls the server with it for members who
    have not connected the server themselves or must connect again, and for callers that are not people, such as
    agents a trigger starts. The record names the secret and never holds the token.
    """

    server_id: str
    """ID of the MCP server the token is for."""

    org_id: str
    """ID of the organization that owns the token."""

    secret_name: str
    """Name of the :py:class:`~roboto.domain.secrets.Secret` that holds the token.

    Roboto reads the secret's value each time it calls the server, and sends it as ``Authorization: Bearer <token>``.
    """

    created: datetime.datetime
    """Time the organization's token for this server was first set."""

    created_by: str
    """Principal that first set the token, as ``<type>:<id>``, such as ``user:<user_id>``."""

    modified: datetime.datetime
    """Time an organization administrator last chose the secret. Changing the secret's value does not update it."""

    modified_by: str
    """Principal that last chose the secret, in the same ``<type>:<id>`` form as ``created_by``."""
