# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import dataclasses
import sys
import typing

from ..context import cli_roboto_env, make_cli_client
from ..outcome import (
    StepOutcome,
    StepStatus,
    print_heading,
    print_outcomes,
)
from .credentials import set_up_credentials
from .environment import AiTool, SetupEnvironment
from .mcp import ROBOTO_MCP_URL, register_mcp_server
from .prerequisites import check_docker, check_uv
from .prompts import (
    NO_ANSWERS,
    YES_ANSWERS,
    InputEnded,
    Prompts,
    answer_to,
    confirm,
)
from .skills import SKILL_READERS, set_up_agent_skills

HELP = "Set up this machine to use Roboto: check your access token, install agent skills, and connect your AI tools."

DESCRIPTION = (
    "Set up this machine to use Roboto from the command line, the Python SDK, and your AI tools. "
    + "Checks your access token, or asks for one, and asks which organization to use by default if you belong to "
    + "several. For the AI tools you choose among Claude Code, Codex, Cursor, and VS Code, installs Roboto's agent "
    + "skills and adds the Roboto MCP server, then signs Claude Code and Codex in to it. Checks for uv and Docker, "
    + "which the skills use, and offers to install uv. Running it again updates the agent skills and changes nothing "
    + "else that is already set up."
)


def setup_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-input",
        action="store_true",
        help="Ask nothing: report a missing access token or default organization, connect every AI tool found, and "
        + "skip each sign-in and the offer to install uv. Implied when standard input isn't a terminal.",
    )
    parser.add_argument(
        "--skip-skills",
        action="store_true",
        help="Don't install Roboto's agent skills or check for uv and Docker.",
    )
    parser.add_argument(
        "--skip-mcp",
        action="store_true",
        help="Don't add the Roboto MCP server to your AI tools.",
    )
    parser.add_argument(
        "--mcp-url",
        default=ROBOTO_MCP_URL,
        help=f"Address of the Roboto MCP server to add. Defaults to {ROBOTO_MCP_URL}.",
    )


def run(args: argparse.Namespace) -> None:
    """Run every setup step, printing each one's outcome as it finishes with anything it leaves the user to do.

    Ends by saying what to do next: fix what failed, when a step failed; otherwise finish any steps left for the user
    and, when a default organization is known and an AI tool was chosen, ask that tool a first question.

    Exits with status 1 when any step failed. The user stops setup by pressing Ctrl-C, which exits with status 130,
    or by pressing Ctrl-D at a question, which exits with status 1. During an AI tool's sign-in, Ctrl-C skips that
    sign-in instead.
    """
    color = sys.stdout.isatty()
    try:
        result = _run_steps(args, color)
    except (KeyboardInterrupt, InputEnded) as stop:
        # Stopping here leaves no file half-written: AI tools' config files, an existing Roboto config file, and each
        # skill directory are written under a temporary name and renamed into place, and a new Roboto config file
        # that is interrupted mid-write is deleted. Running setup again redoes whatever was cut short.
        print()
        print("Setup stopped. Run `roboto setup` again to finish.")
        sys.exit(130 if isinstance(stop, KeyboardInterrupt) else 1)

    print()
    if any(outcome.status is StepStatus.Failed for outcome in result.outcomes):
        print("Setup finished with failures. Fix the [failed] steps above, then run `roboto setup` again.")
        sys.exit(1)

    steps_left = any(outcome.status is StepStatus.ActionNeeded for outcome in result.outcomes)
    if result.organization_name is not None and result.chosen_tools:
        restart = "Do the [todo] steps above, then restart" if steps_left else "Restart"
        print(f'Setup finished. {restart} your AI tools and ask: "What datasets are in {result.organization_name}?"')
    elif steps_left:
        print("Setup finished. Do the [todo] steps above.")
    else:
        print("Setup finished.")
    print("Run `roboto setup` again at any time to check your setup or update Roboto's agent skills.")


@dataclasses.dataclass(frozen=True)
class _SetupResult:
    chosen_tools: list[AiTool]
    """The AI tools the user chose to connect to Roboto, or every tool found when nobody was asked. Empty when no tool
    was found, and when both ``--skip-skills`` and ``--skip-mcp`` were given."""

    organization_name: typing.Optional[str]
    """Name of the organization commands act in by default, when there is one."""

    outcomes: list[StepOutcome]


def _run_steps(args: argparse.Namespace, color: bool) -> _SetupResult:
    environment = SetupEnvironment.current()
    interactive = not args.no_input and sys.stdin.isatty()
    prompts = Prompts.for_terminal(environment.env, environment.platform) if interactive else None

    outcomes: list[StepOutcome] = []

    def report(*step_outcomes: StepOutcome) -> None:
        outcomes.extend(print_outcomes(list(step_outcomes), color))

    print_heading("Roboto access", color)
    access = set_up_credentials(
        cli_roboto_env(args.config_file),
        prompts,
        make_client=make_cli_client,
        profile=args.profile,
        # Printed before setup asks which organization to use, so the question follows the token it depends on.
        report_token=report,
    )
    if access.organization is not None:
        report(access.organization)

    chosen_tools: list[AiTool] = []
    if not (args.skip_skills and args.skip_mcp):
        print_heading("AI tools", color)
        found = environment.ai_tools
        if not found:
            # With no tool found, there is nothing to choose. The skills still go to the shared skills directory,
            # since an AI tool that setup doesn't look for may read them there, and each step's outcome says what to do
            # for such a tool.
            if not args.skip_skills:
                report(set_up_agent_skills(environment))
            if not args.skip_mcp:
                report(*register_mcp_server(environment, mcp_url=args.mcp_url))
        else:
            print(f"  Found {', '.join(tool.value for tool in found)}.")
            chosen_tools = _choose_tools(found, prompts)
            if not chosen_tools:
                print("  Connected no AI tools.")
            # Skipped when no chosen tool reads skills: the skills step would install them all the same,
            # and then report that it found no AI tool that reads them.
            if not args.skip_skills and any(tool in SKILL_READERS for tool in chosen_tools):
                report(set_up_agent_skills(environment, tools=chosen_tools))
            if not args.skip_mcp:
                # One tool at a time, so each tool's line is printed as soon as its sign-in ends.
                for tool in chosen_tools:
                    report(*register_mcp_server(environment, mcp_url=args.mcp_url, tools=[tool], sign_in=interactive))

    if not args.skip_skills:
        print_heading("Optional", color)
        report(check_uv(environment, prompts))
        report(check_docker(environment))

    return _SetupResult(chosen_tools=chosen_tools, organization_name=access.organization_name, outcomes=outcomes)


def _choose_tools(found: list[AiTool], prompts: typing.Optional[Prompts]) -> list[AiTool]:
    """Ask which of ``found`` to connect to Roboto, and return them: all, none, or those chosen one by one.

    A single tool gets a yes-or-no question. When ``prompts`` is ``None``, nothing is asked and every tool is returned.
    """
    if prompts is None:
        return found

    if len(found) == 1:
        return found if confirm(prompts, "  Connect it to Roboto?") else []

    while True:
        answer = answer_to(prompts, "  Connect all of them to Roboto? [Y/n/choose] ").lower()
        if answer in YES_ANSWERS:
            return found
        if answer in NO_ANSWERS:
            return []
        if answer in ("c", "choose"):
            return [tool for tool in found if confirm(prompts, f"  Connect {tool.value} to Roboto?")]
