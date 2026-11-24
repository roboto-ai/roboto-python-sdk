# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Optional

import pydantic

from ...time import _NanosecondsFromInteger


class ClientViewingContext(pydantic.BaseModel):
    """What the caller had open in their client, such as the Roboto web app, when they wrote a message to Roboto's AI.

    Carried in :py:attr:`~roboto.ai.agent_thread.StartAgentThreadRequest.client_context` and
    :py:attr:`~roboto.ai.agent_thread.SendMessageRequest.client_context`, and stored on the caller's message as
    :py:attr:`~roboto.ai.core.AgentClientContextEntry.context`. It lets the AI resolve references such as "this
    dataset" or "those files" without the caller naming them. It does not change what the AI may access: the AI
    still reads each resource through its own tools. Roboto also records each dataset, file and session it names as
    an :py:class:`~roboto.ai.agent_thread.AgentThreadSubject`, so the thread can be found from that resource.

    It differs from :py:class:`~roboto.ai.core.AnalysisScope`, which limits the data the AI's tools read, and from
    :py:class:`~roboto.ai.goals.AgentGoal`, which states a result the AI must reach in a turn.
    """

    dataset_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the datasets the caller had open or selected. Defaults to none."""

    file_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the files the caller had open or selected. Defaults to none."""

    collection_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the collections the caller had open or selected. Defaults to none."""

    device_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the devices the caller had open or selected. Defaults to none.

    Each is the ID the organization gave the device, such as a serial number, so unlike the other IDs here it has no
    fixed prefix.
    """

    device_type_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the device types the caller had open. Defaults to none."""

    session_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the sessions the caller had open. Defaults to none."""

    view_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of the Views applied to the resource table the caller had open. Defaults to none.

    A View is a saved, shareable search over one kind of resource. These IDs let the AI resolve "this View" without
    the caller naming it.
    """

    table_state: Optional[dict[str, Any]] = None
    """Resource table the caller had open, or ``None`` if they wrote the message from elsewhere.

    Holds the table's ``target`` (``datasets``, ``files``, ...) and its current ``definition``, in the shape a View
    stores: RoboQL text or filter controls, plus the visible columns, sort and page size. The client sends it whether
    or not a View is loaded, so the AI can describe filters the caller has not saved, and can save the table as it
    stands when the caller asks it to save what they are looking at as a View.
    """

    display_time_anchor_ns: Optional[int] = None
    """Time the client shows as zero, in nanoseconds since the Unix epoch, or ``None`` if it shows absolute times.

    The client sets it while the caller reads timestamps as time elapsed since this time. It lets the AI turn a
    relative time the caller types, such as "around 65 s", into an absolute time. The AI still reports times back in
    nanoseconds since the Unix epoch.
    """

    display_time_anchor_label: Optional[str] = None
    """Name the client shows for the time in ``display_time_anchor_ns``, or ``None`` when that field is ``None``.

    The name is "Start of workspace" or a chosen timestamp in local time. It lets the AI name the time an offset
    counts from.
    """

    visualizer_state: Optional[dict[str, Any]] = None
    """State of the visualizer, or ``None`` if the caller wrote the message from elsewhere.

    The Roboto web app defines its form.
    """

    misc_context: Optional[dict[str, Any]] = None
    """Other context from the client that fits none of the other fields, or ``None`` for none."""


class AnalysisScope(pydantic.BaseModel):
    """Time window of the data Roboto's AI analyzes in a thread.

    Carried in :py:attr:`~roboto.ai.agent_thread.StartAgentThreadRequest.analysis_scope`,
    :py:attr:`~roboto.ai.agent_thread.SendMessageRequest.analysis_scope`,
    :py:attr:`~roboto.ai.agent.LaunchAgentRequest.analysis_scope` and
    :py:attr:`~roboto.domain.triggers.StartAgentTarget.analysis_scope`. Roboto passes the scope to each tool the AI
    calls, and each tool decides whether to apply it. A bound left ``None`` leaves that end of the window open, so a
    scope with both bounds ``None`` limits nothing.

    Building it raises ``pydantic.ValidationError`` when ``start_time`` is after ``end_time``.
    """

    start_time: Optional[_NanosecondsFromInteger] = None
    """Inclusive start of the window, in nanoseconds since the Unix epoch. ``None`` leaves the start open."""

    end_time: Optional[_NanosecondsFromInteger] = None
    """Inclusive end of the window, in nanoseconds since the Unix epoch. ``None`` leaves the end open."""

    @pydantic.model_validator(mode="after")
    def _validate_time_window(self) -> "AnalysisScope":
        if self.start_time is not None and self.end_time is not None and self.start_time > self.end_time:
            raise ValueError(f"AnalysisScope.start_time ({self.start_time}) must be <= end_time ({self.end_time}).")
        return self

    def merge(self, override: "AnalysisScope") -> "AnalysisScope":
        """Build a scope that takes each bound from ``override`` when it is set, and from this scope otherwise.

        Roboto calls this when a user launches an agent, or a trigger starts one, with a scope set. It merges that
        scope, as ``override``, into the scope in the agent's request template, as this scope.

        Args:
            override: Scope whose bounds replace this scope's. A bound left ``None`` keeps this scope's.

        Returns:
            A new scope. Neither this scope nor ``override`` changes.

        Raises:
            pydantic.ValidationError: The resulting start is after the resulting end, as when ``override`` sets only a
                start later than this scope's end.
        """
        return AnalysisScope(
            start_time=override.start_time if override.start_time is not None else self.start_time,
            end_time=override.end_time if override.end_time is not None else self.end_time,
        )
