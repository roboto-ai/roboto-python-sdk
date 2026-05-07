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


AgentGoal = Annotated[
    Union[DatasetSummaryAgentGoal, DatasetTriageGoal],
    pydantic.Field(discriminator="goal_type"),
]
"""Closed, Roboto-controlled discriminated union of all declarable agent goals.

Validated via pydantic discriminator on ``goal_type``. Add new goals by
extending the ``Union`` and registering a corresponding ``GoalHandler``.

A goal is the right primitive when the caller has an upfront, verifiable
platform mutation the turn must complete — and is willing to fail the turn
(``AgentSessionStatus.GOALS_FAILED``) if the action doesn't happen. Goals
power specialized agents with deterministic, directionally opinionated
behavior. One-off LLM-discovered actions and pure reads belong as regular
:class:`AgentTool` registrations; actions that don't need an LLM at all
belong as direct REST endpoints. The registry is closed to keep this
discipline visible at PR-review time.
"""
