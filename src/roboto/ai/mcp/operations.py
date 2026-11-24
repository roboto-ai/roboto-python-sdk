# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum
import typing

import pydantic


class RegistrationMode(str, enum.Enum):
    """Registration mode of an MCP server: how Roboto gets the OAuth 2.0 client it connects users to the server with."""

    DCR = "dcr"
    """Roboto registers its own client with the server's authorization server, by Dynamic Client Registration.

    It reads the OAuth endpoints from the metadata that authorization server publishes. Dynamic Client Registration is
    defined by RFC 7591: https://datatracker.ietf.org/doc/html/rfc7591
    """

    MANUAL = "manual"
    """The caller supplies the OAuth endpoints, client ID and client secret."""


# Roboto's AI names each of a server's tools <display_name>__<tool_name>, and the AI model accepts tool names of at
# most 64 letters, digits, hyphens and underscores. Capping display_name at 32 leaves room for the tool name.
_DISPLAY_NAME_PATTERN = r"^[a-zA-Z0-9_-]+$"
_DISPLAY_NAME_MAX_LENGTH = 32


class RegisterMcpServerRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/mcp/servers``.

    Registers an external Model Context Protocol (MCP) server, whose tools Roboto's AI can call, for the caller's
    organization only. Only organization administrators may send it. No SDK method sends it. When a server at
    ``server_url`` is already registered for the organization, Roboto returns that server and changes nothing.

    How Roboto gets the server's OAuth client depends on ``registration_mode``:

    - ``RegistrationMode.DCR`` reads the endpoints from the metadata ``oauth_issuer_url`` publishes and registers a
      client there, ignoring ``authorization_endpoint``, ``token_endpoint``, ``revocation_endpoint``, ``client_id``
      and ``client_secret``. An authorization server that publishes no such metadata, or does not offer Dynamic Client
      Registration, raises ``RobotoInvalidRequestException``; register the server with ``RegistrationMode.MANUAL``
      instead.
    - ``RegistrationMode.MANUAL`` takes the client from the request. Leaving out ``oauth_issuer_url``,
      ``authorization_endpoint``, ``token_endpoint``, ``client_id`` or ``client_secret`` raises
      ``RobotoInvalidRequestException``.

    A URL that does not use ``https`` or resolve to a public address raises ``RobotoInvalidRequestException``.
    Building it raises ``pydantic.ValidationError`` when:

    - ``display_name`` is empty.
    - ``display_name`` is longer than 32 characters.
    - ``display_name`` holds a character other than a letter, digit, hyphen or underscore.
    """

    registration_mode: RegistrationMode = RegistrationMode.DCR
    """How Roboto gets the server's OAuth client. Defaults to ``RegistrationMode.DCR``."""

    server_url: str
    """URL of the server's MCP endpoint, which must use the Streamable HTTP transport."""

    display_name: str = pydantic.Field(pattern=_DISPLAY_NAME_PATTERN, max_length=_DISPLAY_NAME_MAX_LENGTH)
    """Human-readable name of the server, such as ``GitHub``: 1 to 32 letters, digits, hyphens and underscores."""

    oauth_issuer_url: typing.Optional[str] = None
    """URL of the OAuth 2.0 authorization server. With ``RegistrationMode.DCR``, ``None`` uses ``server_url``."""

    authorization_endpoint: typing.Optional[str] = None
    """URL of the OAuth 2.0 authorization endpoint. Used only with ``RegistrationMode.MANUAL``."""

    token_endpoint: typing.Optional[str] = None
    """URL of the OAuth 2.0 token endpoint. Used only with ``RegistrationMode.MANUAL``."""

    client_id: typing.Optional[str] = None
    """OAuth 2.0 client ID from the provider's developer settings. Used only with ``RegistrationMode.MANUAL``."""

    client_secret: typing.Optional[str] = None
    """OAuth 2.0 client secret from the provider's developer settings. Used only with ``RegistrationMode.MANUAL``."""

    revocation_endpoint: typing.Optional[str] = None
    """URL of the OAuth 2.0 token revocation endpoint, or ``None`` if the provider has none.

    Used only with ``RegistrationMode.MANUAL``.
    """

    scopes: list[str] = pydantic.Field(default_factory=list)
    """OAuth 2.0 scopes to request when a user connects the server. Defaults to none."""

    extra_auth_params: dict[str, str] = pydantic.Field(default_factory=dict)
    """Further query parameters for the provider's authorization URL, such as ``{"audience": "api.atlassian.com"}``.

    Standard OAuth 2.0, PKCE and OpenID Connect parameter names, such as ``state``, ``scope`` and ``prompt``, raise
    ``RobotoInvalidRequestException``.
    """

    allowed_tools: typing.Optional[dict[str, bool]] = None
    """Ignored: the server starts with no tool allowlist, which Roboto fills in when the AI first lists its tools.

    ``AdminRegisterMcpServerRequest.allowed_tools`` describes how Roboto fills it in.
    """


class StartOAuthFlowResponse(pydantic.BaseModel):
    """Response body of ``POST /v1/mcp/servers/{server_id}/oauth/start``.

    Roboto returns it when it starts connecting the caller's own account to an MCP server, in the caller's
    organization. Send the user to ``authorization_url``, then pass the ``code`` and ``state`` the provider returns
    in ``OAuthCallbackRequest`` within 10 minutes.
    """

    authorization_url: str
    """URL of the provider's authorization page to send the user to."""

    state: str
    """Single-use token that ties the provider's response to this flow. Pass it back in ``OAuthCallbackRequest``."""


class OAuthCallbackRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/mcp/oauth/callback``.

    Completes the flow ``StartOAuthFlowResponse`` began: Roboto exchanges ``code`` for the user's tokens and stores
    them. The user who started the flow must send it, in the same organization. A ``state`` that is unknown, more than
    10 minutes old, or already used raises ``RobotoNotFoundException``; one another user or organization started
    raises ``RobotoUnauthorizedException``. A provider that rejects the code raises ``RobotoInvalidRequestException``.
    """

    code: str
    """Authorization code the provider returned after the user authorized Roboto."""

    state: str
    """``StartOAuthFlowResponse.state`` of the flow this request completes."""


class AdminRegisterMcpServerRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/mcp/admin/servers``.

    Registers an external MCP server for the organizations in ``org_ids``, or for every organization. Only Roboto
    administrators may send it. No SDK method sends it. Unlike ``RegisterMcpServerRequest``, it always creates a new
    server, even when one is already registered at ``server_url``, and it stores ``allowed_tools``. The two requests
    share their other behavior: ``RegisterMcpServerRequest`` describes how ``registration_mode`` decides which fields
    Roboto uses, and which values Roboto and ``pydantic.ValidationError`` reject.
    """

    registration_mode: RegistrationMode = RegistrationMode.MANUAL
    """How Roboto gets the server's OAuth client. Defaults to ``RegistrationMode.MANUAL``."""

    server_url: str
    """URL of the server's MCP endpoint, which must use the Streamable HTTP transport."""

    display_name: str = pydantic.Field(pattern=_DISPLAY_NAME_PATTERN, max_length=_DISPLAY_NAME_MAX_LENGTH)
    """Human-readable name of the server, such as ``GitHub``: 1 to 32 letters, digits, hyphens and underscores."""

    oauth_issuer_url: typing.Optional[str] = None
    """URL of the OAuth 2.0 authorization server, such as ``https://github.com``.

    With ``RegistrationMode.DCR``, ``None`` uses ``server_url``.
    """

    authorization_endpoint: typing.Optional[str] = None
    """URL of the OAuth 2.0 authorization endpoint. Used only with ``RegistrationMode.MANUAL``."""

    token_endpoint: typing.Optional[str] = None
    """URL of the OAuth 2.0 token endpoint. Used only with ``RegistrationMode.MANUAL``."""

    client_id: typing.Optional[str] = None
    """OAuth 2.0 client ID from the provider's developer settings. Used only with ``RegistrationMode.MANUAL``."""

    client_secret: typing.Optional[str] = None
    """OAuth 2.0 client secret from the provider's developer settings. Used only with ``RegistrationMode.MANUAL``."""

    scopes: list[str] = pydantic.Field(default_factory=list)
    """OAuth 2.0 scopes to request when a user connects the server. Defaults to none."""

    revocation_endpoint: typing.Optional[str] = None
    """URL of the OAuth 2.0 token revocation endpoint, or ``None`` if the provider has none.

    Used only with ``RegistrationMode.MANUAL``.
    """

    org_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the organizations that can use the server. An empty list makes it visible to every organization."""

    extra_auth_params: dict[str, str] = pydantic.Field(default_factory=dict)
    """Further query parameters for the provider's authorization URL, such as ``{"audience": "api.atlassian.com"}``.

    Standard OAuth 2.0, PKCE and OpenID Connect parameter names, such as ``state``, ``scope`` and ``prompt``, raise
    ``RobotoInvalidRequestException``.
    """

    allowed_tools: typing.Optional[dict[str, bool]] = None
    """Tools Roboto's AI may call on the server, as a map of tool name to whether it is enabled.

    The AI cannot call a tool missing from the map. ``None`` leaves the allowlist unset until the AI first lists the
    server's tools, when Roboto fills it in with every tool the server offers: if any tool carries the MCP
    ``readOnlyHint`` annotation, only tools marked read-only are enabled, and otherwise every tool is.
    """


class UpdateMcpServerRequest(pydantic.BaseModel):
    """No SDK method or Roboto route uses this model.

    A ``display_name`` that is empty, longer than 32 characters, or holds a character other than a letter, digit,
    hyphen or underscore raises ``pydantic.ValidationError``.
    """

    display_name: typing.Optional[str] = pydantic.Field(
        default=None, pattern=_DISPLAY_NAME_PATTERN, max_length=_DISPLAY_NAME_MAX_LENGTH
    )
    """Human-readable name of the server: 1 to 32 letters, digits, hyphens and underscores."""

    scopes: typing.Optional[list[str]] = None
    """OAuth 2.0 scopes to request when a user connects the server."""


class UpdateMcpServerOrgsRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/mcp/admin/servers/{server_id}/orgs``.

    Only Roboto administrators may send it. No SDK method sends it. ``org_ids`` replaces the organizations that can see
    the server. A non-empty list deletes the server's OAuth connections and organization-wide tokens in every
    organization outside it, including when it scopes a server every organization could see. An empty list makes the
    server visible to every organization and deletes nothing.
    """

    org_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the organizations that can use the server. An empty list makes it visible to every organization."""


class UpdateMcpServerAllowedToolsRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/mcp/admin/servers/{server_id}/allowed-tools``.

    Only Roboto administrators may send it. No SDK method sends it.
    """

    allowed_tools: typing.Optional[dict[str, bool]] = None
    """Tools Roboto's AI may call on the server, as a map of tool name to whether it is enabled.

    ``None`` clears the allowlist, and Roboto fills it in again the next time the AI lists the server's tools, as
    ``AdminRegisterMcpServerRequest.allowed_tools`` describes.
    """


class CopyMcpServerAllowedToolsRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/mcp/admin/servers/{server_id}/copy-allowed-tools``.

    Replaces the server's tool allowlist with another server's. Only Roboto administrators may send it. No SDK method
    sends it.
    """

    source_server_id: str
    """ID of the server whose tool allowlist to copy."""


_ORG_CONTEXT_MAX_LENGTH = 4000


class SetMcpServerOrgContextRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/mcp/servers/{server_id}/context``.

    Sets text that tells Roboto's AI how the caller's organization uses an MCP server, such as which repositories or
    projects to work in, replacing any already set. Only organization administrators may send it. No SDK method sends
    it. The AI receives the text with its instructions in every conversation in the organization, including those of
    members who have not connected the server. The 4000-character limit bounds how much organization-written text the AI
    receives as instructions. A longer ``context`` raises ``pydantic.ValidationError``.
    """

    context: str = pydantic.Field(default="", max_length=_ORG_CONTEXT_MAX_LENGTH)
    """Text to give the AI, at most 4000 characters. An empty string clears it."""


class SetMcpServerOrgCredentialRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/mcp/servers/{server_id}/org-credential``.

    Sets the organization-wide token the caller's organization uses for the server, replacing any already set. Only
    organization administrators may send it. No SDK method sends it. An empty ``secret_name`` raises
    ``pydantic.ValidationError``.
    """

    secret_name: str = pydantic.Field(min_length=1)
    """Name of a :py:class:`~roboto.domain.secrets.Secret` in the caller's organization, whose value is the token.

    Roboto sends the token to the server as a bearer token. A name that matches no secret raises
    ``RobotoInvalidRequestException``.
    """
