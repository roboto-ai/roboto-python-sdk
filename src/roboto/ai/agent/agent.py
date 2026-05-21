# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Public-surface wrapper around :class:`AgentRecord`.

Mirrors the codebase's well-entrenched record-plus-wrapper pattern
(:class:`~roboto.domain.actions.Action`,
:class:`~roboto.domain.devices.Device`) so callers do not have to thread
:class:`~roboto.http.RobotoClient` instances or remember route URLs.
"""

import collections.abc
import datetime
import typing
import urllib.parse

from ...http import RobotoClient
from ...sentinels import NotSet, NotSetType, is_set, remove_not_set
from ..agent_session import (
    AgentSession,
    AgentSessionRecord,
    SessionVisibility,
    StartAgentSessionRequest,
)
from .record import (
    AgentRecord,
    CreateAgentRequest,
    InvokeAgentRequest,
    TemplateVariable,
    UpdateAgentRequest,
)


class Agent:
    """A reusable, parameterized factory for :class:`AgentSession`.

    An :class:`Agent` captures a :class:`StartAgentSessionRequest` body
    with ``{{name}}`` placeholders alongside the
    :class:`TemplateVariable` declarations that those placeholders bind
    to. Invoking the agent substitutes caller-supplied values into the
    body, runs invoke-time existence checks for typed values (dataset
    ids, device ids), and starts a session via the same code path as
    :meth:`AgentSession.start`.

    The wrapper is to :class:`AgentRecord` what
    :class:`~roboto.domain.actions.Action` is to
    :class:`~roboto.domain.actions.action_record.ActionRecord`: the
    record carries the wire-shape data, this class carries the
    behaviors.

    Note:
        Agents cannot be instantiated directly through the constructor
        when starting from a name or an id; use :py:meth:`create`,
        :py:meth:`from_id`, or :py:meth:`from_name` to obtain
        :class:`Agent` instances.
    """

    __record: AgentRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        request_template: StartAgentSessionRequest,
        variables: typing.Optional[collections.abc.Sequence[TemplateVariable]] = None,
        description: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Agent":
        """Persist a new agent in the caller's organization.

        The platform fills :attr:`agent_id`, :attr:`org_id`,
        :attr:`created`, :attr:`created_by`, :attr:`modified`, and
        :attr:`modified_by` from the caller's identity. Every other
        field comes from this method's arguments.

        Args:
            name: Human-readable display name. Unique per
                ``(org_id, name)``; a second agent with the same name in
                the same org is rejected with
                :class:`RobotoConflictException`.
            request_template: The :class:`StartAgentSessionRequest` to
                clone at invoke time. Any string leaf may carry
                ``{{name}}`` placeholders; every referenced placeholder
                must appear in ``variables`` (and vice versa).
            variables: :class:`TemplateVariable` declarations. The set
                of names here must equal the set of placeholder names
                referenced anywhere in ``request_template``; a mismatch
                fails server-side validation with a 400.
            description: Free-form text rendered on the agent's detail
                and library pages.
            caller_org_id: Organization to create the agent in. If
                omitted and the caller belongs to exactly one
                organization, that organization is used; required when
                the caller belongs to multiple organizations.
            roboto_client: Optional :class:`RobotoClient` instance. If
                omitted, the default client configuration is used.

        Returns:
            The newly created :class:`Agent` instance.

        Raises:
            RobotoConflictException: An agent with the same name
                already exists in the org.
            RobotoInvalidRequestException: ``request_template`` and
                ``variables`` disagree about the placeholder set, or a
                variable name is invalid.
            RobotoUnauthorizedException: The caller lacks permission to
                create agents in the target organization.

        Examples:
            Create an agent with one dataset-typed variable:

            >>> from roboto.ai.agent import Agent, TemplateVariable, TemplateVariableType
            >>> from roboto.ai.agent_session import StartAgentSessionRequest, AgentMessage
            >>> request_template = StartAgentSessionRequest(
            ...     messages=[AgentMessage.text("Triage dataset {{dataset_id}}.")],
            ... )
            >>> agent = Agent.create(
            ...     name="triage",
            ...     request_template=request_template,
            ...     variables=[
            ...         TemplateVariable(name="dataset_id", type=TemplateVariableType.DATASET_ID),
            ...     ],
            ...     description="Apply the triage label vocabulary to a dataset.",
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        request = CreateAgentRequest(
            name=name,
            description=description,
            request_template=request_template,
            variables=list(variables) if variables is not None else [],
        )
        record = roboto_client.post(
            "v1/ai/agents",
            data=request,
            caller_org_id=caller_org_id,
        ).to_record(AgentRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls,
        agent_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Agent":
        """Load an :class:`Agent` by its canonical id.

        ``agent_id`` is platform-unique, so the SDK does not need the
        caller to declare which org the agent lives in — the route looks
        up the record and authorizes the caller against the record's
        ``org_id``.

        Args:
            agent_id: The platform-issued ``agt_<short>`` identifier.
            roboto_client: Optional :class:`RobotoClient`; defaults to
                the ambient configuration.

        Returns:
            The :class:`Agent` instance.

        Raises:
            RobotoNotFoundException: The agent does not exist or
                belongs to an organization the caller cannot read.

        Examples:
            >>> agent = Agent.from_id("agt_abc123")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        encoded_agent_id = urllib.parse.quote(agent_id, safe="")
        record = roboto_client.get(
            f"v1/ai/agents/{encoded_agent_id}",
        ).to_record(AgentRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_name(
        cls,
        name: str,
        roboto_client: typing.Optional[RobotoClient] = None,
        owner_org_id: typing.Optional[str] = None,
    ) -> "Agent":
        """Load an :class:`Agent` by its ``(org_id, name)`` handle.

        Mirrors :meth:`~roboto.domain.actions.Action.from_name`: name +
        owning org are jointly unique, so this returns at most one
        agent. Unlike :meth:`from_id` (which derives the org from the
        looked-up record), name lookup needs the org up-front and goes
        through the ``X-Roboto-Resource-Owner-Id`` header.
        ``agent_id`` (the canonical handle) stays stable across renames,
        so a script that pins by name follows renames; a script that
        pins by id does not.

        Args:
            name: The agent's :attr:`name`.
            roboto_client: Optional :class:`RobotoClient`; defaults to
                the ambient configuration.
            owner_org_id: Organization that owns the agent. If omitted
                and the caller belongs to one organization, that
                organization is used.

        Returns:
            The :class:`Agent` instance.

        Raises:
            RobotoNotFoundException: No agent with that name exists in
                the resolved organization.

        Examples:
            >>> agent = Agent.from_name("triage")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        encoded_name = urllib.parse.quote(name, safe="")
        record = roboto_client.get(
            f"v1/ai/agents/name/{encoded_name}",
            owner_org_id=owner_org_id,
        ).to_record(AgentRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def for_org(
        cls,
        org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Agent", None, None]:
        """Iterate every :class:`Agent` declared in an organization.

        Yields agents newest-first (by :attr:`created`) and paginates
        transparently; callers consume the generator without worrying
        about ``next_token``.

        Args:
            org_id: Organization to list agents for. If omitted and the
                caller belongs to exactly one organization, that
                organization is used.
            roboto_client: Optional :class:`RobotoClient`; defaults to
                the ambient configuration.

        Yields:
            :class:`Agent` instances, one per row, in newest-first
            order.

        Examples:
            Print every agent's name:

            >>> for agent in Agent.for_org():
            ...     print(agent.name)

            Count agents in a specific org:

            >>> count = sum(1 for _ in Agent.for_org(org_id="og_abc123"))
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        next_token: typing.Optional[str] = None
        while True:
            query_params: dict[str, typing.Any] = {}
            if next_token:
                query_params["page_token"] = next_token

            page = roboto_client.get(
                "v1/ai/agents",
                query=query_params,
                # ``v1/ai/agents`` is org-scoped via the caller header,
                # not a path parameter, so the caller's effective org is
                # used unless ``org_id`` was supplied here.
                caller_org_id=org_id,
            ).to_paginated_list(AgentRecord)

            for record in page.items:
                yield cls(record=record, roboto_client=roboto_client)

            next_token = page.next_token
            if not next_token:
                break

    def __init__(
        self,
        record: AgentRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> None:
        """Wrap an existing :class:`AgentRecord` with the public surface.

        Note:
            Prefer :py:meth:`create`, :py:meth:`from_id`, or
            :py:meth:`from_name`. The constructor is exposed for
            hydrating records returned by other SDK calls (e.g. an
            invoke response) into a wrapper without re-fetching.
        """
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def agent_id(self) -> str:
        """Platform-issued ``agt_<short>`` handle. Stable across renames."""
        return self.__record.agent_id

    @property
    def org_id(self) -> str:
        """Organization that owns this agent."""
        return self.__record.org_id

    @property
    def name(self) -> str:
        """Human-readable display name; unique within :attr:`org_id`."""
        return self.__record.name

    @property
    def description(self) -> typing.Optional[str]:
        """Free-form text rendered on the agent's detail and library pages."""
        return self.__record.description

    @property
    def request_template(self) -> StartAgentSessionRequest:
        """The :class:`StartAgentSessionRequest` cloned at invoke time."""
        return self.__record.request_template

    @property
    def variables(self) -> list[TemplateVariable]:
        """:class:`TemplateVariable` declarations. The set of names here
        equals the set of placeholders referenced in :attr:`request_template`."""
        return self.__record.variables

    @property
    def created(self) -> datetime.datetime:
        """Wall-clock time the agent was first persisted."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """User id of the original author."""
        return self.__record.created_by

    @property
    def modified(self) -> datetime.datetime:
        """Wall-clock time of the most recent successful update."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """User id who applied the most recent update; equals
        :attr:`created_by` for records never edited since creation."""
        return self.__record.modified_by

    @property
    def record(self) -> AgentRecord:
        """Underlying :class:`AgentRecord`.

        Wire shape used in API requests; may evolve over time. Prefer
        the public :class:`Agent` API unless you need direct record
        access.
        """
        return self.__record

    def invoke(
        self,
        values: typing.Optional[dict[str, str]] = None,
        visibility: SessionVisibility = SessionVisibility.ORG,
    ) -> AgentSession:
        """Resolve placeholders and start an :class:`AgentSession`.

        The platform substitutes ``values`` into :attr:`request_template`,
        runs invoke-time existence checks on typed values (``DATASET_ID``
        / ``DEVICE_ID``), and creates a session via the same code path
        as a bare :meth:`AgentSession.start`. The resulting session is
        owned by this agent's :attr:`org_id` (not the caller's default
        org), and its ``created_from_agent_id`` is stamped with this
        agent's :attr:`agent_id` so the agent detail page can list
        "sessions launched from here".

        Args:
            values: Variable name to caller-supplied value. Keys must
                match the names declared in :attr:`variables`; values
                are coerced to ``str`` before splicing into placeholders.
                Omit when every declared variable carries a ``default``.
            visibility: :class:`SessionVisibility` for the new session.
                Defaults to ``ORG`` because agents exist to share
                workflows; the caller passes ``PRIVATE`` to opt out per
                invocation. Overrides whatever the authored
                ``request_template`` carries.

        Returns:
            An :class:`AgentSession` wrapping the freshly created
            session. The session is fully hydrated (messages, status,
            continuation token) and ready for :meth:`AgentSession.run`
            or :meth:`AgentSession.events`.

        Raises:
            RobotoInvalidRequestException: ``values`` is missing a
                required variable, references an unknown variable, or
                a typed value (``DATASET_ID`` / ``DEVICE_ID``) names a
                resource that does not exist in the agent's org.
            RobotoNotFoundException: This agent has been deleted since
                the wrapper was loaded.
            RobotoUnauthorizedException: The caller is not a member of
                this agent's :attr:`org_id` or that org is not on a
                premium plan.

        Examples:
            >>> agent = Agent.from_name("triage")
            >>> session = agent.invoke(values={"dataset_id": "ds_abc123"})
            >>> session.run()
        """
        request = InvokeAgentRequest(
            values=values if values is not None else {},
            visibility=visibility,
        )
        encoded_agent_id = urllib.parse.quote(self.agent_id, safe="")
        record = self.__roboto_client.post(
            f"v1/ai/agents/{encoded_agent_id}/invoke",
            data=request,
        ).to_record(AgentSessionRecord)
        return AgentSession(record=record, roboto_client=self.__roboto_client)

    def update(
        self,
        name: typing.Union[str, NotSetType] = NotSet,
        description: typing.Union[typing.Optional[str], NotSetType] = NotSet,
        request_template: typing.Union[StartAgentSessionRequest, NotSetType] = NotSet,
        variables: typing.Union[collections.abc.Sequence[TemplateVariable], NotSetType] = NotSet,
    ) -> "Agent":
        """Apply a partial update.

        Each parameter defaults to :data:`NotSet` so omitting a field
        leaves it untouched on the server, while passing ``None`` for
        :attr:`description` clears it. ``request_template`` and
        ``variables`` are co-validated server-side after the merge: the
        post-update placeholder set must equal the post-update variable
        set, even if only one of the two fields was supplied.

        Args:
            name: Replace the display name. Subject to the same
                ``(org_id, name)`` uniqueness as :meth:`create`.
            description: Replace the description. Pass ``None`` to
                clear; omit to leave unchanged.
            request_template: Replace the :class:`StartAgentSessionRequest`.
            variables: Replace the variable declarations.

        Returns:
            ``self``, with :attr:`record` refreshed to the persisted
            state.

        Raises:
            RobotoConflictException: ``name`` collides with another
                agent in the same org.
            RobotoInvalidRequestException: The post-update placeholder
                set disagrees with the post-update variable set.
            RobotoNotFoundException: The agent has been deleted.
            RobotoUnauthorizedException: The caller is not a member of
                this agent's :attr:`org_id`.

        Examples:
            >>> agent.update(description="Triages a dataset against the v2 label vocab.")

            Clear the description:

            >>> agent.update(description=None)
        """
        update_kwargs: dict[str, typing.Any] = {}
        if is_set(name):
            update_kwargs["name"] = name
        if is_set(description):
            update_kwargs["description"] = description
        if is_set(request_template):
            update_kwargs["request_template"] = request_template
        if is_set(variables):
            update_kwargs["variables"] = list(typing.cast(collections.abc.Sequence[TemplateVariable], variables))

        request = remove_not_set(UpdateAgentRequest(**update_kwargs))
        encoded_agent_id = urllib.parse.quote(self.agent_id, safe="")
        record = self.__roboto_client.put(
            f"v1/ai/agents/{encoded_agent_id}",
            data=request,
        ).to_record(AgentRecord)
        self.__record = record
        return self

    def delete(self) -> None:
        """Permanently delete this agent.

        Sessions previously launched from this agent are unaffected —
        their ``created_from_agent_id`` references this agent's id
        independent of any foreign key, so they remain readable. Creating
        a new agent with the same name in the same org is allowed after
        deletion.

        Raises:
            RobotoNotFoundException: The agent has already been deleted.
            RobotoUnauthorizedException: The caller is not a member of
                this agent's :attr:`org_id`.

        Examples:
            >>> agent = Agent.from_name("retired_triage")
            >>> agent.delete()
        """
        encoded_agent_id = urllib.parse.quote(self.agent_id, safe="")
        self.__roboto_client.delete(
            f"v1/ai/agents/{encoded_agent_id}",
        )

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the JSON-serializable form of the underlying record."""
        return self.__record.model_dump(mode="json")
