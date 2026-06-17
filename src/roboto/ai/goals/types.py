# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Annotated, Any, Literal, Optional, Union

import pydantic

from ...compat import StrEnum


class GoalType(StrEnum):
    """Discriminator values for the :data:`AgentGoal` union.

    Each value pairs with exactly one :class:`pydantic.BaseModel` subclass below
    and one server-side ``GoalHandler`` registration. The string value is the
    canonical identifier used in persistence (``agent_session_goals.goal_type``),
    in the Bedrock-facing achieve-tool name, and in the wire format.
    """

    DATASET_SUMMARY = "dataset_summary"
    """Produce and persist a dataset summary via ``SummaryService.set_dataset_summary``."""

    DATASET_TRIAGE = "dataset_triage"
    """Deliberate over a caller-supplied label vocabulary and apply the labels that fit (zero or more) as tags
    on the dataset, with a per-label justification recorded in the agent session log."""

    CREATE_EVENTS = "create_events"
    """Investigate a dataset and create events on it, drawn from a caller-supplied event vocabulary;
    optionally file each created event into a caller-supplied collection."""


class AgentGoalStatus(StrEnum):
    """Lifecycle of a per-turn declared goal.

    Goals begin PENDING when registered. They transition to ACHIEVED when the
    corresponding achieve-tool reports success, or to FAILED when the runner's
    corrective re-prompt budget for the turn is exhausted (or when the worker
    cannot construct an achieve-tool for the goal).
    """

    PENDING = "pending"
    """Goal has been registered but not yet completed."""

    ACHIEVED = "achieved"
    """Goal's corresponding achieve-tool was invoked successfully."""

    FAILED = "failed"
    """Goal could not be achieved within the turn's retry budget."""


class AgentGoalBase(pydantic.BaseModel):
    """Shared base for every :data:`AgentGoal` subclass.

    Subclasses must declare a literal-typed discriminator field, e.g.
    ``goal_type: Literal[GoalType.MY_GOAL] = GoalType.MY_GOAL``. Two
    machineries enforce that contract:

    - :meth:`__pydantic_init_subclass__` raises ``TypeError`` at class-body
      parse if a subclass forgets ``goal_type`` — converts a silent dispatch
      footgun into a loud failure.
    - :meth:`_force_discriminator_into_fields_set` marks ``goal_type`` as
      explicitly set after construction so it survives the SDK's
      ``model_dump_json(exclude_unset=True)`` serialization and reaches the
      server's discriminated-union parser. Without it, default-valued
      ``goal_type`` would be stripped on the wire and the server would 400
      with "Request body malformed".
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


class DatasetSummaryAgentGoal(AgentGoalBase):
    """Goal: summarize a specific dataset and persist the result.

    The achieve-tool wired to this goal must call
    ``SummaryService.set_dataset_summary`` against the dataset identified by
    :attr:`dataset_id` (no other dataset). The format spec is supplied to the
    LLM as part of the goal prompt block; the achieve-tool itself does not
    interpret it.
    """

    goal_type: Literal[GoalType.DATASET_SUMMARY] = GoalType.DATASET_SUMMARY
    """Discriminator. Always :attr:`GoalType.DATASET_SUMMARY`."""

    dataset_id: str
    """Identifier of the dataset to summarize. The achieve-tool enforces this as an invariant."""

    summary_format_spec_prompt: Optional[str] = pydantic.Field(default=None, min_length=1, max_length=4000)
    """Caller-provided natural-language guidance about the desired summary structure. ``None`` means use the
    handler's opinionated default. When set, must be 1-4000 characters; an empty string is rejected so callers
    don't accidentally suppress the default with whitespace-stripped input."""


_TRIAGE_LABEL_PATTERN = r"^[a-zA-Z0-9_\-]+$"
"""Pattern label keys must satisfy. Mirrors the conservative subset of characters
that work cleanly as Roboto dataset tags and as Bedrock-tool enum values: ASCII
alphanumerics plus underscore and hyphen."""

_MAX_TRIAGE_LABELS = 50
"""Cap on vocabulary size; prevents runaway prompt + tool-schema bloat."""

_MAX_TRIAGE_DESCRIPTION_CHARS = 500
"""Per-label description length cap; keeps the prompt budget predictable."""


class DatasetTriageGoal(AgentGoalBase):
    """Goal: deliberate over a caller-supplied label vocabulary and apply the labels that fit.

    The achieve-tool requires one decision per vocabulary entry — each with
    ``applies: bool`` plus a justification and confidence. Labels with
    ``applies=true`` (zero or more) become tags on the dataset identified
    by :attr:`dataset_id`; per-label reasoning lives in the agent session
    log, not on the dataset itself.
    """

    goal_type: Literal[GoalType.DATASET_TRIAGE] = GoalType.DATASET_TRIAGE
    """Discriminator. Always :attr:`GoalType.DATASET_TRIAGE`."""

    dataset_id: str
    """Identifier of the dataset to triage. The achieve-tool enforces this as an invariant."""

    label_vocabulary: dict[str, str] = pydantic.Field(min_length=1, max_length=_MAX_TRIAGE_LABELS)
    """Allowable labels for this triage action, mapped to descriptions. Keys are the labels the LLM may
    choose between; values describe what each label signifies so the LLM can pick correctly. Must contain
    at least one entry and at most :data:`_MAX_TRIAGE_LABELS`. Each key must match :data:`_TRIAGE_LABEL_PATTERN`
    (ASCII alphanumerics, underscore, hyphen). Each description must be 1-:data:`_MAX_TRIAGE_DESCRIPTION_CHARS`
    characters."""

    @pydantic.field_validator("label_vocabulary")
    @classmethod
    def _validate_vocabulary_entries(cls, value: dict[str, str]) -> dict[str, str]:
        import re

        label_re = re.compile(_TRIAGE_LABEL_PATTERN)
        for label, description in value.items():
            if not label_re.match(label):
                raise ValueError(
                    f"label_vocabulary key {label!r} is not a valid label: must match {_TRIAGE_LABEL_PATTERN!r} "
                    "(ASCII alphanumerics, underscore, hyphen). Labels are persisted as dataset tags and reflected "
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


_MAX_EVENT_FOCUS_PROMPT_CHARS = 4000
"""Length cap on :attr:`CreateEventsGoal.event_focus_prompt`; keeps the prompt budget predictable."""

_MAX_EVENT_VOCABULARY = 50
"""Cap on :attr:`CreateEventsGoal.event_vocabulary` size; prevents runaway prompt + tool-schema
bloat. Mirrors the conservative cap on triage labels."""

_MAX_TAG_VOCABULARY = 50
"""Cap on :attr:`CreateEventsGoal.tag_vocabulary` size; same rationale as :data:`_MAX_EVENT_VOCABULARY`."""

_MAX_VOCABULARY_KEY_CHARS = 100
"""Per-entry key length cap for either vocabulary. Keys are reflected into the achieve-tool's enums
and become created events' ``name`` / ``tags``; the cap keeps both bounded."""

_MAX_VOCABULARY_DESCRIPTION_CHARS = 500
"""Per-entry description length cap for either vocabulary; keeps the prompt budget predictable."""


def _validate_vocabulary(value: dict[str, str], *, field_name: str) -> dict[str, str]:
    """Shared entry validator for :class:`CreateEventsGoal`'s two vocabularies.

    Both ``event_vocabulary`` and ``tag_vocabulary`` map a short key (an event-type
    name / a tag) to a description rendered into the prompt. Keys must be non-empty
    and at most :data:`_MAX_VOCABULARY_KEY_CHARS`; descriptions non-empty and at most
    :data:`_MAX_VOCABULARY_DESCRIPTION_CHARS`.
    """
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
    """Goal: investigate a dataset and create tagged events on it from fixed vocabularies.

    The caller declares :attr:`event_vocabulary` — a fixed set of event types
    (name → description) the agent may create — and, optionally, :attr:`tag_vocabulary`
    — a fixed set of tags (tag → when-to-apply description) the agent may attach.
    The achieve-tool constrains every submitted event's ``name`` to an
    ``event_vocabulary`` key and every tag to a ``tag_vocabulary`` key, so the agent
    can only file events of the declared kinds carrying the declared tags; the
    descriptions steer which intervals qualify and which tags fit. Every created
    event is associated with the dataset identified by :attr:`dataset_id`. When
    :attr:`collection_id` is set, each created event is also added to that (event)
    collection; when it is ``None``, events are created but not filed into any
    collection. The dataset id — and the collection id when set — are
    constructor-injected into the achieve-tool so the LLM cannot redirect the work.
    """

    goal_type: Literal[GoalType.CREATE_EVENTS] = GoalType.CREATE_EVENTS
    """Discriminator. Always :attr:`GoalType.CREATE_EVENTS`."""

    dataset_id: str
    """Identifier of the dataset to investigate. Every created event is associated with this
    dataset. The achieve-tool enforces this as an invariant."""

    event_vocabulary: dict[str, str] = pydantic.Field(min_length=1, max_length=_MAX_EVENT_VOCABULARY)
    """Fixed set of event types the agent may create, mapped to descriptions. Keys are the event
    names the LLM may choose between — each becomes the ``name`` of a created event — and values
    describe what each event type signifies so the LLM can decide which intervals qualify. Must
    contain at least one entry and at most :data:`_MAX_EVENT_VOCABULARY`."""

    tag_vocabulary: dict[str, str] = pydantic.Field(default_factory=dict, max_length=_MAX_TAG_VOCABULARY)
    """Fixed set of tags the agent may attach to created events, mapped to descriptions of when each
    tag applies. For every event it creates the agent picks a subset (possibly empty) of these tags.
    Empty (the default) means created events carry no tags. At most :data:`_MAX_TAG_VOCABULARY`
    entries."""

    collection_id: Optional[str] = None
    """Identifier of the collection every created event is added to. ``None`` (the default) means
    created events are not filed into any collection. When set, the achieve-tool enforces it as an
    invariant and the target must be an event collection."""

    event_focus_prompt: Optional[str] = pydantic.Field(
        default=None, min_length=1, max_length=_MAX_EVENT_FOCUS_PROMPT_CHARS
    )
    """Caller-provided natural-language guidance layered on top of the vocabularies (e.g. "only flag
    intervals longer than five seconds"). ``None`` means the vocabulary descriptions alone steer the
    agent. When set, must be 1-:data:`_MAX_EVENT_FOCUS_PROMPT_CHARS` characters; an empty string is
    rejected so callers don't accidentally suppress the guidance with whitespace-stripped input."""

    @pydantic.field_validator("event_vocabulary")
    @classmethod
    def _validate_event_vocabulary(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_vocabulary(value, field_name="event_vocabulary")

    @pydantic.field_validator("tag_vocabulary")
    @classmethod
    def _validate_tag_vocabulary(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_vocabulary(value, field_name="tag_vocabulary")


AgentGoal = Annotated[
    Union[DatasetSummaryAgentGoal, DatasetTriageGoal, CreateEventsGoal],
    pydantic.Field(discriminator="goal_type"),
]
"""Closed, Roboto-controlled discriminated union of all declarable agent goals.

Validated via pydantic discriminator on ``goal_type``. Add new goals by
extending the ``Union`` and registering a corresponding ``GoalHandler``.

A goal is the right primitive when the caller has an upfront, verifiable
platform mutation the turn must complete — and is willing to fail the turn
(``AgentThreadStatus.GOALS_FAILED``) if the action doesn't happen. Goals
power specialized agents with deterministic, directionally opinionated
behavior. One-off LLM-discovered actions and pure reads belong as regular
:class:`AgentTool` registrations; actions that don't need an LLM at all
belong as direct REST endpoints. The registry is closed to keep this
discipline visible at PR-review time.
"""
