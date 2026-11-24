# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Annotated, Any, Optional, Union

import pydantic

from ...compat import StrEnum
from ...sentinels import NotSet, NotSetType
from .record import (
    MAX_SKILL_DESCRIPTION_LENGTH,
    SkillAccessibility,
)

SKILL_NAME_PATTERN = r"^[A-Za-z0-9_-]+$"
"""Regular expression a skill name must match: letters, digits, hyphens and underscores only.

Roboto checks names against it when a skill is created or renamed. A user invokes a skill in a chat message by
typing ``/`` and its name, and the name ends at the first space, so it cannot contain whitespace.
"""


class SkillListScope(StrEnum):
    """Scope of :py:meth:`~roboto.domain.skills.Skill.list_for_org`: which of the skills the caller can see it lists.

    A skill shared with the organization that the caller subscribed to but did not author is in both subsets.
    """

    Personal = "personal"
    """Skills the caller authored or has subscribed to."""

    Org = "org"
    """Skills shared with the organization that someone else authored, whether or not the caller subscribed."""

    Roboto = "roboto"
    """Skills that Roboto ships (:py:attr:`~roboto.domain.skills.SkillAccessibility.Roboto`), and no others."""


def _refuse_roboto_accessibility(accessibility: Any) -> Any:
    if accessibility == SkillAccessibility.Roboto:
        raise ValueError("Only Roboto ships skills with accessibility 'roboto'; choose private, org or org-editable.")
    return accessibility


class CreateSkillRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.skills.Skill.create`.

    Roboto creates the skill and its version 1 together, and subscribes the author with ``ai_version`` set to ``1``,
    so Roboto's AI can apply the skill for the author at once.

    Building it raises ``pydantic.ValidationError`` when:

    - ``name`` is longer than 120 characters.
    - ``name`` does not match ``SKILL_NAME_PATTERN``.
    - ``description`` is longer than 500 characters.
    - ``accessibility`` is :py:attr:`~roboto.domain.skills.SkillAccessibility.Roboto`.
    """

    name: str = pydantic.Field(max_length=120, pattern=SKILL_NAME_PATTERN)
    """Name of the skill, at most 120 characters, matching ``SKILL_NAME_PATTERN``.

    The names of skills shared with the organization (:py:attr:`~roboto.domain.skills.SkillAccessibility.Org` and
    :py:attr:`~roboto.domain.skills.SkillAccessibility.OrgEditable`) are unique within the organization. A private
    skill's name is unique among its author's private skills in the organization, so it can match the name of a shared
    skill. A name already taken raises ``RobotoConflictException``.
    """

    accessibility: Annotated[SkillAccessibility, pydantic.AfterValidator(_refuse_roboto_accessibility)] = (
        SkillAccessibility.Private
    )
    """Who can see and edit the skill.

    The author can change it later with :py:meth:`~roboto.domain.skills.Skill.update_metadata`.
    :py:attr:`~roboto.domain.skills.SkillAccessibility.Roboto` is refused: only Roboto ships skills with it.
    """

    description: str = pydantic.Field(max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    """Text telling Roboto's AI when to apply version 1.

    At most 500 characters (:py:const:`~roboto.domain.skills.MAX_SKILL_DESCRIPTION_LENGTH`). Roboto shows it to the AI
    in the conversations of every subscriber who has made this version available to it.
    """

    body: str
    """Instructions Roboto's AI follows when it applies version 1."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to set on the skill. Defaults to none.

    Change them later with ``put_tags`` and ``remove_tags`` on ``UpdateSkillMetadataRequest``.
    """

    relevant_topics: list[str] = pydantic.Field(default_factory=list)
    """Names of the topics version 1's instructions examine, such as ``"/imu/data"``. Defaults to none.

    Roboto stores the list as given and does not read topic names from ``body``; the Roboto web app fills the list in
    from the topic references in the body. See :py:attr:`~roboto.domain.skills.SkillVersionRecord.relevant_topics`
    for how Roboto's AI uses it.
    """

    model_config = pydantic.ConfigDict(extra="ignore")


class UpdateSkillMetadataRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.skills.Skill.update_metadata`.

    A field left unset (``NotSet``) leaves that property of the skill unchanged. The author can change every field. On
    an :py:attr:`~roboto.domain.skills.SkillAccessibility.OrgEditable` skill, any subscribed member of the organization
    can change the name and tags, but only the author can change ``accessibility``.

    Building the request raises ``pydantic.ValidationError`` when ``name`` is longer than 120 characters or does not
    match ``SKILL_NAME_PATTERN``.
    """

    name: Union[str, NotSetType] = pydantic.Field(default=NotSet, max_length=120, pattern=SKILL_NAME_PATTERN)
    """New name of the skill, at most 120 characters, matching ``SKILL_NAME_PATTERN``.

    Unique under the same rules as ``CreateSkillRequest.name``. A name already taken raises ``RobotoConflictException``.
    """

    accessibility: Annotated[
        Union[SkillAccessibility, NotSetType], pydantic.AfterValidator(_refuse_roboto_accessibility)
    ] = NotSet
    """New setting for who can see and edit the skill.

    Sharing a private skill shows it to every member of the organization at once, and fails with
    ``RobotoConflictException`` when a shared skill already has its name. Making a shared skill private deletes every
    subscription to it except the author's. :py:attr:`~roboto.domain.skills.SkillAccessibility.Roboto` is refused:
    only Roboto ships skills with it.
    """

    put_tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to add to the skill, keeping its other tags. Defaults to none.

    Roboto applies ``put_tags`` and ``remove_tags`` to the tags stored when the request arrives, so two requests that
    change different tags at the same time both take effect.
    """

    remove_tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to remove from the skill. Defaults to none.

    A tag the skill does not have is ignored, and a tag in both ``put_tags`` and ``remove_tags`` is removed.
    """

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


class CreateSkillVersionRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.skills.Skill.create_version`.

    Roboto numbers the new version one higher than the skill's highest version. Subscribers keep the version they have
    pinned.

    Building the request raises ``pydantic.ValidationError`` when ``description`` is longer than 500 characters.
    """

    description: str = pydantic.Field(max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    """Text telling Roboto's AI when to apply this version.

    At most 500 characters (:py:const:`~roboto.domain.skills.MAX_SKILL_DESCRIPTION_LENGTH`). Roboto shows it to the AI
    in the conversations of every subscriber who has made this version available to it.
    """

    body: str
    """Instructions Roboto's AI follows when it applies this version."""

    relevant_topics: list[str] = pydantic.Field(default_factory=list)
    """Names of the topics this version's instructions examine, such as ``"/imu/data"``. Defaults to none.

    See :py:attr:`~roboto.domain.skills.SkillVersionRecord.relevant_topics` for how Roboto's AI uses them.
    """

    model_config = pydantic.ConfigDict(extra="ignore")


class UpdateSkillVersionRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.skills.Skill.update_version`.

    A field left unset (``NotSet``) is unchanged. Roboto changes the version in place and keeps no copy of the earlier
    values, so subscribers pinned to the version get the new content the next time Roboto's AI applies it for them. To
    leave them on the current content, add a version with :py:meth:`~roboto.domain.skills.Skill.create_version`
    instead.

    Building the request raises ``pydantic.ValidationError`` when ``description`` is longer than 500 characters.
    """

    description: Union[str, NotSetType] = pydantic.Field(default=NotSet, max_length=MAX_SKILL_DESCRIPTION_LENGTH)
    """New text telling Roboto's AI when to apply this version.

    At most 500 characters (:py:const:`~roboto.domain.skills.MAX_SKILL_DESCRIPTION_LENGTH`).
    """

    body: Union[str, NotSetType] = NotSet
    """New instructions Roboto's AI follows when it applies this version."""

    relevant_topics: Union[list[str], NotSetType] = NotSet
    """New names of the topics this version's instructions examine. An empty list clears them."""

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)


class SetSkillSubscriptionRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.skills.Skill.set_ai_version`.

    Roboto subscribes the caller to the skill if they are not subscribed, and otherwise changes only the
    subscription's ``ai_version``. Any caller who can see the skill can send it.
    """

    ai_version: Optional[int] = None
    """Version of the skill Roboto's AI may apply for the caller on its own.

    ``None`` keeps the subscription but stops the AI from applying the skill on its own; the caller can still invoke it
    in a chat message. A version the skill does not have raises ``RobotoNotFoundException``.
    """

    model_config = pydantic.ConfigDict(extra="ignore")
