# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Optional

import pydantic


class RobotoLLMContext(pydantic.BaseModel):
    """Contextual information about what a user is trying to do. May be passed along to Roboto LLM based code paths
    in order to enrich results"""

    dataset_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of datasets that are relevant to the user's query."""

    file_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of files that are relevant to the user's query."""

    visualizer_state: Optional[dict[str, Any]] = None
    """State of the visualizer, if a request is being made from the visualizer. This is expected to be a relatively
    opaque JSON blob"""

    misc_context: Optional[dict[str, Any]] = None
    """Miscellaneous context that is relevant to the user's query."""


class AnalysisScope(pydantic.BaseModel):
    """The slice of data an agent is expected to analyze.

    An ``AnalysisScope`` is delivered to every ``AgentTool`` invocation on
    the server side. Individual tools opt in to honoring the scope as they
    are adopted; this SDK type carries the configuration, it does not
    itself enforce anything. Fields set to ``None`` are unconstrained on
    that dimension; an ``AnalysisScope`` with every field ``None`` is
    equivalent to no scope at all.
    """

    start_time: Optional[int] = None
    """Lower bound (inclusive) of the analysis window, expressed as nanoseconds since the Unix epoch."""

    end_time: Optional[int] = None
    """Upper bound (inclusive) of the analysis window, expressed as nanoseconds since the Unix epoch."""

    @pydantic.model_validator(mode="after")
    def _validate_time_window(self) -> "AnalysisScope":
        if self.start_time is not None and self.end_time is not None and self.start_time > self.end_time:
            raise ValueError(f"AnalysisScope.start_time ({self.start_time}) must be <= end_time ({self.end_time}).")
        return self
