# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Optional

import pydantic


class ClientViewingContext(pydantic.BaseModel):
    """What the Roboto client (e.g. the Web UI) is currently viewing when the
    user composed a message.

    Passed to the agent as implicit context for resolving deictic references
    — "this dataset", "those files", "the visualizer state I'm looking at" —
    that the user would otherwise have to spell out. This type is purely
    informational; it is not enforced and never gates tool authorization.

    Distinct from:

    * :class:`AnalysisScope`, which is a hard analysis window honored by
      individual tools on the server side.
    * :class:`~roboto.ai.goals.AgentGoal`, which declares typed outcomes the
      agent runner must drive the turn to satisfy.

    The corresponding wire-format field is ``client_context`` (with a
    one-release ``context`` alias for migration).
    """

    dataset_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of datasets the user is currently viewing or has selected."""

    file_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of files the user is currently viewing or has selected."""

    visualizer_state: Optional[dict[str, Any]] = None
    """State of the visualizer, when the user composed the message from the
    visualizer view. A relatively opaque JSON blob."""

    misc_context: Optional[dict[str, Any]] = None
    """Miscellaneous client-supplied context that doesn't fit the typed fields
    above. Use sparingly; prefer adding a typed field when a recurring shape
    emerges."""


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
