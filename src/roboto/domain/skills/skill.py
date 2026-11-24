# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import typing
import urllib.parse

from ...http import RobotoClient
from .operations import (
    CreateSkillRequest,
    CreateSkillVersionRequest,
    SetSkillSubscriptionRequest,
    SkillListScope,
    UpdateSkillMetadataRequest,
    UpdateSkillVersionRequest,
)
from .record import (
    SkillAccessibility,
    SkillRecord,
    SkillSubscriptionRecord,
    SkillSummary,
    SkillVersionRecord,
)


class Skill:
    """A skill: a stored, versioned procedure, written in Markdown, that Roboto's AI can apply during a conversation.

    A skill belongs to one organization, and the user who created it is its author. Its
    :py:class:`~roboto.domain.skills.SkillAccessibility` sets who can see, invoke, and edit it. Its procedure is in its
    versions, each a :py:class:`~roboto.domain.skills.SkillVersionRecord`. A user's subscription to the skill adds it
    to their personal skills and pins the version, if any, that the AI may apply for them without being asked.

    Get a ``Skill`` from ``create``, ``from_id``, or ``from_name``. ``list_for_org`` and ``get_summary`` return
    :py:class:`~roboto.domain.skills.SkillSummary` records instead. Each instance holds a copy of the skill's record:
    ``update_metadata`` updates that copy from Roboto's response, and ``refresh`` fetches changes made elsewhere.
    """

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        body: str,
        accessibility: SkillAccessibility = SkillAccessibility.Private,
        tags: typing.Optional[collections.abc.Sequence[str]] = None,
        relevant_topics: typing.Optional[collections.abc.Sequence[str]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> Skill:
        """Create a skill and its first version, version ``1``.

        Roboto subscribes the author with version ``1`` pinned, so Roboto's AI can apply the skill for the author at
        once. Other members of the organization who can see the skill must ``subscribe`` and pin a version with
        ``set_ai_version`` before the AI applies it for them on its own.

        Args:
            name: Name of the skill, at most 120 characters, matching
                :py:const:`~roboto.domain.skills.SKILL_NAME_PATTERN`. The name of a skill shared with the organization
                is unique among the organization's shared skills; a private skill's name is unique among its author's
                private skills in the organization.
            description: Text telling the AI when to apply the skill, at most 500 characters
                (:py:const:`~roboto.domain.skills.MAX_SKILL_DESCRIPTION_LENGTH`).
            body: Procedure the AI follows when it applies the skill.
            accessibility: Who can see, invoke, and edit the skill. Defaults to
                :py:attr:`~roboto.domain.skills.SkillAccessibility.Private`, which limits all three to the author.
            tags: Tags to set on the skill. ``None`` sets none.
            relevant_topics: Names of the topics the first version's procedure investigates, such as ``"/imu/data"``.
                ``None`` names none. See :py:attr:`~roboto.domain.skills.SkillVersionRecord.relevant_topics` for how
                the AI uses them.
            caller_org_id: Organization to create the skill in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoConflictException: The name is already taken, under the rules given for ``name``.
            pydantic.ValidationError: ``name`` is longer than 120 characters or does not match ``SKILL_NAME_PATTERN``,
                or ``description`` is longer than 500 characters.

        Examples:
            >>> skill = Skill.create(
            ...     name="qa-review",
            ...     description="Run when the user asks for a QA review of a dataset.",
            ...     body="Step 1: load the dataset summary...",
            ...     accessibility=SkillAccessibility.Org,
            ...     tags=["qa-review", "triage"],
            ...     relevant_topics=["/imu/data", "/gps/fix"],
            ... )
            >>> print(skill.skill_id)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.post(
            "v1/skills/create",
            data=CreateSkillRequest(
                name=name,
                accessibility=accessibility,
                description=description,
                body=body,
                tags=list(tags) if tags is not None else [],
                relevant_topics=list(relevant_topics) if relevant_topics is not None else [],
            ),
            caller_org_id=caller_org_id,
        ).to_record(SkillRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_id(
        cls,
        skill_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> Skill:
        """Fetch a skill by its ID.

        Args:
            skill_id: ID of the skill.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No skill has this ID, or the caller cannot see it.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> print(skill.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/skills/id/{skill_id}").to_record(SkillRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def get_summary(
        cls,
        skill_id: str,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> SkillSummary:
        """Fetch a skill's summary: the skill, its latest version, and the caller's subscription to it.

        Returns the same summary ``list_for_org`` yields for this skill, without listing the organization's skills.

        Args:
            skill_id: ID of the skill.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: No skill has this ID, or the caller cannot see it.

        Examples:
            >>> summary = Skill.get_summary("sk_12345")
            >>> print(summary.latest_version.version)
            >>> if summary.subscription is None:
            ...     print("Not subscribed")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        return roboto_client.get(f"v1/skills/id/{skill_id}/summary").to_record(SkillSummary)

    @classmethod
    def from_name(
        cls,
        name: str,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> Skill:
        """Fetch a skill by name.

        A private skill can have the same name as a skill shared with the organization. When the caller authored such
        a private skill, this method returns it rather than the shared one.

        Args:
            name: Name of the skill.
            caller_org_id: Organization to look the skill up in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: The organization has no skill with this name that the caller can see.

        Examples:
            >>> skill = Skill.from_name("qa-review")
            >>> print(skill.accessibility)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        # Roboto URL-decodes this path segment. SKILL_NAME_PATTERN admits no character that needs encoding, but
        # encoding keeps the request valid for any name.
        encoded = urllib.parse.quote(name, safe="")
        record = roboto_client.get(
            f"v1/skills/name/{encoded}",
            caller_org_id=caller_org_id,
        ).to_record(SkillRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def list_known_tags(
        cls,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> list[str]:
        """List the distinct tags on the skills the caller can see in the organization, in alphabetical order.

        Tags on other users' private skills are left out.

        Args:
            caller_org_id: Organization to list the tags of. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Examples:
            >>> for tag in Skill.list_known_tags():
            ...     print(tag)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        return roboto_client.get(
            "v1/skills/tags",
            caller_org_id=caller_org_id,
        ).to_string_list()

    @classmethod
    def list_for_org(
        cls,
        scope: typing.Optional[SkillListScope] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator[SkillSummary, None, None]:
        """List summaries of the skills the caller can see in the organization, most recently modified first.

        The caller can see every skill shared with the organization, the private skills they authored, and the skills
        that Roboto ships. Each summary holds the skill's record, its latest version, and the caller's subscription to
        it, if any. Summaries are fetched a page at a time as you iterate.

        Args:
            scope: Which of those skills to list: :py:attr:`~roboto.domain.skills.SkillListScope.Personal` for the
                skills the caller authored or subscribed to, :py:attr:`~roboto.domain.skills.SkillListScope.Org`
                for the shared skills someone else authored, or
                :py:attr:`~roboto.domain.skills.SkillListScope.Roboto` for the skills that Roboto ships. ``None``
                lists every skill the caller can see, with the skills that Roboto ships first.
            caller_org_id: Organization to list the skills of. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            :py:class:`~roboto.domain.skills.SkillSummary` of each skill.

        Examples:
            Print the skills the caller authored or subscribed to, with the version each one pins:

            >>> for summary in Skill.list_for_org(scope=SkillListScope.Personal):
            ...     print(summary.skill.name, summary.subscription.ai_version if summary.subscription else None)

            Collect every skill the caller can see:

            >>> all_visible = list(Skill.list_for_org())

            List only the skills that Roboto ships:

            >>> for summary in Skill.list_for_org(scope=SkillListScope.Roboto):
            ...     print(summary.skill.name, [resource.slug for resource in summary.latest_version.resources])
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        next_token: typing.Optional[str] = None
        while True:
            query: dict[str, typing.Any] = {}
            if next_token:
                query["page_token"] = next_token
            if scope is not None:
                query["scope"] = scope.value
            page = roboto_client.get(
                "v1/skills",
                caller_org_id=caller_org_id,
                query=query,
            ).to_paginated_list(SkillSummary)
            yield from page.items
            if not page.next_token:
                break
            next_token = page.next_token

    def __init__(self, record: SkillRecord, roboto_client: RobotoClient):
        self.__record: SkillRecord = record
        self.__roboto_client: RobotoClient = roboto_client

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Skill):
            return False
        return self.__record == other.__record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def skill_id(self) -> str:
        """Unique ID of the skill, beginning with ``sk_``."""
        return self.__record.skill_id

    @property
    def name(self) -> str:
        """Human-readable name of the skill.

        See :py:attr:`~roboto.domain.skills.SkillRecord.name` for where it is unique.
        """
        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the skill."""
        return self.__record.org_id

    @property
    def accessibility(self) -> SkillAccessibility:
        """Who can see, invoke, and edit the skill."""
        return self.__record.accessibility

    @property
    def created_by(self) -> str:
        """ID of the user who created the skill, its author."""
        return self.__record.created_by

    @property
    def tags(self) -> list[str]:
        """Tags on the skill, such as ``"qa-review"``.

        The list is a copy; change the skill's tags with ``update_metadata``, as
        :py:attr:`~roboto.domain.skills.SkillRecord.tags` describes.
        """
        return list(self.__record.tags)

    @property
    def record(self) -> SkillRecord:
        """Record of the skill that this instance holds."""
        return self.__record

    def refresh(self) -> Skill:
        """Fetch the skill's record from Roboto again, replacing this instance's copy.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: The skill has been deleted, or the caller can no longer see it.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> print(skill.refresh().name)
        """
        self.__record = self.__roboto_client.get(f"v1/skills/id/{self.__record.skill_id}").to_record(SkillRecord)
        return self

    def update_metadata(self, request: UpdateSkillMetadataRequest) -> Skill:
        """Update the skill's name, accessibility, or tags.

        The author can change every field. On an :py:attr:`~roboto.domain.skills.SkillAccessibility.OrgEditable` skill,
        any member of the organization subscribed to it can change the name and tags, but only the author can change
        its accessibility. Making a shared skill private deletes every subscription to it except the author's.

        Args:
            request: Fields to change. A field left unset is unchanged.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoConflictException: The new name is already taken, or the request shares a private skill whose name
                a shared skill already has.
            RobotoUnauthorizedException: The request sets ``accessibility`` and the caller is not the author.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> skill.update_metadata(
            ...     UpdateSkillMetadataRequest(
            ...         accessibility=SkillAccessibility.Org,
            ...         put_tags=["qa-review"],
            ...     )
            ... )
        """
        self.__record = self.__roboto_client.put(
            f"v1/skills/id/{self.__record.skill_id}",
            data=request,
        ).to_record(SkillRecord)
        return self

    def delete(self) -> None:
        """Delete the skill, with all its versions and every subscription to it.

        Only the author can delete a skill, whatever its accessibility. Conversations in which Roboto's AI already
        applied the skill keep the procedure it received.

        Raises:
            RobotoUnauthorizedException: The caller is not the skill's author.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> skill.delete()
        """
        self.__roboto_client.delete(f"v1/skills/id/{self.__record.skill_id}")

    def list_versions(self) -> list[SkillVersionRecord]:
        """List the skill's versions, highest version number first.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> for version in skill.list_versions():
            ...     print(version.version, version.description)
        """
        return self.__roboto_client.get(
            f"v1/skills/id/{self.__record.skill_id}/versions",
        ).to_record_list(SkillVersionRecord)

    def get_version(self, version: int) -> SkillVersionRecord:
        """Fetch one version of the skill.

        Args:
            version: Number of the version.

        Raises:
            RobotoNotFoundException: The skill has no version with this number.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> v2 = skill.get_version(2)
            >>> print(v2.body)
        """
        return self.__roboto_client.get(
            f"v1/skills/id/{self.__record.skill_id}/versions/{version}",
        ).to_record(SkillVersionRecord)

    def create_version(self, request: CreateSkillVersionRequest) -> SkillVersionRecord:
        """Create a version of the skill, numbered one higher than its highest version.

        The author can create versions, and so can any member of the organization subscribed to an
        :py:attr:`~roboto.domain.skills.SkillAccessibility.OrgEditable` skill. Subscribers keep the version they
        pinned; for Roboto's AI to apply the new version for them, each must pin it with ``set_ai_version``.

        Args:
            request: Description, procedure, and relevant topics of the new version.

        Returns:
            Record of the new version.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> v2 = skill.create_version(
            ...     CreateSkillVersionRequest(
            ...         description="Run when ...",
            ...         body="Updated procedure ...",
            ...         relevant_topics=["/imu/data", "/gps/fix"],
            ...     )
            ... )
            >>> print(v2.version)
        """
        return self.__roboto_client.post(
            f"v1/skills/id/{self.__record.skill_id}/versions",
            data=request,
        ).to_record(SkillVersionRecord)

    def update_version(self, version: int, request: UpdateSkillVersionRequest) -> SkillVersionRecord:
        """Update a version of the skill in place.

        The same users who can create versions can update them. Roboto keeps no copy of the earlier values, so
        subscribers who pinned this version get the new content the next time Roboto's AI applies the skill for them.
        To leave them on the current content, create a version with ``create_version`` instead.

        Args:
            version: Number of the version to update.
            request: Fields to change. A field left unset is unchanged.

        Returns:
            Record of the version, as updated.

        Raises:
            RobotoNotFoundException: The skill has no version with this number.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> skill.update_version(2, UpdateSkillVersionRequest(body="..."))
        """
        return self.__roboto_client.put(
            f"v1/skills/id/{self.__record.skill_id}/versions/{version}",
            data=request,
        ).to_record(SkillVersionRecord)

    def delete_version(self, version: int) -> None:
        """Delete a version of the skill, and the skill itself when no other version remains.

        The author can delete any version. On an :py:attr:`~roboto.domain.skills.SkillAccessibility.OrgEditable`
        skill, any member of the organization subscribed to it can delete every version but the last: deleting the
        last version deletes the skill, which only the author can do. Subscriptions that pinned the deleted version
        remain, with ``ai_version`` set to ``None``.

        Args:
            version: Number of the version to delete.

        Raises:
            RobotoNotFoundException: The skill has no version with this number.
            RobotoUnauthorizedException: The version is the skill's last and the caller is not its author.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> skill.delete_version(1)
        """
        self.__roboto_client.delete(f"v1/skills/id/{self.__record.skill_id}/versions/{version}")

    def subscribe(self) -> SkillSubscriptionRecord:
        """Subscribe the caller to the skill, adding it to their personal skills.

        Any caller who can see the skill can subscribe. A new subscription pins no version, so Roboto's AI applies the
        skill only when the caller invokes it; pin a version with ``set_ai_version``. If the caller is already
        subscribed, Roboto returns that subscription unchanged.

        Returns:
            Caller's subscription to the skill.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> subscription = skill.subscribe()
            >>> print(subscription.ai_version)
        """
        return self.__roboto_client.post(
            f"v1/skills/id/{self.__record.skill_id}/subscribe",
        ).to_record(SkillSubscriptionRecord)

    def unsubscribe(self) -> None:
        """Delete the caller's subscription to the skill, so Roboto's AI no longer applies it without being asked.

        Does nothing if the caller is not subscribed. A caller who is not the author can no longer invoke the skill
        and no longer sees it among their personal skills. An author who unsubscribes still sees the skill there and
        can subscribe again.

        Examples:
            >>> skill = Skill.from_id("sk_12345")
            >>> skill.unsubscribe()
        """
        self.__roboto_client.delete(f"v1/skills/id/{self.__record.skill_id}/subscribe")

    def set_ai_version(self, version: typing.Optional[int]) -> SkillSubscriptionRecord:
        """Pin the version of the skill that Roboto's AI may apply for the caller without being asked.

        Subscribes the caller if they are not subscribed. Any caller who can see the skill can pin a version.

        Args:
            version: Number of the version to pin. ``None`` keeps the subscription but stops the AI from applying
                the skill on its own; the caller can still invoke it in a chat message.

        Returns:
            Caller's subscription to the skill.

        Raises:
            RobotoNotFoundException: The skill has no version with this number.

        Examples:
            Let the AI apply version 2 on its own:

            >>> skill = Skill.from_id("sk_12345")
            >>> skill.set_ai_version(2)

            Stop the AI from applying the skill on its own, but keep the subscription so the caller can still
            invoke it in a chat message:

            >>> skill.set_ai_version(None)
        """
        return self.__roboto_client.put(
            f"v1/skills/id/{self.__record.skill_id}/subscribe",
            data=SetSkillSubscriptionRequest(ai_version=version),
        ).to_record(SkillSubscriptionRecord)
