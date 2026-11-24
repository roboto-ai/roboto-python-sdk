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
    """Sentiment of feedback on a message from Roboto's AI: whether the rating is positive or negative."""

    POSITIVE = "positive"
    NEGATIVE = "negative"


class FeedbackCategory(StrEnum):
    """Category of feedback on a message from Roboto's AI: what about the message was good or bad.

    Which categories feedback may carry depends on its sentiment; ``category_is_valid_for_sentiment`` checks one.
    ``OTHER`` is valid with either sentiment, and feedback that includes it needs notes.
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
"""Categories valid only on feedback with negative sentiment. ``FeedbackCategory.OTHER`` is in neither set."""

POSITIVE_CATEGORIES: frozenset[FeedbackCategory] = frozenset(
    {
        FeedbackCategory.CORRECT,
        FeedbackCategory.HELPFUL,
        FeedbackCategory.GOOD_TOOL_USE,
    }
)
"""Categories valid only on feedback with positive sentiment. ``FeedbackCategory.OTHER`` is in neither set."""


def category_is_valid_for_sentiment(category: FeedbackCategory, sentiment: FeedbackSentiment) -> bool:
    """Return whether feedback with ``sentiment`` may carry ``category``.

    ``FeedbackCategory.OTHER`` is valid with either sentiment. Every other category is valid with one, as
    ``NEGATIVE_CATEGORIES`` and ``POSITIVE_CATEGORIES`` list.

    Args:
        category: Category to check.
        sentiment: Sentiment of the feedback.
    """
    if category is FeedbackCategory.OTHER:
        return True
    if sentiment is FeedbackSentiment.POSITIVE:
        return category in POSITIVE_CATEGORIES
    return category in NEGATIVE_CATEGORIES


class SubmitFeedbackRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.ai.agent_thread.AgentThread.submit_feedback`.

    A user has at most one feedback on each message, so submitting again replaces that user's ``sentiment``,
    ``categories`` and ``notes``. Building the model raises ``pydantic.ValidationError`` when a category is not valid
    for ``sentiment``, or when ``categories`` includes ``FeedbackCategory.OTHER`` and ``notes`` is ``None``, empty, or
    only whitespace.
    """

    sentiment: FeedbackSentiment
    """Sentiment of the feedback."""

    categories: list[FeedbackCategory] = pydantic.Field(default_factory=list)
    """Categories describing what was good or bad about the message. Defaults to none.

    Building the model drops duplicates and sorts the rest by value, so the order given is not kept.
    """

    notes: Optional[str] = None
    """Free-text notes on the message. Required when ``categories`` includes ``FeedbackCategory.OTHER``.

    Building the model turns notes that are empty or only whitespace into ``None``.
    """

    @pydantic.model_validator(mode="after")
    def _validate(self) -> "SubmitFeedbackRequest":
        for category in self.categories:
            if not category_is_valid_for_sentiment(category, self.sentiment):
                raise ValueError(f"category {category.value} is not valid for sentiment {self.sentiment.value}")
        # Sorted so that one set of categories is always stored as the same list.
        self.categories = sorted(set(self.categories))
        # Clear whitespace-only notes whatever the categories, so "   " is never stored with HELPFUL while
        # being rejected with OTHER.
        if self.notes is not None and not self.notes.strip():
            self.notes = None
        if FeedbackCategory.OTHER in self.categories and self.notes is None:
            raise ValueError("notes are required when 'other' is among the categories")
        return self


class AdminUpdateFeedbackRequest(pydantic.BaseModel):
    """Request body for ``PUT /v1/admin/feedback/{feedback_id}``.

    Only Roboto administrators may send it. No SDK method sends it.

    A field left unset (``NotSet``) is unchanged. A request that sets no field raises
    ``RobotoInvalidRequestException``. Building the model raises ``pydantic.ValidationError`` for a field it does not
    define, such as a misspelled field name.
    """

    admin_label: Union[Optional[str], NotSetType] = NotSet
    """Short label to sort the feedback by, such as ``"follow up"`` or ``"duplicate"``.

    Stored with surrounding whitespace removed and its case kept, since labels are case-sensitive. ``None`` or a blank
    label clears it.
    """

    admin_note: Union[Optional[str], NotSetType] = NotSet
    """Note on the feedback for Roboto administrators. ``None`` clears it."""

    resolved: Union[bool, NotSetType] = NotSet
    """Whether the feedback is resolved.

    ``True`` records the time and the administrator in ``AgentFeedbackRecord.resolved_at`` and
    ``AgentFeedbackRecord.resolved_by``; ``False`` clears both.
    """

    model_config = pydantic.ConfigDict(
        # A misspelled field (admin_lable) fails instead of being dropped, which would leave admin_label unchanged.
        extra="forbid",
        json_schema_extra=NotSetType.openapi_schema_modifier,
    )

    @pydantic.field_validator("admin_label")
    @classmethod
    def _normalize_admin_label(cls, value: Union[Optional[str], NotSetType]) -> Union[Optional[str], NotSetType]:
        # Labels are filtered and counted by exact value, so "dup" and "dup " would otherwise be two labels.
        if isinstance(value, str):
            return value.strip() or None
        return value


class AgentFeedbackRecord(pydantic.BaseModel):
    """Data record of feedback on a message in a thread, as ``GET /v1/admin/feedback/{feedback_id}`` returns it.

    Feedback is one user's rating of a message from Roboto's AI: a sentiment, categories, and optional notes. This
    record also holds the fields Roboto administrators use to triage feedback, and only routes for Roboto
    administrators return it; :py:meth:`~roboto.ai.agent_thread.AgentThread.submit_feedback` returns
    ``UserFeedbackRecord``, which leaves those fields out.
    """

    feedback_id: str
    """Unique ID of the feedback, beginning with ``fb_``."""

    thread_id: str
    """ID of the thread the rated message is in."""

    message_sequence_num: int
    """Sequence number of the rated message: its zero-based position in the thread's messages."""

    org_id: str
    """ID of the organization that owns the thread. Fixed when the feedback is first submitted."""

    created: datetime.datetime
    """Time the feedback was first submitted."""

    created_by: str
    """ID of the user who submitted the feedback."""

    modified: datetime.datetime
    """Time the feedback was last submitted, equal to ``created`` until its submitter submits it again.

    Triage by a Roboto administrator does not change it.
    """

    modified_by: str
    """ID of the user who last submitted the feedback.

    Always equal to ``created_by``, because submitting again replaces only the submitting user's own feedback.
    """

    sentiment: FeedbackSentiment
    """Sentiment of the feedback."""

    categories: list[FeedbackCategory] = pydantic.Field(default_factory=list)
    """Categories describing what was good or bad about the message, sorted by value. Empty when none were chosen."""

    notes: Optional[str] = None
    """Free-text notes on the message, or ``None`` if the submitter gave none."""

    admin_label: Optional[str] = None
    """Short label a Roboto administrator attached to sort the feedback by, such as ``"follow up"``, or ``None``."""

    admin_note: Optional[str] = None
    """Note on the feedback for Roboto administrators, or ``None``."""

    resolved: bool = False
    """Whether a Roboto administrator has marked the feedback resolved."""

    resolved_by: Optional[str] = None
    """ID of the Roboto administrator who marked the feedback resolved, or ``None`` while it is unresolved."""

    resolved_at: Optional[datetime.datetime] = None
    """Time the feedback was marked resolved, or ``None`` while it is unresolved."""


class UserFeedbackRecord(pydantic.BaseModel):
    """Data record of feedback on a message in a thread, as Roboto returns it to the user who submitted it.

    :py:meth:`~roboto.ai.agent_thread.AgentThread.submit_feedback` returns it. Feedback is one user's rating of a
    message from Roboto's AI: a sentiment, categories, and optional notes. The record leaves out the fields Roboto
    administrators use to triage feedback.
    """

    feedback_id: str
    """Unique ID of the feedback, beginning with ``fb_``."""

    thread_id: str
    """ID of the thread the rated message is in."""

    message_sequence_num: int
    """Sequence number of the rated message: its zero-based position in the thread's messages."""

    org_id: str
    """ID of the organization that owns the thread. Fixed when the feedback is first submitted."""

    created: datetime.datetime
    """Time the feedback was first submitted."""

    created_by: str
    """ID of the user who submitted the feedback."""

    modified: datetime.datetime
    """Time the feedback was last submitted, equal to ``created`` until its submitter submits it again."""

    modified_by: str
    """ID of the user who last submitted the feedback.

    Always equal to ``created_by``, because submitting again replaces only the submitting user's own feedback.
    """

    sentiment: FeedbackSentiment
    """Sentiment of the feedback."""

    categories: list[FeedbackCategory] = pydantic.Field(default_factory=list)
    """Categories describing what was good or bad about the message, sorted by value. Empty when none were chosen."""

    notes: Optional[str] = None
    """Free-text notes on the message, or ``None`` if the submitter gave none."""

    @classmethod
    def from_admin_record(cls, record: AgentFeedbackRecord) -> "UserFeedbackRecord":
        """Build a record from ``AgentFeedbackRecord``, leaving out the fields for Roboto administrators.

        Roboto calls this when it returns feedback to anyone but a Roboto administrator. It copies only the fields
        this class defines, so a field added to ``AgentFeedbackRecord`` alone never reaches the result.

        Args:
            record: Record to copy the fields from.
        """
        return cls.model_validate(record.model_dump(include=set(cls.model_fields)))


# AgentFeedbackRecord stays importable but is left out: it holds the triage fields only Roboto administrators see,
# and customers receive UserFeedbackRecord instead.
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
