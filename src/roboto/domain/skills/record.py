# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
from typing import Optional

import pydantic

from ...compat import StrEnum

# Maximum length of the per-version `description` field. The description appears
# inside the LoadSkillTool's tool description, which the model reads on every
# turn — keeping it tight matters.
MAX_SKILL_DESCRIPTION_LENGTH = 500


class SkillAccessibility(StrEnum):
    """Controls who can see a skill."""

    Private = "private"
    """Only the author (``created_by``) can see, edit, or invoke the skill."""

    Org = "org"
    """All members of the owning org can see and invoke the skill. Only the author can edit."""


class SkillRecord(pydantic.BaseModel):
    """Top-level skill identity, ownership, and visibility.

    A skill on its own carries no procedure content — see :class:`SkillVersionRecord`.
    """

    skill_id: str
    org_id: str
    accessibility: SkillAccessibility
    name: str
    tags: list[str] = pydantic.Field(default_factory=list)
    """Free-form labels for categorization (e.g. ``"qa-review"``, ``"experiments"``).
    Skill-level metadata, not version-scoped — they describe what the skill is for,
    not how a specific version implements it. Edited via the changeset fields on
    :class:`UpdateSkillMetadataRequest` (``put_tags`` / ``remove_tags``)."""

    created: datetime.datetime
    created_by: str
    modified: datetime.datetime
    """Last edit timestamp. Skill mutations are author-only, so the editor is always
    ``created_by`` — no separate ``modified_by`` field is stored."""


class SkillVersionRecord(pydantic.BaseModel):
    """A single, mutable version of a skill's content."""

    skill_id: str
    version: int
    description: str = pydantic.Field(max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    """Short ``when to use'' text. Surfaces verbatim in the LoadSkillTool description."""

    body: str
    """The procedure text the model executes when the skill is invoked."""

    created: datetime.datetime
    modified: datetime.datetime


class SkillSubscriptionRecord(pydantic.BaseModel):
    """Per-user state for a single skill.

    Created when a user subscribes to a skill (or authors one — authors are
    auto-subscribed at create time). Carries the user's choice of which version,
    if any, should be exposed to the AI auto-invoke registry. ``ai_version=None``
    means the user is subscribed but has not enabled the skill for AI auto-invoke;
    manual chip-invocation still works.
    """

    user_id: str
    skill_id: str
    ai_version: Optional[int] = None
    """If set, the AI's :class:`LoadSkillTool` registry surfaces this exact version of
    the skill to this user. If ``None``, the skill is hidden from AI auto-invocation
    for this user. Manual invocation works regardless."""

    subscribed: datetime.datetime
    """When the subscription was created."""


class SkillSummary(pydantic.BaseModel):
    """Compact projection of a skill plus its latest version (if any).

    Also includes the caller's personal subscription state for the skill, when
    one exists. ``subscription=None`` means the caller has neither authored nor
    subscribed to the skill.
    """

    skill: SkillRecord
    latest_version: Optional[SkillVersionRecord] = None
    """The MAX(version) row for this skill. Always populated for summaries
    returned from the public API: ``Skill.create()`` makes the skill row and
    v1 atomically, and deleting the last version cascades to delete the
    parent skill in the same transaction. The ``Optional`` is defense-in-
    depth for repo-direct callers (test fixtures, manual SQL) and should not
    be treated as a real branch by SDK consumers."""

    subscription: Optional[SkillSubscriptionRecord] = None
    """The caller's subscription row for this skill, if any. Populated by the
    server based on the caller's identity; not used in INSERT or UPDATE
    payloads."""
