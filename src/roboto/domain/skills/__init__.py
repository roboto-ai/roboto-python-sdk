# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Stored, versioned procedures the chat AI can apply during a conversation.

A skill is text instructions the model follows when invoked — either manually
via a chat-composer chip or automatically when the model selects it from the
``load_skill`` tool's registry. Skills are owned by a user, optionally shared
with the user's organization, and versioned in place; each version is mutable
without lifecycle states. Visibility and edit rights follow the skill's
accessibility: ``private`` (author-only), ``org`` (visible org-wide, author-only
to edit), or ``org-editable`` (visible org-wide and editable by any subscribed
member). Per-user subscriptions carry an ``ai_version`` pin that controls
whether — and which version — the AI auto-invoke registry exposes to the
subscriber.
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
    "SkillSubscriptionRecord",
    "SkillSummary",
    "SkillVersionRecord",
    "UpdateSkillMetadataRequest",
    "UpdateSkillVersionRequest",
]
