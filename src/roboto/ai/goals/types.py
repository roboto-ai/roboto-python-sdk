# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Annotated, Any, Literal, Optional, Union

import pydantic

from ...compat import StrEnum


class GoalType(StrEnum):
    """Kind of goal: what Roboto's AI must produce.

    Each member is the ``goal_type`` of one class in ``AgentGoal``.
    """

    DATASET_SUMMARY = "dataset_summary"
    """Summary of a dataset (``DatasetSummaryAgentGoal``).

    Roboto stores it where :py:meth:`~roboto.domain.datasets.Dataset.get_summary` returns it.
    """

    DATASET_TRIAGE = "dataset_triage"
    """Tags on a dataset, chosen from labels the caller supplies (``DatasetTriageGoal``)."""

    CREATE_EVENTS = "create_events"
    """Events on a dataset, of kinds the caller supplies (``CreateEventsGoal``)."""

    SESSION_SUMMARY = "session_summary"
    """Summary of a session (``SessionSummaryAgentGoal``).

    Roboto stores it where :py:meth:`~roboto.experimental.sessions.Session.get_summary` returns it.
    """

    SESSION_TRIAGE = "session_triage"
    """Tags on a session, chosen from labels the caller supplies (``SessionTriageGoal``)."""

    SESSION_CREATE_EVENTS = "session_create_events"
    """Session events, of kinds the caller supplies (``SessionCreateEventsGoal``)."""


class AgentGoalStatus(StrEnum):
    """Status of a goal: whether Roboto's AI has achieved it.

    A goal starts ``PENDING`` when it is declared and ends ``ACHIEVED`` or ``FAILED`` with its turn.
    """

    PENDING = "pending"
    """Declared, and not yet achieved or failed."""

    ACHIEVED = "achieved"
    """The AI made the change the goal asks for."""

    FAILED = "failed"
    """The turn ended without the AI achieving the goal.

    Either the AI used up its retries for the turn, or Roboto could not process this kind of goal.
    """


class AgentGoalBase(pydantic.BaseModel):
    """Base class of the goals in ``AgentGoal``.

    Roboto subclasses it to add a kind of goal; to declare a goal, build one of its subclasses. Defining a subclass
    without a ``goal_type`` field raises ``TypeError``. ``goal_type`` counts as set even when left at its default, so
    ``model_dump(exclude_unset=True)`` keeps it and Roboto can tell which kind of goal a request declares.
    """

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        super().__pydantic_init_subclass__(**kwargs)
        if "goal_type" not in cls.model_fields:
            raise TypeError(
                f"{cls.__name__} must declare a `goal_type: Literal[GoalType.X] = GoalType.X` field. "
                "Without it the discriminated-union dispatch on the server side cannot route the goal "
                "to its handler, and ``model_dump_json(exclude_unset=True)`` would silently drop the "
                "discriminator on the wire."
            )

    @pydantic.model_validator(mode="after")
    def _force_discriminator_into_fields_set(self) -> "AgentGoalBase":
        self.__pydantic_fields_set__.add("goal_type")
        return self


_MAX_SUMMARY_FORMAT_SPEC_CHARS = 4000
"""Maximum length of a summary goal's ``summary_format_spec_prompt``, in characters."""


class DatasetSummaryAgentGoal(AgentGoalBase):
    """Goal that has Roboto's AI summarize a dataset.

    The AI stores the summary on the dataset ``dataset_id`` and no other, where
    :py:meth:`~roboto.domain.datasets.Dataset.get_summary` returns it. Building the goal raises
    ``pydantic.ValidationError`` when ``summary_format_spec_prompt`` is empty or longer than 4000 characters.
    """

    goal_type: Literal[GoalType.DATASET_SUMMARY] = GoalType.DATASET_SUMMARY
    """Kind of goal, always ``GoalType.DATASET_SUMMARY``."""

    dataset_id: str
    """ID of the dataset to summarize."""

    summary_format_spec_prompt: Optional[str] = pydantic.Field(
        default=None, min_length=1, max_length=_MAX_SUMMARY_FORMAT_SPEC_CHARS
    )
    """Instructions for the AI on how to structure the summary, from 1 to 4000 characters.

    Roboto does not check the summary against them. ``None`` uses Roboto's default structure.
    """


_TRIAGE_LABEL_PATTERN = r"^[a-zA-Z0-9_\-]+$"
"""Regular expression a triage label must match: ASCII letters, digits, underscores and hyphens.

These characters work both as tags and as choices in the tool the AI calls to report its decisions.
"""

_MAX_TRIAGE_LABELS = 50
"""Maximum number of labels in a triage goal's ``label_vocabulary``."""

_MAX_TRIAGE_DESCRIPTION_CHARS = 500
"""Maximum length of a triage label's description, in characters."""


def _validate_triage_vocabulary(value: dict[str, str]) -> dict[str, str]:
    """Reject a label vocabulary that breaks the rules ``DatasetTriageGoal`` states."""
    import re

    label_re = re.compile(_TRIAGE_LABEL_PATTERN)
    for label, description in value.items():
        if not label_re.match(label):
            raise ValueError(
                f"label_vocabulary key {label!r} is not a valid label: must match {_TRIAGE_LABEL_PATTERN!r} "
                "(ASCII alphanumerics, underscore, hyphen). Labels are persisted as tags and reflected "
                "into the LLM-facing tool schema, so we keep them to a conservative character set."
            )
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"label_vocabulary value for {label!r} must be a non-empty string describing what the label "
                "signifies; this description is rendered into the prompt so the LLM can pick correctly."
            )
        if len(description) > _MAX_TRIAGE_DESCRIPTION_CHARS:
            raise ValueError(
                f"label_vocabulary value for {label!r} exceeds {_MAX_TRIAGE_DESCRIPTION_CHARS} characters "
                f"(got {len(description)}). Tighten the description or split into multiple labels."
            )
    return value


class DatasetTriageGoal(AgentGoalBase):
    """Goal that has Roboto's AI tag a dataset with the labels from a vocabulary that apply to it.

    The AI decides on every label in ``label_vocabulary``, giving whether it applies, a justification and a
    confidence. Roboto adds the labels that apply, if any, to the tags of the dataset ``dataset_id`` and no other. The
    decisions are in the goal's :py:class:`~roboto.ai.goals.DatasetTriageGoalResult`.

    Building the goal raises ``pydantic.ValidationError`` when:

    - ``label_vocabulary`` is empty or has more than 50 labels.
    - A label has a character other than an ASCII letter, digit, underscore or hyphen.
    - A label's description is blank or longer than 500 characters.
    """

    goal_type: Literal[GoalType.DATASET_TRIAGE] = GoalType.DATASET_TRIAGE
    """Kind of goal, always ``GoalType.DATASET_TRIAGE``."""

    dataset_id: str
    """ID of the dataset to tag."""

    label_vocabulary: dict[str, str] = pydantic.Field(min_length=1, max_length=_MAX_TRIAGE_LABELS)
    """Labels the AI chooses from, each mapped to a description of what it means.

    The AI reads each description to decide whether the label applies.
    """

    @pydantic.field_validator("label_vocabulary")
    @classmethod
    def _validate_vocabulary_entries(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_triage_vocabulary(value)


_MAX_EVENT_FOCUS_PROMPT_CHARS = 4000
"""Maximum length of an events goal's ``event_focus_prompt``, in characters."""

_MAX_EVENT_VOCABULARY = 50
"""Maximum number of entries in an events goal's ``event_vocabulary``."""

_MAX_TAG_VOCABULARY = 50
"""Maximum number of entries in an events goal's ``tag_vocabulary``."""

_MAX_VOCABULARY_KEY_CHARS = 100
"""Maximum length of a key in an events goal's ``event_vocabulary`` or ``tag_vocabulary``, in characters."""

_MAX_VOCABULARY_DESCRIPTION_CHARS = 500
"""Maximum length of a description in an events goal's ``event_vocabulary`` or ``tag_vocabulary``, in characters."""


def _validate_vocabulary(value: dict[str, str], *, field_name: str) -> dict[str, str]:
    """Reject an event or tag vocabulary that breaks the rules ``CreateEventsGoal`` states."""
    for key, description in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{field_name} keys must be non-empty strings; got {key!r}.")
        if len(key) > _MAX_VOCABULARY_KEY_CHARS:
            raise ValueError(
                f"{field_name} key {key!r} exceeds {_MAX_VOCABULARY_KEY_CHARS} characters (got {len(key)})."
            )
        if not isinstance(description, str) or not description.strip():
            raise ValueError(
                f"{field_name} value for {key!r} must be a non-empty string; the description is "
                "rendered into the prompt so the LLM can pick correctly."
            )
        if len(description) > _MAX_VOCABULARY_DESCRIPTION_CHARS:
            raise ValueError(
                f"{field_name} value for {key!r} exceeds {_MAX_VOCABULARY_DESCRIPTION_CHARS} characters "
                f"(got {len(description)})."
            )
    return value


class CreateEventsGoal(AgentGoalBase):
    """Goal that has Roboto's AI investigate a dataset and create events on it, of kinds the caller supplies.

    Every event the AI creates is on the dataset ``dataset_id`` and no other, takes a key of ``event_vocabulary`` as
    its name, and carries only tags that are keys of ``tag_vocabulary``. The descriptions in both vocabularies guide
    the AI's choice of time spans and tags. When ``collection_id`` is set, Roboto also adds every created event to that
    collection and no other.

    Only an organization whose :py:class:`~roboto.domain.orgs.EventModel` is
    :py:attr:`~roboto.domain.orgs.EventModel.Legacy` or ``Dual`` takes events on datasets. Declaring this goal on a
    dataset of any other organization raises ``RobotoInvalidRequestException``; declare ``SessionCreateEventsGoal``
    on a session instead.

    Building the goal raises ``pydantic.ValidationError`` when:

    - ``event_vocabulary`` is empty.
    - Either vocabulary has more than 50 entries, a blank key, a key longer than 100 characters, or a description that
      is blank or longer than 500 characters.
    - ``event_focus_prompt`` is empty or longer than 4000 characters.
    """

    goal_type: Literal[GoalType.CREATE_EVENTS] = GoalType.CREATE_EVENTS
    """Kind of goal, always ``GoalType.CREATE_EVENTS``."""

    dataset_id: str
    """ID of the dataset to investigate and create events on."""

    event_vocabulary: dict[str, str] = pydantic.Field(min_length=1, max_length=_MAX_EVENT_VOCABULARY)
    """Names of the events the AI may create, each mapped to a description of what that kind of event marks.

    The AI reads the descriptions to decide which time spans qualify.
    """

    tag_vocabulary: dict[str, str] = pydantic.Field(default_factory=dict, max_length=_MAX_TAG_VOCABULARY)
    """Tags the AI may put on the events it creates, each mapped to a description of when it applies.

    The AI picks any number of them for each event. Defaults to none, so created events carry no tags.
    """

    collection_id: Optional[str] = None
    """ID of the collection to add every created event to.

    It must be a collection of events (:py:attr:`~roboto.domain.collections.CollectionResourceType.Event`). ``None``
    adds them to no collection.
    """

    event_focus_prompt: Optional[str] = pydantic.Field(
        default=None, min_length=1, max_length=_MAX_EVENT_FOCUS_PROMPT_CHARS
    )
    """Further instructions for the AI on which events to create, from 1 to 4000 characters.

    For example, ``"only flag intervals longer than five seconds"``. ``None`` leaves the vocabulary descriptions as
    the only guidance.
    """

    @pydantic.field_validator("event_vocabulary")
    @classmethod
    def _validate_event_vocabulary(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_vocabulary(value, field_name="event_vocabulary")

    @pydantic.field_validator("tag_vocabulary")
    @classmethod
    def _validate_tag_vocabulary(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_vocabulary(value, field_name="tag_vocabulary")


class SessionSummaryAgentGoal(AgentGoalBase):
    """Goal that has Roboto's AI summarize a session.

    The AI stores the summary on the session ``session_id`` and no other, where
    :py:meth:`~roboto.experimental.sessions.Session.get_summary` returns it. Building the goal raises
    ``pydantic.ValidationError`` when ``summary_format_spec_prompt`` is empty or longer than 4000 characters.
    """

    goal_type: Literal[GoalType.SESSION_SUMMARY] = GoalType.SESSION_SUMMARY
    """Kind of goal, always ``GoalType.SESSION_SUMMARY``."""

    session_id: str
    """ID of the session to summarize."""

    summary_format_spec_prompt: Optional[str] = pydantic.Field(
        default=None, min_length=1, max_length=_MAX_SUMMARY_FORMAT_SPEC_CHARS
    )
    """Instructions for the AI on how to structure the summary, from 1 to 4000 characters.

    Roboto does not check the summary against them. ``None`` uses Roboto's default structure.
    """


class SessionTriageGoal(AgentGoalBase):
    """Goal that has Roboto's AI tag a session with the labels from a vocabulary that apply to it.

    The session counterpart of ``DatasetTriageGoal``, which states the rules ``label_vocabulary`` must follow; building
    this goal raises ``pydantic.ValidationError`` for the same values. Roboto adds the labels that apply, if any, to the
    tags of the session ``session_id`` and no other. The decisions are in the goal's
    :py:class:`~roboto.ai.goals.SessionTriageGoalResult`.
    """

    goal_type: Literal[GoalType.SESSION_TRIAGE] = GoalType.SESSION_TRIAGE
    """Kind of goal, always ``GoalType.SESSION_TRIAGE``."""

    session_id: str
    """ID of the session to tag."""

    label_vocabulary: dict[str, str] = pydantic.Field(min_length=1, max_length=_MAX_TRIAGE_LABELS)
    """Labels the AI chooses from, each mapped to a description of what it means.

    The AI reads each description to decide whether the label applies.
    """

    @pydantic.field_validator("label_vocabulary")
    @classmethod
    def _validate_vocabulary_entries(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_triage_vocabulary(value)


class SessionCreateEventsGoal(AgentGoalBase):
    """Goal that has Roboto's AI investigate a session and create session events on it, of kinds the caller supplies.

    The session counterpart of ``CreateEventsGoal``, which states the rules both vocabularies and
    ``event_focus_prompt`` must follow; building this goal raises ``pydantic.ValidationError`` for the same values.
    Every event the AI creates is on the session ``session_id`` and no other, has an ID beginning with ``evt_``, and
    is listed by :py:meth:`~roboto.experimental.sessions.Session.list_events`. Each event may name the topics of the
    session it concerns. Session events cannot be added to collections, so the goal has no ``collection_id``.

    Only an organization whose :py:class:`~roboto.domain.orgs.EventModel` is
    ``Dual``, ``Migrating`` or ``Session`` takes session events.
    """

    goal_type: Literal[GoalType.SESSION_CREATE_EVENTS] = GoalType.SESSION_CREATE_EVENTS
    """Kind of goal, always ``GoalType.SESSION_CREATE_EVENTS``."""

    session_id: str
    """ID of the session to investigate and create events on."""

    event_vocabulary: dict[str, str] = pydantic.Field(min_length=1, max_length=_MAX_EVENT_VOCABULARY)
    """Names of the events the AI may create, each mapped to a description of what that kind of event marks.

    The AI reads the descriptions to decide which time spans qualify.
    """

    tag_vocabulary: dict[str, str] = pydantic.Field(default_factory=dict, max_length=_MAX_TAG_VOCABULARY)
    """Tags the AI may put on the events it creates, each mapped to a description of when it applies.

    The AI picks any number of them for each event. Defaults to none, so created events carry no tags.
    """

    event_focus_prompt: Optional[str] = pydantic.Field(
        default=None, min_length=1, max_length=_MAX_EVENT_FOCUS_PROMPT_CHARS
    )
    """Further instructions for the AI on which events to create, from 1 to 4000 characters.

    ``None`` leaves the vocabulary descriptions as the only guidance.
    """

    @pydantic.field_validator("event_vocabulary")
    @classmethod
    def _validate_event_vocabulary(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_vocabulary(value, field_name="event_vocabulary")

    @pydantic.field_validator("tag_vocabulary")
    @classmethod
    def _validate_tag_vocabulary(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_vocabulary(value, field_name="tag_vocabulary")


AgentGoal = Annotated[
    Union[
        DatasetSummaryAgentGoal,
        DatasetTriageGoal,
        CreateEventsGoal,
        SessionSummaryAgentGoal,
        SessionTriageGoal,
        SessionCreateEventsGoal,
    ],
    pydantic.Field(discriminator="goal_type"),
]
"""Goal of any kind: an instance of one of the six goal classes.

The classes are ``DatasetSummaryAgentGoal``, ``DatasetTriageGoal``, ``CreateEventsGoal``, ``SessionSummaryAgentGoal``,
``SessionTriageGoal`` and ``SessionCreateEventsGoal``.

Pydantic picks the class from ``goal_type``. Only Roboto adds kinds of goal.
"""
