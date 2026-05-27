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
    """An AI skill — a versioned, accessibility-scoped procedure the chat AI can apply.

    Use :py:meth:`create` to create a new skill, :py:meth:`from_id` /
    :py:meth:`from_name` to load existing ones, and :py:meth:`list_for_org` to
    iterate. The constructor is internal.
    """

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        body: str,
        accessibility: SkillAccessibility = SkillAccessibility.Private,
        tags: typing.Optional[collections.abc.Sequence[str]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> Skill:
        """Create a new skill plus its first version (version=1).

        The skill is created in the caller's organization. With the default
        :py:attr:`SkillAccessibility.Private` accessibility only the caller can
        see, edit, or delete it. :py:attr:`SkillAccessibility.Org` makes it
        readable by all org members (author-only to edit);
        :py:attr:`SkillAccessibility.OrgEditable` additionally lets any member
        who subscribes edit its versions, name, and tags. The author is
        auto-subscribed at creation time and the new version is pinned as
        Available to AI. Other org members must :py:meth:`subscribe` to see the
        skill in their AI auto-invoke registry.
        Pass ``tags`` to seed the skill's tag list at creation time;
        later edits flow through :class:`UpdateSkillMetadataRequest`.

        Examples:
            >>> skill = Skill.create(
            ...     name="qa-review",
            ...     description="Run when the user asks for a QA review of a dataset.",
            ...     body="Step 1: load the dataset summary...",
            ...     accessibility=SkillAccessibility.Org,
            ...     tags=["qa-review", "triage"],
            ... )
            >>> skill.skill_id
            'sk_...'
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
        """Load a skill by its skill_id.

        Raises:
            RobotoNotFoundException: No skill with this id exists, or the caller
                cannot see it (visibility-gated).

        Examples:
            >>> skill = Skill.from_id("sk_abc123")
            >>> skill.name
            'qa-review'
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/skills/id/{skill_id}").to_record(SkillRecord)
        return cls(record=record, roboto_client=roboto_client)

    @classmethod
    def from_name(
        cls,
        name: str,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> Skill:
        """Load a skill by name in the caller's organization.

        Skill names are unique within ``(org_id, accessibility)``. When both a
        private and an org-shared skill share a name in the same org, this
        method returns the caller's private one (the manual-invocation
        tie-break — see :func:`SkillsRepo.get_skill_by_name`).

        Args:
            name: Skill name. URL-encoded by the SDK.
            caller_org_id: Look up in this org. Defaults to the caller's
                current org.

        Raises:
            RobotoNotFoundException: No skill with this name is visible to the
                caller in the target org.

        Examples:
            >>> skill = Skill.from_name("qa-review")
            >>> skill.accessibility
            <SkillAccessibility.Org: 'org'>
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        # Backend `unquote`s this segment, so we must encode it. Skill names are
        # restricted to a safe charset by SKILL_NAME_PATTERN, but always encode
        # to keep the SDK robust against any future relaxation of that rule.
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
        """Return the distinct tags found on skills the caller can see in this org.

        Visibility-filtered the same way :py:meth:`list_for_org` is — private
        skills owned by other users contribute no tags. Suitable for powering
        a tag-autocomplete UI.

        Examples:
            >>> Skill.list_known_tags()
            ['qa-review', 'triage', 'experiments']
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
        """Yield :class:`SkillSummary` items for every skill the caller can see in their org.

        The summary includes the latest version (MAX(version)) and the caller's
        own subscription row when one exists. When ``scope`` is provided the
        result is restricted to either ``Personal`` (authored or subscribed) or
        ``Org`` (org-shared skills the caller did not author, regardless of
        subscription state). Omit ``scope`` to receive every visible skill in
        one stream.

        Examples:
            List the caller's Personal-tab skills:

            >>> for summary in Skill.list_for_org(scope=SkillListScope.Personal):
            ...     print(summary.skill.name, summary.subscription.ai_version if summary.subscription else None)

            Iterate every visible skill (Personal + Org), in one pass:

            >>> all_visible = list(Skill.list_for_org())
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
        return self.__record.skill_id

    @property
    def name(self) -> str:
        return self.__record.name

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def accessibility(self) -> SkillAccessibility:
        return self.__record.accessibility

    @property
    def created_by(self) -> str:
        return self.__record.created_by

    @property
    def tags(self) -> list[str]:
        return list(self.__record.tags)

    @property
    def record(self) -> SkillRecord:
        return self.__record

    def refresh(self) -> Skill:
        """Re-fetch this skill's record from the server and return self.

        Useful after another caller may have updated the skill — bumps the
        local view past stale data.

        Examples:
            >>> skill.refresh()
            >>> skill.name  # now reflects any server-side rename
            'qa-review'
        """
        self.__record = self.__roboto_client.get(f"v1/skills/id/{self.__record.skill_id}").to_record(SkillRecord)
        return self

    def update_metadata(self, request: UpdateSkillMetadataRequest) -> Skill:
        """Update skill-level metadata (name, accessibility, tags).

        Editing the name and tags is permitted for the author and — on an
        :py:attr:`SkillAccessibility.OrgEditable` skill — for any subscribed
        org member. Changing ``accessibility`` is always author-only.

        Updates apply in place; the local record is replaced with the
        server's authoritative copy.

        Examples:
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
        """Hard-delete this skill. Author-only, including on ``OrgEditable`` skills.

        Cascades to all versions and subscriptions. Existing chats keep any
        fabricated ``load_skill`` tool_use / tool_result blocks they've
        already produced — the body is captured at invocation time and
        written into the transcript.

        Examples:
            >>> skill.delete()
        """
        self.__roboto_client.delete(f"v1/skills/id/{self.__record.skill_id}")

    def list_versions(self) -> list[SkillVersionRecord]:
        """List every version of this skill, newest first.

        Examples:
            >>> for version in skill.list_versions():
            ...     print(version.version, version.description)
        """
        return self.__roboto_client.get(
            f"v1/skills/id/{self.__record.skill_id}/versions",
        ).to_record_list(SkillVersionRecord)

    def get_version(self, version: int) -> SkillVersionRecord:
        """Load a specific version of this skill.

        Raises:
            RobotoNotFoundException: No such version exists.

        Examples:
            >>> v2 = skill.get_version(2)
            >>> print(v2.body)
        """
        return self.__roboto_client.get(
            f"v1/skills/id/{self.__record.skill_id}/versions/{version}",
        ).to_record(SkillVersionRecord)

    def create_version(self, request: CreateSkillVersionRequest) -> SkillVersionRecord:
        """Add a new version to this skill. The server assigns ``MAX(version) + 1``.

        Permitted for the author and — on an :py:attr:`SkillAccessibility.OrgEditable`
        skill — for any subscribed org member. Subscribers who pinned the previous
        version stay on that pin until they explicitly re-pin — the new row does
        not auto-promote.

        Examples:
            >>> v2 = skill.create_version(
            ...     CreateSkillVersionRequest(
            ...         description="Run when ...",
            ...         body="Updated procedure ...",
            ...     )
            ... )
            >>> v2.version
            2
        """
        return self.__roboto_client.post(
            f"v1/skills/id/{self.__record.skill_id}/versions",
            data=request,
        ).to_record(SkillVersionRecord)

    def update_version(self, version: int, request: UpdateSkillVersionRequest) -> SkillVersionRecord:
        """Edit fields on an existing version in place.

        Permitted for the author and — on an :py:attr:`SkillAccessibility.OrgEditable`
        skill — for any subscribed org member.

        Subscribers pinned to this version see the new body on their next AI
        invocation; there is no per-edit revision. Use :py:meth:`create_version`
        when callers should not be auto-migrated.

        Examples:
            >>> skill.update_version(2, UpdateSkillVersionRequest(body="..."))
        """
        return self.__roboto_client.put(
            f"v1/skills/id/{self.__record.skill_id}/versions/{version}",
            data=request,
        ).to_record(SkillVersionRecord)

    def delete_version(self, version: int) -> None:
        """Delete a single version. If it's the last remaining version, the parent skill is removed too.

        Permitted for the author and — on an :py:attr:`SkillAccessibility.OrgEditable`
        skill — for any subscribed org member. A subscribed non-author may not
        delete the *last* remaining version: that cascades into a full skill
        delete, which is author-only. The author has no such restriction.

        Subscriptions pinned to the deleted version have their ``ai_version``
        nulled out via a server-side trigger; the subscription row survives.

        Examples:
            >>> skill.delete_version(1)
        """
        self.__roboto_client.delete(f"v1/skills/id/{self.__record.skill_id}/versions/{version}")

    def subscribe(self) -> SkillSubscriptionRecord:
        """Subscribe to this skill — adds it to the caller's Personal tab.

        Idempotent: if the caller is already subscribed (or is the author), the
        existing row is returned unchanged. New subscriptions default to
        ``ai_version=None`` (not yet exposed to AI). Use :py:meth:`set_ai_version`
        to enable AI auto-invocation.

        Examples:
            >>> sub = skill.subscribe()
            >>> sub.ai_version is None
            True
        """
        return self.__roboto_client.post(
            f"v1/skills/id/{self.__record.skill_id}/subscribe",
        ).to_record(SkillSubscriptionRecord)

    def unsubscribe(self) -> None:
        """Remove the caller's subscription row — removes the skill from their Personal tab.

        No-op if there is no subscription. Authors who unsubscribe from their own
        skill can re-subscribe later; authorship is unchanged.

        Examples:
            >>> skill.unsubscribe()
        """
        self.__roboto_client.delete(f"v1/skills/id/{self.__record.skill_id}/subscribe")

    def set_ai_version(self, version: typing.Optional[int]) -> SkillSubscriptionRecord:
        """Pin (or clear) which version of this skill the AI auto-invokes for the caller.

        Pass an integer to expose that exact version to AI auto-invocation; pass
        ``None`` to disable AI auto-invocation while keeping the subscription.
        Implicitly subscribes the caller if no row exists yet. Visibility-gated;
        the caller does not have to be the author.

        Examples:
            Pin version 2 for AI auto-invoke:

            >>> skill.set_ai_version(2)

            Stop the AI from auto-invoking this skill, but stay subscribed
            so manual chip-invocation still works:

            >>> skill.set_ai_version(None)
        """
        return self.__roboto_client.put(
            f"v1/skills/id/{self.__record.skill_id}/subscribe",
            data=SetSkillSubscriptionRequest(ai_version=version),
        ).to_record(SkillSubscriptionRecord)
