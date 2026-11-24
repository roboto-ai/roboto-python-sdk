# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
from typing import Optional

import pydantic

from ...compat import StrEnum

MAX_SKILL_DESCRIPTION_LENGTH = 500
"""Maximum length of a skill description, in characters.

Roboto's AI reads the description of every skill available to it on each turn of a conversation, so descriptions
are kept short.
"""


class SkillAccessibility(StrEnum):
    """Accessibility of a skill: who can see, invoke, and edit it.

    Only a skill's author can delete it or change its accessibility, whatever its accessibility.
    """

    Private = "private"
    """Only the skill's author can see, invoke, or edit it."""

    Org = "org"
    """Every member of the skill's organization can see and invoke it, and only its author can edit it."""

    OrgEditable = "org-editable"
    """Every member of the skill's organization can see and invoke it, and subscribed members can also edit it.

    Members subscribed to the skill can edit its versions, name, and tags.
    """

    Roboto = "roboto"
    """A skill that Roboto writes and ships.

    Every member of an organization that Roboto has released the skill to can see and invoke it. Nobody can edit it,
    delete it, subscribe to it, or pin a version of it for the AI: those calls raise ``RobotoUnauthorizedException``,
    and the AI needs no subscription to load the skill. No request can give a skill this accessibility.

    The Roboto API never returns such a skill's instructions: the ``body`` of its version is empty, because the
    instructions are written for the AI and are not published. Its name, its description and its list of resources
    are returned.
    """


class SkillRecord(pydantic.BaseModel):
    """Data record of a skill, as the Roboto API returns it.

    A skill is a stored, versioned procedure, written in Markdown, that Roboto's AI can apply during a conversation.
    This record holds the skill's identity, ownership, and accessibility; the procedure itself is in its versions
    (``SkillVersionRecord``). :py:class:`~roboto.domain.skills.Skill` wraps this record with methods that act on the
    skill, and exposes it as :py:attr:`~roboto.domain.skills.Skill.record`.
    """

    skill_id: str
    """Unique ID of the skill, beginning with ``sk_``."""

    org_id: str
    """ID of the organization that owns the skill."""

    accessibility: SkillAccessibility
    """Who can see, invoke, and edit the skill."""

    name: str
    """Human-readable name of the skill.

    The name of a skill with ``SkillAccessibility`` ``Org`` or ``OrgEditable`` accessibility is unique among those
    skills in its organization. The name of a ``Private`` skill is unique among its author's private skills in the
    organization, so it can match the name of a skill shared with the organization.
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the skill, such as ``"qa-review"``.

    Tags belong to the skill, not to one version. Change them with
    :py:attr:`~roboto.domain.skills.UpdateSkillMetadataRequest.put_tags` and
    :py:attr:`~roboto.domain.skills.UpdateSkillMetadataRequest.remove_tags`.
    """

    created: datetime.datetime
    """Time the skill was created."""

    created_by: str
    """ID of the user who created the skill, its author."""

    modified: datetime.datetime
    """Time the skill's name, accessibility, or tags were last modified.

    Creating, editing, or deleting a version does not change it.
    """


class SkillResourceSummary(pydantic.BaseModel):
    """One resource of a skill, without its text.

    A resource is a part of a skill, such as one chapter of a guide, that Roboto's AI loads separately from the
    skill's ``body`` and from the skill's other resources. Its text is written for the AI, and the Roboto API does not
    return it.
    """

    slug: str
    """The resource's name, unique within its skill."""

    when_to_use: str
    """One line, written for people, that says when Roboto's AI reads the resource."""


class SkillVersionRecord(pydantic.BaseModel):
    """Data record of one version of a skill, as the Roboto API returns it.

    A version holds the skill's procedure and the description Roboto's AI uses to decide when to apply it. A version
    can be edited in place: every user who pinned it gets the edited procedure the next time the AI applies the skill.
    """

    skill_id: str
    """ID of the skill this version belongs to."""

    version: int
    """Version number, unique within the skill.

    The first version is ``1``, and each new version takes the number after the highest existing one.
    """

    description: str = pydantic.Field(max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    """Description of when to apply the skill.

    It is at most 500 characters (``MAX_SKILL_DESCRIPTION_LENGTH``). Roboto's AI reads the description of the
    version a user pinned to decide whether to apply the skill.
    """

    body: str
    """Procedure Roboto's AI follows when it applies the skill."""

    relevant_topics: list[str] = pydantic.Field(default_factory=list)
    """Names of the topics this version's procedure investigates, such as ``"/imu/data"``.

    The list is empty if the author named none. The names belong to the version, not the skill, so that a new
    version's procedure can investigate different topics. When Roboto's AI applies the skill to a dataset, Roboto
    returns the schema of each named topic in that dataset along with the ``body``.
    """

    resources: list[SkillResourceSummary] = pydantic.Field(default_factory=list)
    """Resources this version carries, each without its text.

    Only a skill that Roboto ships (:py:attr:`~roboto.domain.skills.SkillAccessibility.Roboto`) has any; for every
    other skill the list is empty.
    """

    created: datetime.datetime
    """Time the version was created."""

    modified: datetime.datetime
    """Time the version was last modified."""


class SkillSubscriptionRecord(pydantic.BaseModel):
    """Data record of a subscription to a skill, as :py:meth:`~roboto.domain.skills.Skill.subscribe` returns it.

    :py:meth:`~roboto.domain.skills.Skill.set_ai_version` also returns it. A subscription adds a skill to the user's
    personal skills and records which version, if any, Roboto's AI may apply for that user without being asked.
    Roboto subscribes a skill's author when the skill is created, with the first version pinned.
    """

    user_id: str
    """ID of the subscribed user, which for a person is their email address."""

    skill_id: str
    """ID of the skill the user subscribed to."""

    ai_version: Optional[int] = None
    """Version of the skill Roboto's AI may apply for this user without being asked.

    ``None`` means the AI applies the skill only when the user invokes it. Deleting the pinned version sets this to
    ``None``.
    """

    subscribed: datetime.datetime
    """Time the user subscribed to the skill."""


class SkillSummary(pydantic.BaseModel):
    """Summary of a skill for the caller, as :py:meth:`~roboto.domain.skills.Skill.get_summary` returns it.

    :py:meth:`~roboto.domain.skills.Skill.list_for_org` also yields it, one for each skill it lists. A summary holds
    the skill, its latest version, and the caller's subscription to it.
    """

    skill: SkillRecord
    """Record of the skill."""

    latest_version: Optional[SkillVersionRecord] = None
    """Record of the skill's version with the highest version number.

    Roboto always sets it: a skill is created with its first version, and deleting a skill's last version deletes the
    skill.
    """

    subscription: Optional[SkillSubscriptionRecord] = None
    """Record of the caller's subscription to the skill, or ``None`` if the caller is not subscribed to it.

    An author who unsubscribes from their own skill has no subscription.
    """
