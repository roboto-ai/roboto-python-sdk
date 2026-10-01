# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import typing

from ..outcome import StepOutcome, StepStatus
from ..terminal import quote_for_shell
from .environment import AiTool, SetupEnvironment
from .files import write_file_atomically

if sys.version_info >= (3, 11):
    import tomllib

ROBOTO_MCP_URL = "https://mcp.roboto.ai/mcp"
MCP_DOCS_URL = "https://docs.roboto.ai/user-guides/use-roboto-mcp-server.html"

MCP_SERVER_NAME = "roboto"

CLAUDE_CLI_TIMEOUT_SECONDS = 60
CODEX_CLI_TIMEOUT_SECONDS = 60

# Characters cmd.exe acts on in the arguments of a batch file it runs: it expands %NAME%, reads ^ as an escape, ends
# the command at & | < > or a line break, and a " changes how it reads the rest. Some batch files give ! ( ) a meaning.
_CHARACTERS_CMD_CHANGES = frozenset('%^&|<>"!()\r\n')


def register_mcp_server(
    environment: SetupEnvironment,
    mcp_url: str = ROBOTO_MCP_URL,
    tools: typing.Optional[collections.abc.Collection[AiTool]] = None,
    sign_in: bool = False,
) -> list[StepOutcome]:
    """Register the Roboto MCP server, under the name ``roboto``, with AI tools installed on the machine.

    Each tool is registered as follows:

    - Claude Code: runs ``claude mcp add`` at user scope, so the server is available in every project. A ``roboto``
      server Claude Code has only for one project, at local or project scope, doesn't count. Where ``claude`` is a
      batch file, as npm installs it on Windows, Windows runs it through cmd.exe, which would change an ``mcp_url``
      holding a character such as ``&`` or ``%``. Setup then adds nothing, and the outcome says how to install Claude
      Code's native ``claude.exe``. Where Claude Code's configuration directory exists but its ``claude`` command
      isn't on ``PATH``, the outcome gives the command to run.
    - Codex: appends a ``[mcp_servers.roboto]`` table to ``config.toml`` and leaves the rest of the file as it was.
      On Python 3.10, which has no TOML parser, setup writes only a missing or empty file; for any other it asks the
      user to add the entry by hand.
    - Cursor and VS Code: adds a ``roboto`` entry to the user's ``mcp.json``, which may be empty.
    - Claude Desktop: adds remote servers only through its own settings, so the outcome gives the steps.

    Configuration files are read as UTF-8, with or without the byte order mark some Windows editors save. A file that
    setup can't read, parse, add the entry to, or write is left unchanged, and the outcome is a failure that says what
    to add by hand.

    Setup never changes or removes a ``roboto`` entry a tool already has. It compares the entry's URL with
    ``mcp_url``, treating two URLs that differ only by a trailing slash as the same.
    An entry at another URL is reported as needing action, with the steps to point it at ``mcp_url``;
    for Codex, Cursor, and VS Code, so is an entry with no URL, such as a command-based server named ``roboto``.
    Claude Code shows a URL only for a remote server, so an entry it shows no URL for is reported as already done.
    How a matching entry is reported depends on whether the tool is signed in, as described below.

    Every tool is registered without an access token, and signs in to Roboto in the browser. Claude Code and Codex
    have a command for that, ``claude mcp login roboto`` and ``codex mcp login roboto``, and each reports whether it
    is signed in. When ``sign_in`` is true, setup runs the command, with the terminal handed over to it, for a server
    it has just added and for one the tool reports as not signed in, as after a sign-in that never finished;
    Ctrl-C during the sign-in stops that sign-in, not setup. When ``sign_in`` is false, or the sign-in doesn't finish,
    the outcome needs action and gives the command. A matching entry the tool reports as signed in is already done.
    Claude Code's report also covers its connection to the server: when it reports neither a connection
    nor a missing sign-in, as for a failed connection, setup starts no sign-in,
    and the outcome needs action and gives the status.

    Setup can't ask Cursor or VS Code whether they are signed in, since they sign in from inside the tool.
    It can't ask Codex either where Codex was found by its configuration directory alone,
    with no ``codex`` command to ask or to run.
    For these, a server setup has just added needs action, and the outcome says how to sign in.
    A matching entry already there gets an optional outcome that says how to sign in,
    without counting the sign-in as left to do.
    So does a matching entry in Codex when setup can't read Codex's report, and setup starts no sign-in for it.
    Claude Desktop's outcome is always optional too: setup can't see the servers added there,
    so it gives the steps, which include the sign-in.

    Args:
        environment: The machine to set up.
        mcp_url: Address of the Roboto MCP server.
        tools: The AI tools to register the server with; one that isn't installed is skipped. Defaults to every tool
            installed on the machine.
        sign_in: Whether to run the sign-in command of a tool that isn't signed in, which needs a person at the
            keyboard to finish it in the browser.

    Returns:
        One outcome for each installed tool in ``tools``, with the tool's name as its ``step``. When ``tools`` is
        ``None`` and no tool is installed, a single outcome saying so.
    """
    installed = environment.ai_tools
    if tools is None and not installed:
        return [
            StepOutcome(
                step="MCP server",
                status=StepStatus.ActionNeeded,
                summary="Found no supported AI tool (Claude Code, Claude Desktop, Codex, Cursor, or VS Code).",
                next_steps=(f"To connect another AI tool to Roboto, follow {MCP_DOCS_URL}.",),
            )
        ]

    outcomes: list[StepOutcome] = []
    for tool in installed:
        if tools is not None and tool not in tools:
            continue
        if tool is AiTool.ClaudeCode:
            outcomes.append(_register_with_claude_code(environment, mcp_url, sign_in))
        elif tool is AiTool.Codex:
            outcomes.append(_register_with_codex(environment, mcp_url, sign_in))
        elif tool is AiTool.Cursor:
            outcomes.append(
                _register_in_json_config(
                    tool=tool,
                    config_file=environment.cursor_dir / "mcp.json",
                    servers_key="mcpServers",
                    entry={"url": mcp_url},
                    mcp_url=mcp_url,
                    how_to_sign_in='open Cursor\'s MCP settings and click "Needs login" on the roboto server',
                )
            )
        elif tool is AiTool.VSCode:
            outcomes.append(
                _register_in_json_config(
                    tool=tool,
                    config_file=environment.vscode_user_dir / "mcp.json",
                    servers_key="servers",
                    entry={"type": "http", "url": mcp_url},
                    mcp_url=mcp_url,
                    how_to_sign_in="approve the roboto server when VS Code asks to authorize it",
                )
            )
        elif tool is AiTool.ClaudeDesktop:
            outcomes.append(
                StepOutcome(
                    step=tool.value,
                    # Setup can't see the servers Claude Desktop has, so it can't tell whether these steps are done.
                    # Reported as optional so that they aren't counted as left to do on every run.
                    status=StepStatus.Optional,
                    summary="Add Roboto in its settings, if you haven't.",
                    next_steps=(f"Customize > Connectors > + > Add custom connector, enter {mcp_url}, then sign in.",),
                )
            )
    return outcomes


def _register_with_claude_code(environment: SetupEnvironment, mcp_url: str, sign_in: bool) -> StepOutcome:
    step = AiTool.ClaudeCode.value
    add_command = f"claude mcp add --transport http --scope user {MCP_SERVER_NAME} {quote_for_shell(mcp_url)}"

    claude = environment.which("claude")
    if claude is None:
        return StepOutcome(
            step=step,
            status=StepStatus.ActionNeeded,
            summary="Couldn't find the `claude` command.",
            next_steps=(f"Add `claude` to your PATH and run `roboto setup` again, or run `{add_command}` yourself.",),
        )

    try:
        # `claude mcp get` reports the server a project sees, so a local- or project-scope server in the directory
        # setup runs from would hide a missing user-scope one. From an empty directory, it sees only the user scope.
        with tempfile.TemporaryDirectory(prefix="roboto-setup-") as empty_dir:
            existing = _run_claude(claude, environment, empty_dir, "mcp", "get", MCP_SERVER_NAME)
            if existing.returncode == 0:
                existing_url = _value_in_claude_mcp_get_output(existing.stdout, "URL")
                if existing_url is None:
                    # A server that runs a command. It has no sign-in for setup to check or start.
                    return _already_has_server(step)
                if not _same_url(existing_url, mcp_url):
                    return StepOutcome(
                        step=step,
                        status=StepStatus.ActionNeeded,
                        summary=f"Its roboto server is at {existing_url}, not {mcp_url}.",
                        next_steps=(
                            f"To replace it, run `{_removal_command_in_claude_mcp_get_output(existing.stdout)}`, then "
                            + "run `roboto setup` again.",
                        ),
                    )
                status = _status_in_claude_mcp_get_output(existing.stdout)
                # Claude Code reports `Connected · tools fetch failed` when it connected and signed in, then couldn't
                # list the server's tools.
                if status is not None and status.startswith("Connected"):
                    return _already_has_server(step)
                if status == "Needs authentication":
                    return _sign_in_with_command(
                        step,
                        [claude, "mcp", "login", MCP_SERVER_NAME],
                        environment,
                        empty_dir,
                        sign_in,
                        just_added=False,
                    )
                # No other status, such as a failed connection, asks for a sign-in, so none is started.
                return StepOutcome(
                    step=step,
                    status=StepStatus.ActionNeeded,
                    summary=f"Roboto MCP server status: {status or 'unknown'}.",
                    next_steps=(
                        f"To check the connection, run `claude mcp get {MCP_SERVER_NAME}`.",
                        "Once Claude Code connects, run `roboto setup` again.",
                    ),
                )

            if _is_batch_file(claude) and any(c in _CHARACTERS_CMD_CHANGES for c in mcp_url):
                return StepOutcome(
                    step=step,
                    status=StepStatus.ActionNeeded,
                    summary=f"Can't add {mcp_url} through {claude}, a batch file.",
                    next_steps=(
                        "In PowerShell, run `irm https://claude.ai/install.ps1 | iex` to install claude.exe, make "
                        + "sure `claude` runs it, then run `roboto setup` again.",
                    ),
                )

            added = _run_claude(
                claude,
                environment,
                empty_dir,
                "mcp",
                "add",
                "--transport",
                "http",
                "--scope",
                "user",
                MCP_SERVER_NAME,
                mcp_url,
            )
            if added.returncode != 0:
                reason = (added.stderr or added.stdout).strip() or f"exit status {added.returncode}"
                return _claude_code_failed(step, add_command, reason)

            return _sign_in_with_command(
                step,
                [claude, "mcp", "login", MCP_SERVER_NAME],
                environment,
                empty_dir,
                sign_in,
                just_added=True,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _claude_code_failed(step, add_command, str(exc))


def _sign_in_with_command(
    step: str,
    command: list[str],
    environment: SetupEnvironment,
    cwd: typing.Optional[str],
    sign_in: bool,
    just_added: bool,
) -> StepOutcome:
    """Sign a tool in to the Roboto MCP server by running ``command``, and report on the server and the sign-in.

    ``command`` is run only when ``sign_in`` is true, and takes over the terminal, since the tool prints an address
    to open and waits for the browser. ``just_added`` says whether setup has just added the server, for the summary.
    """
    tool_command = " ".join([pathlib.PurePath(command[0]).stem, *command[1:]])
    signed_in = False
    if sign_in:
        print(f"  Signing {step} in to the Roboto MCP server. Finish in your browser (Ctrl-C to skip).")
        # The tool writes straight to the terminal, so everything setup has printed so far has to reach it first.
        sys.stdout.flush()
        try:
            signed_in = subprocess.run(command, cwd=cwd, env=dict(environment.env)).returncode == 0  # noqa: S603
        except OSError:
            # The command couldn't be started. Reported below like a sign-in that didn't finish.
            pass
        except KeyboardInterrupt:
            # Ctrl-C reaches the tool as well, which stops its sign-in. The newline ends the line it left open.
            print()

    if signed_in:
        summary = "Added the Roboto MCP server and signed in." if just_added else "Signed in to the Roboto MCP server."
        return StepOutcome(step=step, status=StepStatus.Done, summary=summary)

    return StepOutcome(
        step=step,
        status=StepStatus.ActionNeeded,
        summary="Added the Roboto MCP server." if just_added else "Not signed in to the Roboto MCP server.",
        next_steps=(f"To sign in, run `{tool_command}`.",),
    )


def _run_claude(claude: str, environment: SetupEnvironment, cwd: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [claude, *args],
        capture_output=True,
        cwd=cwd,
        env=dict(environment.env),
        stdin=subprocess.DEVNULL,
        # `claude` writes UTF-8, including symbols such as ✘ that the locale's encoding on Windows may not decode. Any
        # byte that still fails to decode is replaced, so stray output can't stop setup with a UnicodeDecodeError.
        encoding="utf-8",
        errors="replace",
        timeout=CLAUDE_CLI_TIMEOUT_SECONDS,
    )


def _is_batch_file(program: str) -> bool:
    # Windows runs a .bat or .cmd file through cmd.exe. npm installs Claude Code on Windows as claude.cmd, which starts
    # claude.exe with the arguments cmd.exe hands it.
    return pathlib.PurePath(program).suffix.lower() in (".bat", ".cmd")


def _value_in_claude_mcp_get_output(output: str, label: str) -> typing.Optional[str]:
    # `claude mcp get` has no JSON output. It prints what it knows about a server on lines of the form
    # `  <label>: <value>`. A stdio server has no `URL` line.
    for line in output.splitlines():
        line_label, _, value = line.strip().partition(":")
        if line_label == label and value.strip():
            return value.strip()
    return None


def _status_in_claude_mcp_get_output(output: str) -> typing.Optional[str]:
    # `claude mcp get` connects to the server and prints the result on a line such as `  Status: ✔ Connected`.
    # The symbol in front depends on the terminal as well as the status, so only the words after it are returned.
    status = _value_in_claude_mcp_get_output(output, "Status")
    return None if status is None else re.sub(r"^\W+", "", status)


def _removal_command_in_claude_mcp_get_output(output: str) -> str:
    # The output ends with `To remove this server, run: claude mcp remove <name> -s <scope>`, which names the scope the
    # server is registered at. Without that scope, `claude mcp remove` can refuse a name registered at several.
    for line in output.splitlines():
        _, found, command = line.partition("To remove this server, run:")
        if found and command.strip():
            return command.strip()
    return f"claude mcp remove {MCP_SERVER_NAME}"


def _claude_code_failed(step: str, add_command: str, reason: str) -> StepOutcome:
    return StepOutcome(
        step=step,
        status=StepStatus.Failed,
        summary=f"Couldn't add the Roboto MCP server: {reason}",
        next_steps=(f"Run `{add_command}` yourself.",),
    )


def _same_url(existing_url: str, mcp_url: str) -> bool:
    return existing_url.removesuffix("/") == mcp_url.removesuffix("/")


def _already_has_server(step: str) -> StepOutcome:
    return StepOutcome(step=step, status=StepStatus.AlreadyDone, summary="Already has the Roboto MCP server.")


def _already_has_server_and_may_not_be_signed_in(step: str, how_to_sign_in: str) -> StepOutcome:
    # For a tool that has the server and that setup can't ask whether it is signed in. Reported as optional so that
    # the sign-in isn't counted as left to do on every run.
    return StepOutcome(
        step=step,
        status=StepStatus.Optional,
        summary="Already has the Roboto MCP server.",
        next_steps=(f"If you haven't signed in, {how_to_sign_in}.",),
    )


def _existing_entry_at_another_url(
    step: str, config_file: pathlib.Path, entry: typing.Any, mcp_url: str, entry_to_use: str
) -> typing.Optional[StepOutcome]:
    """Report on the ``roboto`` entry ``entry`` that ``config_file`` already has, when its URL isn't ``mcp_url``.

    Setup leaves such an entry unchanged, so the step needs action, and the next step shows ``entry_to_use``, the
    entry the user should end up with. Returns ``None`` when the entry's URL is ``mcp_url``.
    """
    existing_url = entry.get("url") if isinstance(entry, dict) else None
    if isinstance(existing_url, str) and _same_url(existing_url, mcp_url):
        return None

    what_it_has = f"is at {existing_url}" if isinstance(existing_url, str) else "has no URL"
    return StepOutcome(
        step=step,
        status=StepStatus.ActionNeeded,
        summary=f"The roboto server in {config_file} {what_it_has}.",
        next_steps=(f"Change it to:\n{entry_to_use}",),
    )


def _register_with_codex(environment: SetupEnvironment, mcp_url: str, sign_in: bool) -> StepOutcome:
    step = AiTool.Codex.value
    config_file = environment.codex_dir / "config.toml"
    codex = environment.which("codex")

    def sign_in_outcome(just_added: bool) -> StepOutcome:
        # Setup can't tell whether Codex is signed in where Codex was found by its configuration directory alone,
        # with no `codex` command to ask or to sign in with, or where it can't read Codex's report.
        # No sign-in is started then, and the outcome gives the command to run.
        if not just_added:
            signed_in = None if codex is None else _codex_is_signed_in(codex, environment)
            if signed_in is None:
                return _already_has_server_and_may_not_be_signed_in(step, f"run `codex mcp login {MCP_SERVER_NAME}`")
            if signed_in:
                return _already_has_server(step)
        return _sign_in_with_command(
            step,
            [codex or "codex", "mcp", "login", MCP_SERVER_NAME],
            environment,
            None,
            sign_in and codex is not None,
            just_added=just_added,
        )

    # json.dumps writes a quoted string whose escapes TOML also accepts, so a URL given with --mcp-url that holds
    # a quote, a backslash, or a control character still yields a valid TOML string. Its default ensure_ascii also
    # escapes DEL, which TOML requires and JSON doesn't.
    section = f"[mcp_servers.{MCP_SERVER_NAME}]\nurl = {json.dumps(mcp_url)}\n"

    def not_added(
        status: StepStatus,
        summary: str,
        next_step: str = f"Add the roboto server to it yourself:\n{section.rstrip()}",
    ) -> StepOutcome:
        # ``summary`` names the config file, which the next step refers to as "it".
        return StepOutcome(step=step, status=status, summary=summary, next_steps=(next_step,))

    try:
        existing = config_file.read_text(encoding="utf-8-sig") if config_file.exists() else ""
    except UnicodeDecodeError:
        return not_added(StepStatus.Failed, f"Couldn't read {config_file} as TOML.")
    except OSError as exc:
        return not_added(StepStatus.Failed, f"Couldn't read {config_file}: {exc}")

    # Append the section to the file's text, after a blank line, so the user's comments and formatting survive.
    if not existing or existing.endswith("\n\n"):
        separator = ""
    elif existing.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    updated = f"{existing}{separator}{section}"

    if sys.version_info < (3, 11):
        # Python 3.10 has no TOML parser, so setup can't tell whether a non-empty file already has a roboto server,
        # or whether the appended section would clash with how the file writes its mcp_servers table.
        if existing.strip():
            return not_added(
                StepStatus.ActionNeeded,
                f"Couldn't check {config_file} for a roboto server.",
                f"If it has none, add the roboto server to it yourself:\n{section.rstrip()}",
            )
    else:
        try:
            servers = tomllib.loads(existing).get("mcp_servers")
        except tomllib.TOMLDecodeError:
            return not_added(StepStatus.Failed, f"Couldn't read {config_file} as TOML.")

        if isinstance(servers, dict) and MCP_SERVER_NAME in servers:
            return _existing_entry_at_another_url(
                step, config_file, servers[MCP_SERVER_NAME], mcp_url, entry_to_use=section.rstrip()
            ) or sign_in_outcome(just_added=False)

        # Appending a [mcp_servers.roboto] section breaks the file when mcp_servers is written as an inline table
        # (`mcp_servers = { ... }`), and adds the server in the wrong place when mcp_servers is an array of tables.
        # Parsing the result catches both.
        try:
            added = tomllib.loads(updated).get("mcp_servers")
        except tomllib.TOMLDecodeError:
            added = None
        if not isinstance(added, dict) or added.get(MCP_SERVER_NAME) != {"url": mcp_url}:
            # Pasting the section into such a file by hand would fail the same way, so the next step gives only the
            # URL.
            return not_added(
                StepStatus.Failed,
                f"Couldn't add a [mcp_servers.{MCP_SERVER_NAME}] section to {config_file}.",
                f"Add a roboto server with url = {json.dumps(mcp_url)} to its mcp_servers yourself.",
            )

    try:
        write_file_atomically(config_file, updated)
    except OSError as exc:
        return not_added(StepStatus.Failed, f"Couldn't write {config_file}: {exc}")
    return sign_in_outcome(just_added=True)


def _codex_is_signed_in(codex: str, environment: SetupEnvironment) -> typing.Optional[bool]:
    # `codex mcp list --json` gives each server an "auth_status", which is "not_logged_in" for a server that wants a
    # sign-in. Returns None when setup can't read that for the roboto server: the command fails or times out, prints
    # something other than a JSON list, or, as an older Codex does, lists the server without the field.
    try:
        listed = subprocess.run(  # noqa: S603
            [codex, "mcp", "list", "--json"],
            capture_output=True,
            env=dict(environment.env),
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            errors="replace",
            timeout=CODEX_CLI_TIMEOUT_SECONDS,
        )
        servers = json.loads(listed.stdout) if listed.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    if not isinstance(servers, list):
        return None
    for server in servers:
        if isinstance(server, dict) and server.get("name") == MCP_SERVER_NAME:
            auth_status = server.get("auth_status")
            return auth_status != "not_logged_in" if isinstance(auth_status, str) else None
    return None


def _register_in_json_config(
    tool: AiTool,
    config_file: pathlib.Path,
    servers_key: str,
    entry: dict[str, str],
    mcp_url: str,
    how_to_sign_in: str,
) -> StepOutcome:
    step = tool.value
    manual_entry = json.dumps({servers_key: {MCP_SERVER_NAME: entry}}, indent=2, ensure_ascii=False)

    def not_added(summary: str) -> StepOutcome:
        # ``summary`` names the config file, which the next step refers to as "it".
        return StepOutcome(
            step=step,
            status=StepStatus.Failed,
            summary=summary,
            next_steps=(f"Add the roboto server to it yourself:\n{manual_entry}",),
        )

    config: typing.Any = {}
    try:
        if config_file.exists():
            text = config_file.read_text(encoding="utf-8-sig")
            # A blank file, like an empty config.toml for Codex, has no servers yet.
            config = json.loads(text) if text.strip() else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return not_added(f"Couldn't read {config_file} as JSON.")
    except OSError as exc:
        return not_added(f"Couldn't read {config_file}: {exc}")

    servers = config.get(servers_key, {}) if isinstance(config, dict) else None
    if not isinstance(servers, dict):
        # The file is JSON, but isn't an object, or holds something other than an object under ``servers_key``.
        return not_added(f'Couldn\'t find a "{servers_key}" object in {config_file}.')

    if MCP_SERVER_NAME in servers:
        return _existing_entry_at_another_url(
            step,
            config_file,
            servers[MCP_SERVER_NAME],
            mcp_url,
            entry_to_use=json.dumps({MCP_SERVER_NAME: entry}, indent=2, ensure_ascii=False),
        ) or _already_has_server_and_may_not_be_signed_in(step, how_to_sign_in)

    config[servers_key] = {**servers, MCP_SERVER_NAME: entry}
    try:
        write_file_atomically(config_file, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    except OSError as exc:
        return not_added(f"Couldn't write {config_file}: {exc}")
    return StepOutcome(
        step=step,
        status=StepStatus.ActionNeeded,
        summary="Added the Roboto MCP server.",
        next_steps=(f"To sign in, {how_to_sign_in}.",),
    )
