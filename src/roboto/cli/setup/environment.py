# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import enum
import os
import pathlib
import shutil
import sys
import typing


class AiTool(enum.Enum):
    """AI tool that ``roboto setup`` can connect to Roboto.

    Each member's value is the tool's name as setup shows it, and setup lists the tools in the order they are declared.
    """

    ClaudeCode = "Claude Code"
    Codex = "Codex"
    Cursor = "Cursor"
    VSCode = "VS Code"
    ClaudeDesktop = "Claude Desktop"


@dataclasses.dataclass(frozen=True)
class SetupEnvironment:
    """Home directory, environment variables, and platform of the machine ``roboto setup`` runs on.

    Setup finds each AI tool's configuration directory and command line program from these values alone, so a test can
    point it at a temporary home directory without touching the real one.
    """

    home: pathlib.Path
    """User's home directory."""

    env: collections.abc.Mapping[str, str]
    """Environment variables setup reads and passes to the programs it runs, including the ``PATH`` it searches."""

    platform: str
    """Value of ``sys.platform`` on the machine, such as ``"linux"``, ``"darwin"``, or ``"win32"``."""

    @classmethod
    def current(cls) -> SetupEnvironment:
        """Return the environment of the machine this process runs on."""
        return cls(home=pathlib.Path.home(), env=dict(os.environ), platform=sys.platform)

    @property
    def agent_skills_dir(self) -> pathlib.Path:
        """Skills directory that several AI tools share, ``~/.agents/skills``.

        Codex, Cursor, and VS Code read skills from it, and the ``skills`` command line tool (skills.sh) keeps its
        copies of global skills there.
        """
        return self.home / ".agents" / "skills"

    @property
    def ai_tools(self) -> list[AiTool]:
        """AI tools installed on the machine, in the order ``AiTool`` declares them.

        Claude Code and Codex count as installed when their configuration directory exists or their command is on
        ``PATH``; Cursor, VS Code, and Claude Desktop when their configuration directory exists.
        """
        claude_desktop_dir = self.claude_desktop_dir
        installed = {
            AiTool.ClaudeCode: self.claude_code_dir.is_dir() or self.which("claude") is not None,
            AiTool.Codex: self.codex_dir.is_dir() or self.which("codex") is not None,
            AiTool.Cursor: self.cursor_dir.is_dir(),
            AiTool.VSCode: self.vscode_user_dir.is_dir(),
            AiTool.ClaudeDesktop: claude_desktop_dir is not None and claude_desktop_dir.is_dir(),
        }
        return [tool for tool in AiTool if installed[tool]]

    @property
    def claude_code_dir(self) -> pathlib.Path:
        """Claude Code's user configuration directory: ``CLAUDE_CONFIG_DIR`` when set, otherwise ``~/.claude``."""
        return self.__env_dir("CLAUDE_CONFIG_DIR", default=self.home / ".claude")

    @property
    def claude_code_skills_dir(self) -> pathlib.Path:
        """Directory Claude Code reads the user's skills from, ``skills`` inside ``claude_code_dir``."""
        return self.claude_code_dir / "skills"

    @property
    def claude_desktop_dir(self) -> typing.Optional[pathlib.Path]:
        """Claude Desktop's configuration directory, or ``None`` on platforms other than macOS and Windows."""
        if self.platform == "darwin":
            return self.home / "Library" / "Application Support" / "Claude"
        if self.platform == "win32":
            return self.__windows_app_data_dir() / "Claude"
        return None

    @property
    def codex_dir(self) -> pathlib.Path:
        """Codex's configuration directory: ``CODEX_HOME`` when set, otherwise ``~/.codex``."""
        return self.__env_dir("CODEX_HOME", default=self.home / ".codex")

    @property
    def cursor_dir(self) -> pathlib.Path:
        """Cursor's user directory, ``~/.cursor``, which holds its global ``mcp.json`` and the user's skills."""
        return self.home / ".cursor"

    @property
    def vscode_user_dir(self) -> pathlib.Path:
        """VS Code's user settings directory, which holds the default profile's ``mcp.json``."""
        if self.platform == "darwin":
            return self.home / "Library" / "Application Support" / "Code" / "User"
        if self.platform == "win32":
            return self.__windows_app_data_dir() / "Code" / "User"
        return self.__env_dir("XDG_CONFIG_HOME", default=self.home / ".config") / "Code" / "User"

    def which(self, program: str) -> typing.Optional[str]:
        """Return the path of ``program`` on ``env``'s ``PATH``, or ``None`` if it is not there or ``PATH`` is unset."""
        return shutil.which(program, path=self.env.get("PATH", ""))

    def __env_dir(self, name: str, default: pathlib.Path) -> pathlib.Path:
        """Return the directory environment variable ``name`` holds, or ``default`` when it is unset or blank."""
        value = self.env.get(name, "").strip()
        return pathlib.Path(value) if value else default

    def __windows_app_data_dir(self) -> pathlib.Path:
        return self.__env_dir("APPDATA", default=self.home / "AppData" / "Roaming")
