# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Skills: stored, versioned procedures, written in Markdown, that Roboto's AI can apply during a conversation.

Use :py:class:`~roboto.domain.skills.Skill` to create and find skills, add versions to them, and choose the version
the AI may apply for the caller without being asked.

Roboto also ships skills of its own (:py:attr:`~roboto.domain.skills.SkillAccessibility.Roboto`), which members of an
organization can read and nobody can edit, delete or subscribe to.
"""

from .operations import (
    SKILL_NAME_PATTERN,
    CreateSkillRequest,
    CreateSkillVersionRequest,
    SetSkillSubscriptionRequest,
    SkillListScope,
    UpdateSkillMetadataRequest,
    UpdateSkillVersionRequest,
)
from .record import (
    MAX_SKILL_DESCRIPTION_LENGTH,
    SkillAccessibility,
    SkillRecord,
    SkillResourceSummary,
    SkillSubscriptionRecord,
    SkillSummary,
    SkillVersionRecord,
)
from .skill import Skill

__all__ = [
    "MAX_SKILL_DESCRIPTION_LENGTH",
    "SKILL_NAME_PATTERN",
    "CreateSkillRequest",
    "CreateSkillVersionRequest",
    "SetSkillSubscriptionRequest",
    "Skill",
    "SkillAccessibility",
    "SkillListScope",
    "SkillRecord",
    "SkillResourceSummary",
    "SkillSubscriptionRecord",
    "SkillSummary",
    "SkillVersionRecord",
    "UpdateSkillMetadataRequest",
    "UpdateSkillVersionRequest",
]
