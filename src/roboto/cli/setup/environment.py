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
    """An AI tool ``roboto setup`` can connect to Roboto.

    Each value is the tool's name as shown to the user, and setup lists the tools in the order they are declared here.
    """

    ClaudeCode = "Claude Code"
    Codex = "Codex"
    Cursor = "Cursor"
    VSCode = "VS Code"
    ClaudeDesktop = "Claude Desktop"


@dataclasses.dataclass(frozen=True)
class SetupEnvironment:
    """The user's machine as ``roboto setup`` sees it: home directory, environment variables, and platform.

    Setup finds each AI tool's configuration directory and command line program from these values alone, so a test can
    point it at a temporary home directory without touching the real one.
    """

    home: pathlib.Path
    """The user's home directory."""

    env: collections.abc.Mapping[str, str]
    """Environment variables, including ``PATH`` for finding AI tools' command line programs."""

    platform: str
    """The value of :py:data:`sys.platform` on the machine, e.g. ``linux``, ``darwin``, or ``win32``."""

    @classmethod
    def current(cls) -> SetupEnvironment:
        """Describe the machine this process is running on."""
        return cls(home=pathlib.Path.home(), env=dict(os.environ), platform=sys.platform)

    @property
    def agent_skills_dir(self) -> pathlib.Path:
        """Shared user skills directory, ``~/.agents/skills``.

        Codex, Cursor, and VS Code read skills from it, and the ``skills`` command line tool (skills.sh) keeps its
        copies of global skills there.
        """
        return self.home / ".agents" / "skills"

    @property
    def ai_tools(self) -> list[AiTool]:
        """The AI tools installed on the machine, in the order setup lists them.

        Claude Code and Codex count when their configuration directory exists or their command is on ``PATH``; Cursor,
        VS Code, and Claude Desktop when their configuration directory exists.
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
        """The directory Claude Code reads the user's skills from, ``skills`` in its configuration directory."""
        return self.claude_code_dir / "skills"

    @property
    def claude_desktop_dir(self) -> typing.Optional[pathlib.Path]:
        """Claude Desktop's configuration directory, or ``None`` on platforms Claude Desktop doesn't support."""
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
        """The ``~/.cursor`` directory, where Cursor reads its global ``mcp.json`` and user skills."""
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
        """Return the path of ``program`` on this environment's ``PATH``, or ``None`` if it isn't there."""
        return shutil.which(program, path=self.env.get("PATH", ""))

    def __env_dir(self, name: str, default: pathlib.Path) -> pathlib.Path:
        """The directory named by environment variable ``name``, or ``default`` when it is unset or blank."""
        value = self.env.get(name, "").strip()
        return pathlib.Path(value) if value else default

    def __windows_app_data_dir(self) -> pathlib.Path:
        return self.__env_dir("APPDATA", default=self.home / "AppData" / "Roaming")
