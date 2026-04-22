# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Example: AgentSession with client-side tools.

Demonstrates how to expose Python functions as client-side tools that the
Roboto agent can invoke. This example implements two toy memory tools
(``remember`` and ``recall``) backed by a local markdown file as the
knowledge store.

Running this script requires programmatic access to a Roboto deployment:
    https://docs.roboto.ai/getting-started/programmatic-access.html

Then:

    python packages/roboto/examples/agent_session_client_tools.py
"""

from __future__ import annotations

import pathlib

from roboto.ai import AgentSession, client_tool
from roboto.ai.agent_session import (
    AgentEvent,
    AgentStartTextEvent,
    AgentTextDeltaEvent,
    AgentTextEndEvent,
    AgentToolResultEvent,
    AgentToolUseEvent,
)

# Anchor the KB file next to the script so running from any cwd is consistent.
KB_FILE = pathlib.Path(__file__).with_name("knowledge.md")


@client_tool
def remember(fact: str) -> str:
    """Append a fact to long-term memory.

    Args:
        fact: A standalone sentence describing something worth remembering.
    """
    KB_FILE.touch(exist_ok=True)
    with KB_FILE.open("a") as f:
        f.write(f"- {fact}\n")
    return "stored"


@client_tool
def recall(query: str) -> str:
    """Search long-term memory for facts matching a substring.

    Args:
        query: A substring to search for (case-insensitive).
    """
    if not KB_FILE.exists():
        return "no facts recorded yet"
    hits = [line for line in KB_FILE.read_text().splitlines() if query.lower() in line.lower()]
    return "\n".join(hits) if hits else f"no matches for {query!r}"


def _print_event(event: AgentEvent) -> None:
    if isinstance(event, AgentStartTextEvent):
        print("  [text]        ", end="", flush=True)
    elif isinstance(event, AgentTextDeltaEvent):
        print(event.text, end="", flush=True)
    elif isinstance(event, AgentTextEndEvent):
        print()
    elif isinstance(event, AgentToolUseEvent):
        print(f"  [tool-use]    {event.name}({event.input})")
    elif isinstance(event, AgentToolResultEvent):
        status = "ok" if event.success else "error"
        print(f"  [tool-result] {event.name} -> {status}")


def main() -> None:
    # Clear the KB so re-running the demo produces a clean recall sequence
    # rather than surfacing stale facts from prior runs.
    if KB_FILE.exists():
        KB_FILE.unlink()

    session = AgentSession.start(
        "First, remember that my favorite color is blue. Then recall my favorite color and tell me what it is.",
        client_tools=[remember, recall],
        org_id="roboto-public",
    )
    print(f"Started session {session.session_id}")

    session.run(on_event=_print_event)

    print("\n=== Transcript ===")
    print(session.transcript)


if __name__ == "__main__":
    main()
