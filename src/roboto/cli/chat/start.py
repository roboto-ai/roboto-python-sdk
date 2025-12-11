# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import typing

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from ...ai.chat import Chat
from ...ai.chat.event import (
    ChatStartTextEvent,
    ChatTextDeltaEvent,
    ChatTextEndEvent,
    ChatToolResultEvent,
    ChatToolUseEvent,
)
from ..command import RobotoCommand
from ..common_args import add_org_arg
from ..context import CLIContext

VALID_EXIT_COMMANDS = ("quit", "exit", "q", "e")


class RobotoPrompt(Prompt):
    prompt_suffix = "> "


class RobotoSpinner:
    def __init__(self, console: Console, text: str, transient: bool = False):
        spinner = Spinner("dots", text=text, style="cyan")
        self._text = text
        self._live = Live(spinner, console=console, refresh_per_second=10, transient=transient)

    def start(self):
        self._live.start()

    def stop(self):
        # Use Text.from_markup to properly render rich markup in the text
        self._live.update(Text.from_markup(f"[bold green]✓ {self._text}[/bold green]"))
        self._live.stop()


class RobotoMultiToolSpinner:
    def __init__(self, console: Console, transient: bool = False):
        self._console = console
        self._live = Live(console=console, refresh_per_second=10, transient=transient)
        self._spinners: dict[str, RobotoSpinner] = {}

        self._in_progress_tools: set[str] = set()
        self._completed_tools: set[str] = set()
        self._failed_tools: set[str] = set()
        self._tool_id_to_name: dict[str, str] = {}

    def begin_tool_call(self, event: ChatToolUseEvent):
        self._tool_id_to_name[event.tool_use_id] = event.name
        self._in_progress_tools.add(event.tool_use_id)
        self._render()

    def end_tool_call(self, event: ChatToolResultEvent):
        self._in_progress_tools.remove(event.tool_use_id)
        if event.success:
            self._completed_tools.add(event.tool_use_id)
        else:
            self._failed_tools.add(event.tool_use_id)
        self._render()

    def has_in_progress_tools(self) -> bool:
        return len(self._in_progress_tools) > 0

    def _render(self):
        grid = Table.grid()
        grid.add_column()

        for tool_id in self._completed_tools:
            grid.add_row(Text.from_markup(f"[bold green]✓ {self._tool_id_to_name[tool_id]}[/bold green]"))

        for tool_id in self._failed_tools:
            grid.add_row(Text.from_markup(f"[bold red]✗ {self._tool_id_to_name[tool_id]}[/bold red]"))

        for tool_id in self._in_progress_tools:
            grid.add_row(
                Spinner(
                    "dots",
                    text=f"Using tool [bold]{self._tool_id_to_name[tool_id]}[/bold]",
                    style="cyan",
                )
            )

        self._live.update(grid)

    def start(self):
        self._live.start()

    def stop(self):
        self._failed_tools.update(self._in_progress_tools)
        self._in_progress_tools.clear()
        self._render()
        self._live.stop()


class RobotoMarkdown:
    def __init__(self, content: str, console: Console):
        self._console = console
        self._content = content
        md = Markdown(content)
        self._live = Live(md, console=console, refresh_per_second=4)

    def start(self):
        self._live.start()

    def add_content(self, content: str):
        self._content += content

        if len(self._content) > 1000 and "\n\n" in self._content:
            break_idx = self._content.rfind("\n\n")
            original_content = self._content[: break_idx + 2]
            new_content = self._content[break_idx + 2 :]
            self._live.update(Markdown(original_content))
            self._live.stop()
            self._content = new_content
            self._live = Live(Markdown(self._content), console=self._console, refresh_per_second=4)
            self._live.start()

        md = Markdown(self._content)
        self._live.update(md)

    def stop(self):
        self._live.stop()


def _print_welcome_banner(console: Console):
    """Print a stylized welcome banner using rich components."""
    # Create ASCII art with rich styling
    art_lines = [
        "      [white]@@@@@@@@@@[/white]        ",
        "   [white]@@@@@@@@@@@@@@@@[/white]     ",
        "  [white]@@@@@@@@@@@@@@@@@@@[/white]   ",
        " [white]@@@@@@        @@@@@@@[/white]  ",
        "[white]@@@@@    [red]====[white]    @@@@@[/white]  ",
        "[red]        ======[white]   @@@@@[/white]  ",
        "[red]        ======[white]   @@@@@[/white]  ",
        "[white]@@@@@    [red]====[white]    @@@@@[/white]  ",
        "[white]@@@@@          @@@@@@[/white]   ",
        "[white]@@@@@       @@@@@@@@[/white]    ",
        "[white]@@@@@ [blue]     [white]@@@@@@@[/white]      ",
        "[white]@@@@@ [blue]oboto [white]@@@@@@[/white]      ",
        "[white]@@@@@ [blue]chat   [white]@@@@@@[/white]     ",
        "[white]@@@@@ [blue]client  [white]@@@@@@[/white]    ",
        "[white]@@@@@ [blue]for cool  [white]@@@@@[/white]   ",
        "[white]@@@@@ [blue]engineers  [white]@@@@@@[/white] ",
    ]

    art_text = "\n".join(art_lines)
    panel = Panel(
        art_text,
        border_style="cyan",
        padding=(1, 2),
        title="[bold cyan]Roboto Chat[/bold cyan]",
        subtitle="[dim]AI-powered assistant[/dim]",
    )
    console.print(panel)
    console.print()


def start(args, context: CLIContext, parser: argparse.ArgumentParser):
    org_id = args.org

    console = Console()
    _print_welcome_banner(console)

    console.print(
        f"[dim]What do you want to chat about? (Enter [cyan]{'/'.join(VALID_EXIT_COMMANDS)}[/cyan] to exit)[/dim]"
    )
    console.print()

    chat: typing.Union[Chat, None] = None
    thinking_spinner: RobotoSpinner | None
    multi_tool_spinner: RobotoMultiToolSpinner | None = None
    markdown: RobotoMarkdown | None = None

    while True:
        try:
            prompt = RobotoPrompt.ask(console=console)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Goodbye![/yellow]")
            break

        if prompt.lower() in VALID_EXIT_COMMANDS:
            console.print("[yellow]Goodbye![/yellow]")
            break

        if prompt.strip() == "":
            continue

        console.print()
        thinking_spinner = RobotoSpinner(console=console, text="Thinking...", transient=True)
        thinking_spinner.start()

        if chat is None:
            chat = Chat.start(
                message=prompt,
                org_id=org_id,
                roboto_client=context.roboto_client,
            )
        else:
            chat.send_text(prompt)

        for event in chat.stream_events():
            if thinking_spinner is not None:
                thinking_spinner.stop()
                thinking_spinner = None

            if isinstance(event, ChatStartTextEvent):
                if multi_tool_spinner is not None:
                    multi_tool_spinner.stop()
                    multi_tool_spinner = None
                    console.print()

                markdown = RobotoMarkdown(content="", console=console)
                markdown.start()

            elif isinstance(event, ChatTextDeltaEvent):
                if markdown is not None:
                    markdown.add_content(event.text)

            elif isinstance(event, ChatTextEndEvent):
                if markdown is not None:
                    markdown.stop()
                    console.print()

            elif isinstance(event, ChatToolUseEvent):
                if multi_tool_spinner is None:
                    multi_tool_spinner = RobotoMultiToolSpinner(console=console)
                    multi_tool_spinner.start()

                multi_tool_spinner.begin_tool_call(event)

            elif isinstance(event, ChatToolResultEvent):
                if multi_tool_spinner is not None:
                    multi_tool_spinner.end_tool_call(event)
                    if not multi_tool_spinner.has_in_progress_tools():
                        multi_tool_spinner.stop()
                        multi_tool_spinner = None
                        console.print()

                        thinking_spinner = RobotoSpinner(console=console, text="Thinking...", transient=True)
                        thinking_spinner.start()

        if thinking_spinner is not None:
            thinking_spinner.stop()


def start_setup_parser(parser):
    add_org_arg(parser)


start_command = RobotoCommand(
    name="start",
    logic=start,
    setup_parser=start_setup_parser,
    command_kwargs={"help": "Start an interactive chat session."},
)
