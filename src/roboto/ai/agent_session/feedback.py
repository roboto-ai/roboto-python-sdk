# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
from typing import Optional, Union

import pydantic

from ...compat import StrEnum
from ...sentinels import NotSet, NotSetType


class FeedbackSentiment(StrEnum):
    """Overall rating direction for a piece of AI-chat feedback."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class FeedbackCategory(StrEnum):
    """Taxonomy of feedback categories.

    Which categories are valid depends on ``sentiment`` (see
    :func:`category_is_valid_for_sentiment`). ``OTHER`` is always permitted;
    when ``OTHER`` is among the selected categories, ``notes`` is required.
    """

    # Negative
    INCORRECT = "incorrect"
    INCOMPLETE = "incomplete"
    TOOL_FAILURE = "tool_failure"
    REFUSED_VALID_REQUEST = "refused_valid_request"
    FORMATTING = "formatting"
    SLOW = "slow"
    UNSAFE = "unsafe"

    # Positive
    CORRECT = "correct"
    HELPFUL = "helpful"
    GOOD_TOOL_USE = "good_tool_use"

    # Either
    OTHER = "other"


NEGATIVE_CATEGORIES: frozenset[FeedbackCategory] = frozenset(
    {
        FeedbackCategory.INCORRECT,
        FeedbackCategory.INCOMPLETE,
        FeedbackCategory.TOOL_FAILURE,
        FeedbackCategory.REFUSED_VALID_REQUEST,
        FeedbackCategory.FORMATTING,
        FeedbackCategory.SLOW,
        FeedbackCategory.UNSAFE,
    }
)

POSITIVE_CATEGORIES: frozenset[FeedbackCategory] = frozenset(
    {
        FeedbackCategory.CORRECT,
        FeedbackCategory.HELPFUL,
        FeedbackCategory.GOOD_TOOL_USE,
    }
)


def category_is_valid_for_sentiment(category: FeedbackCategory, sentiment: FeedbackSentiment) -> bool:
    """Report whether ``category`` is a permitted choice under ``sentiment``.

    ``FeedbackCategory.OTHER`` is always permitted.
    """
    if category is FeedbackCategory.OTHER:
        return True
    if sentiment is FeedbackSentiment.POSITIVE:
        return category in POSITIVE_CATEGORIES
    return category in NEGATIVE_CATEGORIES


class SubmitFeedbackRequest(pydantic.BaseModel):
    """Request body for submitting feedback on an assistant message.

    One row per (session, message, user); resubmitting replaces the previous
    sentiment/categories/notes rather than adding a new row.
    """

    sentiment: FeedbackSentiment
    """Overall rating direction."""

    categories: list[FeedbackCategory] = pydantic.Field(default_factory=list)
    """Categories describing what was good or bad. Semantically a *set*: duplicates
    are dropped and the persisted order is enum-value sort, not request order."""

    notes: Optional[str] = None
    """Free-text notes. Whitespace-only input is normalised to ``None`` before
    persistence. Required when ``FeedbackCategory.OTHER`` is selected."""

    @pydantic.model_validator(mode="after")
    def _validate(self) -> "SubmitFeedbackRequest":
        for category in self.categories:
            if not category_is_valid_for_sentiment(category, self.sentiment):
                raise ValueError(f"category {category.value} is not valid for sentiment {self.sentiment.value}")
        # Categories are semantically a set. Sort by enum value so the stored
        # list is deterministic (easier equality checks and reproducible tests).
        # The docstring above documents this rewrite — silent dedup behind a
        # plain-list type is a footgun if the schema doesn't say so.
        self.categories = sorted(set(self.categories))
        # Normalise whitespace-only notes to ``None`` so the persisted column
        # is consistent regardless of category. Without this, ``notes="   "``
        # would store three spaces alongside a HELPFUL rating but would fail
        # validation alongside an OTHER rating — the asymmetry confuses callers.
        if self.notes is not None and not self.notes.strip():
            self.notes = None
        if FeedbackCategory.OTHER in self.categories and self.notes is None:
            raise ValueError("notes are required when 'other' is among the categories")
        return self


class AdminUpdateFeedbackRequest(pydantic.BaseModel):
    """Triage fields editable by Roboto admins.

    Fields omitted from the request (``NotSet``) are left unchanged. Fields
    explicitly set to ``None`` clear the column back to ``NULL``. Fields set
    to a value overwrite the column.

    Setting ``resolved`` to ``True`` additionally stamps ``resolved_at`` and
    ``resolved_by`` server-side; setting it back to ``False`` clears them.
    """

    admin_label: Union[Optional[str], NotSetType] = NotSet
    admin_note: Union[Optional[str], NotSetType] = NotSet
    resolved: Union[bool, NotSetType] = NotSet

    model_config = pydantic.ConfigDict(
        # ``extra="forbid"`` rather than ``ignore`` so a misspelled field
        # (``admin_lable`` for ``admin_label``) raises a clear validation
        # error instead of being silently dropped. The NotSet/None semantics
        # documented above only mean what they say if every field the caller
        # tried to set actually reaches the model.
        extra="forbid",
        json_schema_extra=NotSetType.openapi_schema_modifier,
    )


class AgentFeedbackRecord(pydantic.BaseModel):
    """Persisted feedback record for a specific assistant message."""

    feedback_id: str
    """Unique identifier for this feedback entry."""

    session_id: str
    """Session the feedback was submitted against."""

    message_sequence_num: int
    """Zero-indexed position of the assistant message within the session."""

    org_id: str
    """Org the session belonged to at the time of submission."""

    created: datetime.datetime
    """When this feedback was first submitted."""

    created_by: str
    """User id of the submitter."""

    modified: datetime.datetime
    """When the submitter last updated this feedback. Equals ``created`` for untouched rows.

    Admin triage does not bump this column — it tracks the submitter's own edits only.
    """

    modified_by: str
    """User id of the submitter's last edit. Admin triage does not change this field.

    In practice this always equals ``created_by`` (the same user may only edit their
    own feedback), but it exists as a distinct column for forward compatibility.
    """

    sentiment: FeedbackSentiment
    """Overall rating direction."""

    categories: list[FeedbackCategory] = pydantic.Field(default_factory=list)
    """Categories describing the feedback. May be empty."""

    notes: Optional[str] = None
    """Free-text notes from the submitter, if any."""

    admin_label: Optional[str] = None
    """Short label an admin can attach for triage (e.g. 'follow up', 'duplicate')."""

    admin_note: Optional[str] = None
    """Longer admin-only note captured during triage."""

    resolved: bool = False
    """Whether an admin has marked this feedback as resolved."""

    resolved_by: Optional[str] = None
    """Admin who marked this feedback resolved."""

    resolved_at: Optional[datetime.datetime] = None
    """When the feedback was marked resolved."""


class UserFeedbackRecord(pydantic.BaseModel):
    """Customer-facing projection of :class:`AgentFeedbackRecord`.

    Excludes every admin-only column (``admin_label``, ``admin_note``,
    ``resolved``, ``resolved_by``, ``resolved_at``) so routes that serve
    an end user never return internal triage state. Use this as the return
    type of any non-admin endpoint that surfaces feedback, including the
    response to the submitter's own submit call.

    The admin endpoints continue to return :class:`AgentFeedbackRecord`
    directly.
    """

    feedback_id: str
    """Unique identifier for this feedback entry."""

    session_id: str
    """Session the feedback was submitted against."""

    message_sequence_num: int
    """Zero-indexed position of the assistant message within the session."""

    org_id: str
    """Org the session belonged to at the time of submission."""

    created: datetime.datetime
    """When this feedback was first submitted."""

    created_by: str
    """User id of the submitter."""

    modified: datetime.datetime
    """When the submitter last updated this feedback."""

    modified_by: str
    """User id of the submitter's last edit."""

    sentiment: FeedbackSentiment
    """Overall rating direction."""

    categories: list[FeedbackCategory] = pydantic.Field(default_factory=list)
    """Categories describing the feedback. May be empty."""

    notes: Optional[str] = None
    """Free-text notes from the submitter, if any."""

    @classmethod
    def from_admin_record(cls, record: AgentFeedbackRecord) -> "UserFeedbackRecord":
        """Project an :class:`AgentFeedbackRecord` down to the user-facing shape.

        Use at the boundary of any non-admin route that materialises a full
        admin record from persistence — the projection guarantees no admin
        triage column accidentally escapes to a customer response.

        The projection is driven by ``cls.model_fields`` rather than a hand
        list of columns: a new submitter-controlled column added to both
        records flows through automatically, and a new admin-only column on
        ``AgentFeedbackRecord`` is silently dropped here (which is what we
        want for privacy). The matching test asserts the admin-only field
        set has not drifted unexpectedly.
        """
        return cls.model_validate(record.model_dump(include=set(cls.model_fields)))


# ``AgentFeedbackRecord`` is intentionally not exported. It carries the admin
# triage columns (``admin_label``, ``admin_note``, ``resolved``, etc.) and is
# only constructed inside the service for admin endpoints. Public SDK users
# should reach for ``UserFeedbackRecord`` instead. The class remains
# importable for internal modules but is hidden from ``import *`` and from
# autocomplete tools that respect ``__all__``.
__all__ = [
    "AdminUpdateFeedbackRequest",
    "FeedbackCategory",
    "FeedbackSentiment",
    "NEGATIVE_CATEGORIES",
    "POSITIVE_CATEGORIES",
    "SubmitFeedbackRequest",
    "UserFeedbackRecord",
    "category_is_valid_for_sentiment",
]
