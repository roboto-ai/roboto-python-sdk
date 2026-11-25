# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
import urllib.parse

from ...http import RobotoClient
from ...sentinels import NotSet, NotSetType, is_set, remove_not_set
from ..agent_thread import (
    AgentThread,
    AgentThreadRecord,
    StartAgentThreadRequest,
    ThreadVisibility,
)
from ..core import AnalysisScope
from .record import (
    AgentRecord,
    AgentSubject,
    CreateAgentRequest,
    LaunchAgentRequest,
    TemplateVariable,
    UpdateAgentRequest,
)


class Agent:
    """An agent: an AI worker an organization defines and runs on its data.

    An agent is a saved request to start a thread, with typed ``{{name}}`` placeholders, optionally paired with goals.
    Each launch fills the placeholders with its own values and starts a
    :py:class:`~roboto.ai.agent_thread.AgentThread`, so one agent, such as a triage agent with a fixed label
    vocabulary and a dataset ID placeholder, can run on many datasets.

    Get an ``Agent`` from ``create``, ``from_id``, ``from_name``, or ``for_org``. To wrap an
    :py:class:`~roboto.ai.agent.AgentRecord` already fetched from Roboto, build an ``Agent`` from it directly. Each
    instance holds a copy of the agent's record, which ``update`` replaces with Roboto's response.

    Args:
        record: Record of the agent.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
    """

    __record: AgentRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        request_template: StartAgentThreadRequest,
        variables: typing.Optional[collections.abc.Sequence[TemplateVariable]] = None,
        description: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Agent":
        """Create an agent.

        Args:
            name: Human-readable name of the agent, unique within its organization.
            request_template: Request that starts each of the agent's threads, with ``{{name}}`` placeholders where
                launch values go. A placeholder can appear anywhere in a string value, but not in a dictionary key.
            variables: Variables of the agent, exactly one for each placeholder name in ``request_template``.
                ``None`` declares none.
            description: Human-readable description of the agent. ``None`` sets none.
            caller_org_id: Organization to create the agent in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new agent.

        Raises:
            RobotoConflictException: The organization already has an agent with this name.
            RobotoInvalidRequestException: ``variables`` and the placeholders in ``request_template`` do not name
                the same set of variables; the template's goals mix dataset and session subjects, or a goal names a
                resource that is missing or in another organization; or the template's ``available_skills`` names a
                skill that is missing, private, in another organization, or pinned to a version it does not have.

        Examples:
            Create an agent with one dataset ID variable:

            >>> from roboto.ai.agent import Agent, TemplateVariable, TemplateVariableType
            >>> from roboto.ai.agent_thread import StartAgentThreadRequest, AgentMessage
            >>> request_template = StartAgentThreadRequest(
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
        """Fetch an agent by its ID.

        Args:
            agent_id: Unique ID of the agent, beginning with ``agt_``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No agent has this ID, or it is in an organization the caller does not belong to.
            RobotoUnauthorizedException: The caller is a guest of the agent's organization and holds no role that
                turns on the ``use_ai`` switch.

        Examples:
            >>> agent = Agent.from_id("agt_12345")
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
        """Fetch an agent by its name.

        Agent names are unique within an organization, so a name and an organization identify one agent. Renaming an
        agent leaves its ID unchanged; to keep finding the same agent after it is renamed, use ``from_id``.

        Args:
            name: Human-readable name of the agent.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            owner_org_id: Organization that owns the agent. Defaults to the organization the caller acts in.

        Raises:
            RobotoNotFoundException: The organization has no agent with this name.

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
        """List the agents of an organization, newest first.

        Fetches the agents a page at a time, as the generator is iterated.

        Args:
            org_id: Organization whose agents to list. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Examples:
            Print every agent's name:

            >>> for agent in Agent.for_org():
            ...     print(agent.name)

            Count the agents of one organization:

            >>> count = sum(1 for _ in Agent.for_org(org_id="og_12345"))
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
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def agent_id(self) -> str:
        """Unique ID of the agent, beginning with ``agt_``. Renaming the agent leaves it unchanged."""
        return self.__record.agent_id

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the agent."""
        return self.__record.org_id

    @property
    def name(self) -> str:
        """Human-readable name of the agent, unique within its organization."""
        return self.__record.name

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of the agent, or ``None`` if it has none."""
        return self.__record.description

    @property
    def request_template(self) -> StartAgentThreadRequest:
        """Request that starts each of the agent's threads, with ``{{name}}`` placeholders where launch values go.

        :py:attr:`~roboto.ai.agent.AgentRecord.request_template` says where a placeholder can appear.
        """
        return self.__record.request_template

    @property
    def variables(self) -> list[TemplateVariable]:
        """Variables of the agent, exactly one for each placeholder name in ``request_template``."""
        return self.__record.variables

    @property
    def subject(self) -> typing.Optional[AgentSubject]:
        """Kind of resource the agent is launched on, or ``None`` for an agent with no subject.

        Roboto computes it as :py:attr:`~roboto.ai.agent.AgentRecord.subject` describes.
        """
        return self.__record.subject

    @property
    def created(self) -> datetime.datetime:
        """Time the agent was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """ID of the user who created the agent."""
        return self.__record.created_by

    @property
    def modified(self) -> datetime.datetime:
        """Time the agent was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """ID of the user who last modified the agent."""
        return self.__record.modified_by

    @property
    def record(self) -> AgentRecord:
        """Record of the agent that this instance holds."""
        return self.__record

    def launch(
        self,
        values: typing.Optional[dict[str, str]] = None,
        visibility: ThreadVisibility = ThreadVisibility.ORG,
        analysis_scope: typing.Optional[AnalysisScope] = None,
    ) -> AgentThread:
        """Launch the agent: fill its placeholders with ``values`` and start a thread.

        Before it starts the thread, Roboto checks that each ID-typed value names a dataset, device, collection, or
        session in the agent's organization. The thread belongs to the agent's organization, whichever organization
        the caller acts in, and its :py:attr:`~roboto.ai.core.AgentThreadRecord.created_from_agent_id` names
        this agent. A guest of that organization launches an agent only when a role they hold lets them use AI.

        Args:
            values: Value of each variable, keyed by variable name. A variable left out uses its default. ``None``
                supplies no values.
            visibility: Visibility of the new thread, which replaces the ``visibility`` in the agent's request
                template. Defaults to :py:attr:`~roboto.ai.agent_thread.ThreadVisibility.ORG`, which lets every
                member of the organization read the thread. ``PRIVATE`` limits it to the user who launches the agent.
            analysis_scope: Data the new thread analyzes, combined with the ``analysis_scope`` in the agent's request
                template. Each field set here replaces the template's, and each field left ``None`` keeps the
                template's. ``None`` keeps the template's scope unchanged.

        Returns:
            The new thread. Roboto has already started the AI's first reply, which
            :py:meth:`~roboto.ai.agent_thread.AgentThread.run` waits for and
            :py:meth:`~roboto.ai.agent_thread.AgentThread.events` follows.

        Raises:
            RobotoInvalidRequestException: ``values`` names a variable the agent does not have, leaves out a
                required variable that has no default, or gives an ID-typed variable an ID that names no resource
                in the agent's organization.
            RobotoNotFoundException: The agent has been deleted, or the caller cannot see it.
            RobotoUnauthorizedException: The caller is a guest of the agent's organization and holds no role that
                lets them use AI.

        Examples:
            >>> agent = Agent.from_name("triage")
            >>> thread = agent.launch(values={"dataset_id": "ds_12345"})
            >>> thread.run()
        """
        request = LaunchAgentRequest(
            values=values if values is not None else {},
            visibility=visibility,
            analysis_scope=analysis_scope,
        )
        encoded_agent_id = urllib.parse.quote(self.agent_id, safe="")
        record = self.__roboto_client.post(
            f"v1/ai/agents/{encoded_agent_id}/launch",
            data=request,
        ).to_record(AgentThreadRecord)
        return AgentThread(record=record, roboto_client=self.__roboto_client)

    def update(
        self,
        name: typing.Union[str, NotSetType] = NotSet,
        description: typing.Union[typing.Optional[str], NotSetType] = NotSet,
        request_template: typing.Union[StartAgentThreadRequest, NotSetType] = NotSet,
        variables: typing.Union[collections.abc.Sequence[TemplateVariable], NotSetType] = NotSet,
    ) -> "Agent":
        """Update the agent's properties. Arguments left unset leave their property unchanged.

        Roboto checks the agent's variables against its placeholders after applying the update, so a call that
        changes the placeholders in ``request_template`` must also pass the matching ``variables``.

        Args:
            name: Human-readable name of the agent, unique within its organization.
            description: Human-readable description of the agent. ``None`` clears it.
            request_template: Request that starts each of the agent's threads, with ``{{name}}`` placeholders where
                launch values go.
            variables: Variables of the agent, exactly one for each placeholder name in ``request_template``.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoConflictException: Another agent in the organization has the name ``name``.
            RobotoInvalidRequestException: The updated agent fails a check that ``create`` applies.
            RobotoNotFoundException: The agent has been deleted, or the caller cannot see it.

        Examples:
            Change the agent's description:

            >>> agent = Agent.from_id("agt_12345")
            >>> agent.update(description="Triage a dataset against the label vocabulary.")

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
        """Delete the agent. This cannot be undone.

        Threads launched from the agent remain readable, and their ``created_from_agent_id`` still holds the agent's
        ID. The organization can then create another agent with the same name.

        Raises:
            RobotoNotFoundException: The agent has already been deleted, or the caller cannot see it.

        Examples:
            >>> agent = Agent.from_name("retired_triage")
            >>> agent.delete()
        """
        encoded_agent_id = urllib.parse.quote(self.agent_id, safe="")
        self.__roboto_client.delete(
            f"v1/ai/agents/{encoded_agent_id}",
        )

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the record this instance holds, as a JSON-compatible dictionary.

        Examples:
            >>> agent = Agent.from_id("agt_12345")
            >>> agent.to_dict()["agent_id"]
            'agt_12345'
        """
        return self.__record.model_dump(mode="json")
