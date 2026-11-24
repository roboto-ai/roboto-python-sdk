# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional

import pydantic


def _strip_check(value: str, *, field_name: str) -> str:
    """Reject a string that holds only whitespace, which ``min_length=1`` lets through."""
    if not value.strip():
        raise ValueError(f"{field_name} must contain non-whitespace characters.")
    return value


class SummaryAchieveInput(pydantic.BaseModel):
    """Input Roboto's AI submits to achieve a summary goal, on a dataset or a session.

    Building it raises ``pydantic.ValidationError`` when ``summary`` is empty or holds only whitespace.
    """

    summary: str = pydantic.Field(min_length=1)
    """Text of the summary, which Roboto stores on the goal's dataset or session."""

    @pydantic.field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, value: str) -> str:
        return _strip_check(value, field_name="summary")


class DatasetSummaryAchieveInput(SummaryAchieveInput):
    """Input Roboto's AI submits to achieve a :py:attr:`~roboto.ai.goals.GoalType.DATASET_SUMMARY` goal.

    Roboto checks the AI's input against it, and :py:class:`~roboto.ai.goals.DatasetSummaryGoalResult` holds that
    input for you to read.
    """


class SessionSummaryAchieveInput(SummaryAchieveInput):
    """Input Roboto's AI submits to achieve a :py:attr:`~roboto.ai.goals.GoalType.SESSION_SUMMARY` goal.

    Roboto checks the AI's input against it, and :py:class:`~roboto.ai.goals.SessionSummaryGoalResult` holds that
    input for you to read.
    """


class LabelDecision(pydantic.BaseModel):
    """Decision of Roboto's AI on whether one label of a triage goal's vocabulary applies.

    Carried in ``TriageAchieveInput.label_decisions``. Building it raises ``pydantic.ValidationError`` when:

    - ``applies`` is not a boolean (a string or number is rejected, not converted).
    - ``justification`` is empty or holds only whitespace.
    - ``confidence`` is outside 0.0 to 1.0.
    """

    label: str
    """Label the decision is about: a key of the goal's ``label_vocabulary``.

    Roboto checks the label against that vocabulary when the AI submits it.
    """

    applies: pydantic.StrictBool
    """Whether the label applies to the goal's dataset or session.

    Roboto adds each label that applies to that dataset's or session's tags. A label that does not apply is kept only
    in this decision.
    """

    justification: str = pydantic.Field(min_length=1)
    """Reasoning for the decision, citing what the AI observed in the dataset or session.

    Required whether or not the label applies.
    """

    confidence: float = pydantic.Field(ge=0.0, le=1.0)
    """Confidence of the AI in the decision, from 0.0 (none) to 1.0 (certain).

    Roboto does not use it to decide whether to add the label.
    """

    @pydantic.field_validator("justification")
    @classmethod
    def _justification_not_blank(cls, value: str) -> str:
        return _strip_check(value, field_name="justification")


class TriageAchieveInput(pydantic.BaseModel):
    """Input Roboto's AI submits to achieve a triage goal, on a dataset or a session.

    Building it raises ``pydantic.ValidationError`` when ``label_decisions`` is empty.
    """

    label_decisions: list[LabelDecision] = pydantic.Field(min_length=1)
    """One decision for each label in the goal's ``label_vocabulary``.

    Roboto checks that every label appears exactly once when the AI submits the decisions, and this model does not, so
    the result of a failed attempt can repeat or leave out a label.
    """


class DatasetTriageAchieveInput(TriageAchieveInput):
    """Input Roboto's AI submits to achieve a :py:attr:`~roboto.ai.goals.GoalType.DATASET_TRIAGE` goal.

    Roboto checks the AI's input against it, and :py:class:`~roboto.ai.goals.DatasetTriageGoalResult` holds that
    input for you to read.
    """


class SessionTriageAchieveInput(TriageAchieveInput):
    """Input Roboto's AI submits to achieve a :py:attr:`~roboto.ai.goals.GoalType.SESSION_TRIAGE` goal.

    Roboto checks the AI's input against it, and :py:class:`~roboto.ai.goals.SessionTriageGoalResult` holds that
    input for you to read.
    """


class EventSpecBase(pydantic.BaseModel):
    """Fields shared by the events Roboto's AI proposes for a goal that creates events, on a dataset or a session.

    Base of :py:class:`~roboto.ai.goals.EventSpec` and :py:class:`~roboto.ai.goals.SessionEventSpec`. Building it
    raises ``pydantic.ValidationError`` when ``start_time`` or ``end_time`` is not an integer (a boolean, string or
    float is rejected, not converted), or when ``end_time`` is before ``start_time``.
    """

    name: str
    """Name of the event: a key of the goal's ``event_vocabulary``, which Roboto checks when the AI submits it."""

    start_time: pydantic.StrictInt
    """Start of the event, in nanoseconds since the Unix epoch."""

    end_time: pydantic.StrictInt
    """End of the event, in nanoseconds since the Unix epoch. Equal to ``start_time`` for an instantaneous event."""

    description: Optional[str] = None
    """Human-readable description of the event. ``None`` gives the event no description."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to set on the event, each a key of the goal's ``tag_vocabulary``.

    Roboto checks the tags against that vocabulary when the AI submits them. Defaults to none.
    """

    @pydantic.model_validator(mode="after")
    def _end_after_start(self) -> "EventSpecBase":
        # mode="after" runs this only once StrictInt has accepted both times, so it never compares a non-integer.
        if self.end_time < self.start_time:
            raise ValueError(
                f"end_time ({self.end_time}) is before start_time ({self.start_time}); "
                "use end_time == start_time for an instantaneous event."
            )
        return self


class EventSpec(EventSpecBase):
    """Event Roboto's AI proposes to create for a :py:attr:`~roboto.ai.goals.GoalType.CREATE_EVENTS` goal.

    Carried in ``CreateEventsAchieveInput.events``.
    """

    target_id: Optional[str] = None
    """ID of the dataset, file, topic or message path the event is about.

    It names the goal's dataset (``ds_``), or a file (``fl_``), topic (``tp_``) or message path (``mp_``) in that
    dataset. Roboto rejects a submission that names anything else or leaves this ``None``. ``None`` on events the AI
    proposed before Roboto stored this field.
    """


class CreateEventsAchieveInput(pydantic.BaseModel):
    """Input Roboto's AI submits to achieve a :py:attr:`~roboto.ai.goals.GoalType.CREATE_EVENTS` goal.

    Roboto checks the AI's input against it, and :py:class:`~roboto.ai.goals.CreateEventsGoalResult` holds that
    input for you to read.
    """

    events: list[EventSpec]
    """Events to create on the goal's dataset.

    Empty when the AI found no span of time that matches the goal's event types.
    """


class SessionEventSpec(EventSpecBase):
    """Event Roboto's AI proposes to create for a :py:attr:`~roboto.ai.goals.GoalType.SESSION_CREATE_EVENTS` goal.

    Carried in ``SessionCreateEventsAchieveInput.events``. The event belongs to the goal's session, so no field names a
    session.
    """

    topic_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the session's topics that the event concerns.

    Defaults to none, meaning the event concerns the whole session. Roboto rejects a submission that names a topic
    twice, or a topic with no data in the session.
    """


class SessionCreateEventsAchieveInput(pydantic.BaseModel):
    """Input Roboto's AI submits to achieve a :py:attr:`~roboto.ai.goals.GoalType.SESSION_CREATE_EVENTS` goal.

    Roboto checks the AI's input against it, and :py:class:`~roboto.ai.goals.SessionCreateEventsGoalResult` holds
    that input for you to read.
    """

    events: list[SessionEventSpec]
    """Events to create on the goal's session.

    Empty when the AI found no span of time that matches the goal's event types.
    """
