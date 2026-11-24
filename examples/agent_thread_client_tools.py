# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import pathlib

from roboto.ai import AgentThread, client_tool
from roboto.ai.agent_thread import (
    AgentEvent,
    AgentStartTextEvent,
    AgentTextDeltaEvent,
    AgentTextEndEvent,
    AgentToolResultEvent,
    AgentToolUseEvent,
)

# Next to this script, so that the tools read and write the same file from any working directory.
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
        query: Substring to search for, ignoring case.
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
    """Ask Roboto's AI to store a fact and recall it with two client tools, and print the thread as it runs.

    A client tool is a Python function that the AI asks the caller to run. Whenever the AI requests ``remember`` or
    ``recall``, ``AgentThread.run`` calls it in this process and submits its result to the AI. The tools keep facts as
    lines of a Markdown file, ``knowledge.md``, next to this script.

    Running it requires programmatic access to Roboto:
    https://docs.roboto.ai/getting-started/programmatic-access.html

    Run it with ``python packages/roboto/examples/agent_thread_client_tools.py``.
    """
    # Delete the facts earlier runs stored, so that recall finds only the one this run stores.
    if KB_FILE.exists():
        KB_FILE.unlink()

    thread = AgentThread.start(
        "First, remember that my favorite color is blue. Then recall my favorite color and tell me what it is.",
        client_tools=[remember, recall],
        org_id="roboto-public",
    )
    print(f"Started thread {thread.thread_id}")

    thread.run(on_event=_print_event)

    print("\n=== Transcript ===")
    print(thread.transcript)


if __name__ == "__main__":
    main()
