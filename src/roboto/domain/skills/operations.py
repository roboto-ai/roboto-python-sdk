# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional, Union

import pydantic

from ...compat import StrEnum
from ...sentinels import NotSet, NotSetType
from .record import (
    MAX_SKILL_DESCRIPTION_LENGTH,
    SkillAccessibility,
)

# Skill names appear in URL paths (``v1/skills/name/<skill_name>``) and inside
# the chat composer's ``/slug`` token (where they must be parseable from free
# text — no whitespace allowed, since a space terminates the token). New skills
# must match :data:`SKILL_NAME_PATTERN`.
SKILL_NAME_PATTERN = r"^[A-Za-z0-9_-]+$"


class SkillListScope(StrEnum):
    """Which caller-relative slice of the visible skills a list-skills query targets."""

    Personal = "personal"
    """Skills the caller authored or has subscribed to — their personal set."""

    Org = "org"
    """Org-shared skills authored by someone else, regardless of whether the caller has subscribed."""


class CreateSkillRequest(pydantic.BaseModel):
    """Create a new skill plus its first version (``version=1``) in one call.

    The author is auto-subscribed at creation time with ``ai_version`` set to
    ``1`` so the skill is immediately offered to the author's AI.
    """

    name: str = pydantic.Field(max_length=120, pattern=SKILL_NAME_PATTERN)
    """Skill name. Unique within ``(org_id, accessibility)`` — a user's private skill
    and an org-shared skill may share a name without conflict. Must match
    :data:`SKILL_NAME_PATTERN` so the name is parseable inside the chat composer's
    ``/slug`` token (no whitespace, letters/digits/hyphens/underscores only)."""

    accessibility: SkillAccessibility = SkillAccessibility.Private
    """Visibility scope: ``Private`` (only the author) or ``Org`` (every org member).
    The author can flip this later via :class:`UpdateSkillMetadataRequest`."""

    description: str = pydantic.Field(max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    """"When to use" text for v1. Surfaces verbatim in the ``load_skill`` tool's
    description so the model can decide whether to invoke this skill. Bumping the
    version replaces this text on the new row; this field never re-edits v1's
    description after the fact."""

    body: str
    """Procedure text v1 — the instructions the model executes when this version
    is invoked. Bumping the version creates a new row; this field never re-edits
    v1's body after the fact (use :class:`UpdateSkillVersionRequest` for that)."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Initial set of tags. Edits after creation flow through ``UpdateSkillMetadataRequest.put_tags`` /
    ``.remove_tags`` so concurrent updates merge cleanly — see :class:`SkillRecord.tags`."""

    model_config = pydantic.ConfigDict(extra="ignore")


class UpdateSkillMetadataRequest(pydantic.BaseModel):
    """Update top-level skill identity. Author-only."""

    name: Union[str, NotSetType] = pydantic.Field(default=NotSet, max_length=120, pattern=SKILL_NAME_PATTERN)
    """New skill name. Omit (the ``NotSet`` default) to leave unchanged. Must match
    :data:`SKILL_NAME_PATTERN` and stays unique within ``(org_id, accessibility)``."""

    accessibility: Union[SkillAccessibility, NotSetType] = NotSet
    """New visibility scope. Omit to leave unchanged. Flipping ``Private`` → ``Org``
    immediately exposes the skill to every org member."""

    # Tag changes flow as additive lists (not a full ``tags=`` replacement) so
    # concurrent edits to disjoint tags merge without lost updates — same
    # convention as ``MetadataChangeset`` on datasets / files / collections.
    # Empty list (the default) means "no change to tags."
    put_tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to add. Empty (the default) means "no change to tags." Additive
    semantics — does not clear other tags."""

    remove_tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to remove. Empty (the default) means "no change to tags." Removing
    a tag the skill doesn't have is a no-op."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


class CreateSkillVersionRequest(pydantic.BaseModel):
    """Add a new version to an existing skill. The new version is assigned ``MAX(version) + 1``."""

    description: str = pydantic.Field(max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    """"When to use" text for this version. Surfaces verbatim in the ``load_skill``
    tool's description on every turn this version is offered to the AI."""

    body: str
    """Procedure text the model executes when this version is invoked."""

    model_config = pydantic.ConfigDict(extra="ignore")


class UpdateSkillVersionRequest(pydantic.BaseModel):
    """Edit fields on an existing version (mutates in place)."""

    description: Union[str, NotSetType] = pydantic.Field(default=NotSet, max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    """New "when to use" text. Omit (the ``NotSet`` default) to leave unchanged."""

    body: Union[str, NotSetType] = NotSet
    """New procedure text. Omit (the ``NotSet`` default) to leave unchanged. The
    change applies in place to this version — subscribers pinned to it will see
    the new body on their next AI invocation; there is no per-edit revision."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


class SetSkillSubscriptionRequest(pydantic.BaseModel):
    """Upsert the caller's subscription for a skill.

    Idempotent: creates the subscription row if missing, otherwise updates
    ``ai_version`` in place. Visibility-gated only — the caller does not need to
    be the skill's author. The server enforces that ``ai_version``, if provided,
    references an existing version of the skill.
    """

    ai_version: Optional[int] = None
    """Pinned AI-available version. ``None`` means "subscribed, but not exposed to AI"."""

    model_config = pydantic.ConfigDict(extra="ignore")
