# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import dataclasses
import io
import os
import pathlib
import re
import shutil
import tarfile
import typing
import zlib

from ..outcome import StepOutcome, StepStatus
from .environment import AiTool, SetupEnvironment
from .files import download_file

AGENT_SKILLS_ARCHIVE_URL = "https://github.com/roboto-ai/agent-skills/archive/refs/heads/main.tar.gz"
AGENT_SKILLS_REPO_URL = "https://github.com/roboto-ai/agent-skills"

# The AI tools setup installs skills for. Claude Desktop reads none of the directories setup writes.
SKILL_READERS = (AiTool.ClaudeCode, AiTool.Codex, AiTool.Cursor, AiTool.VSCode)

_SKILL_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")

# Setup writes this file into every skill directory it installs, so a later run can tell the skills it installed
# from the ones the user installed some other way. Setup removes only the skills it installed when Roboto stops
# publishing them, and ``roboto upgrade`` updates skills only on a machine where setup installed some.
_INSTALLED_BY_SETUP_FILE_NAME = ".installed-by-roboto-setup"
_INSTALLED_BY_SETUP_FILE_CONTENTS = (
    f"roboto setup installed this skill from {AGENT_SKILLS_REPO_URL}, "
    + "and removes it when Roboto stops publishing it.\n"
)

# Matches a path part that isn't an ordinary file or directory name on every platform setup runs on, one that:
# 1. contains a control character, or a character Windows reads as a separator, a drive, or a wildcard;
# 2. ends in a dot or space, which Windows drops when it opens the path, so ".. " opens as "..";
#    this also matches "." and "..";
# 3. is a name Windows reserves for a device, such as NUL or COM1, with or without an extension.
_UNSAFE_PATH_PART = re.compile(
    r'[<>:"/\\|?*\x00-\x1f]|[. ]\Z|^(con|prn|aux|nul|conin\$|conout\$|com[0-9]|lpt[0-9]) *(\..*)?\Z',
    re.IGNORECASE,
)


class AgentSkillsArchiveError(Exception):
    """The agent skills archive holds no skills, or isn't a gzipped tar archive."""


def set_up_agent_skills(
    environment: SetupEnvironment, tools: typing.Optional[collections.abc.Collection[AiTool]] = None
) -> StepOutcome:
    """Download Roboto's agent skills from GitHub and install them as :func:`install_agent_skills` describes.

    Any error, from the network, a bad archive, or the file system, is reported as a failed step so the remaining
    steps of setup still run.

    Args:
        environment: The machine to set up.
        tools: The AI tools to install the skills for. Defaults to every tool installed on the machine.

    Returns:
        What was installed, and for which AI tools, or why the skills couldn't be installed.
    """
    try:
        archive = download_file(AGENT_SKILLS_ARCHIVE_URL)
    except Exception as exc:
        return StepOutcome(
            step="Agent skills",
            status=StepStatus.Failed,
            summary=f"Couldn't download them from GitHub: {exc}",
            next_steps=("Check your network connection, then try again.",),
        )

    try:
        return install_agent_skills(environment, archive, tools)
    except PermissionError as exc:
        # Raised for a folder the user can't write to, and on Windows also for a skill folder another program is using,
        # since Windows won't rename or delete that folder.
        return StepOutcome(
            step="Agent skills",
            status=StepStatus.Failed,
            summary=f"Couldn't install them: {exc}",
            next_steps=("Make sure you can write to that path and that no other program is using it, then try again.",),
        )
    except Exception as exc:
        return StepOutcome(
            step="Agent skills",
            status=StepStatus.Failed,
            summary=f"Couldn't install them: {exc}",
            next_steps=(f"Install them yourself from {AGENT_SKILLS_REPO_URL}.",),
        )


def update_agent_skills(environment: SetupEnvironment) -> typing.Optional[StepOutcome]:
    """Update Roboto's agent skills, and remove any Roboto no longer publishes, where ``roboto setup`` installed them.

    Where setup never installed them, nothing is installed: the user didn't ask for skills there. Likewise, Claude
    Code gets the skills only where it already has one that setup installed, so a user who left Claude Code out of
    setup isn't given them by an upgrade.

    Args:
        environment: The machine to update.

    Returns:
        What was updated, as :func:`set_up_agent_skills` reports it, or ``None`` when setup never installed skills.
    """
    shared_copies = _skills_installed_by_setup(environment.agent_skills_dir)
    if not shared_copies:
        return None
    claude_code_has_them = any(
        _is_claude_code_copy(environment.claude_code_skills_dir / shared_copy.name, shared_copy)
        for shared_copy in shared_copies
    )
    tools = [tool for tool in environment.ai_tools if tool is not AiTool.ClaudeCode or claude_code_has_them]
    return set_up_agent_skills(environment, tools)


def install_agent_skills(
    environment: SetupEnvironment,
    archive: bytes,
    tools: typing.Optional[collections.abc.Collection[AiTool]] = None,
) -> StepOutcome:
    """Install every skill in the ``roboto-ai/agent-skills`` archive for the AI tools in ``tools`` that read skills.

    Each skill is written to the shared skills directory (``~/.agents/skills``), replacing any earlier copy of the same
    skill. Codex, Cursor, and VS Code read skills from that directory, whether or not they are in ``tools``, and the
    ``skills`` command line tool (skills.sh) keeps its copies there too. Claude Code reads only its own skills
    directory, so when Claude Code is in ``tools`` each skill gets a link there, or a copy where the platform doesn't
    allow links. Where Claude Code's skills directory is itself a link to the shared one, the skills there are already
    Claude Code's, and nothing more is linked.

    Running setup again updates Roboto's skills, and removes each skill an earlier run installed that the archive no
    longer holds, from the shared skills directory and from Claude Code's. Skills with other names that setup didn't
    install are never touched.

    Only regular files are installed. Links and device files are skipped, and so is any file whose path isn't made of
    ordinary file and directory names on every platform: one that could lead out of its skill's directory, or that
    Windows would open as a device.

    Args:
        environment: The machine to set up.
        archive: A gzipped tar archive of the repository, as GitHub serves it: one top-level directory holding a
            ``skills/<skill name>/`` directory per skill.
        tools: The AI tools to install the skills for. Defaults to every tool installed on the machine.

    Returns:
        What was installed, and for which AI tools, and which skills were removed.

    Raises:
        AgentSkillsArchiveError: ``archive`` isn't a gzipped tar archive, or holds no skills.
        OSError: A skill couldn't be written to, or removed from, one of the skills directories. Each skill written
            there is left whole, holding either the copy this run wrote or the last complete copy from before the run,
            if there was one.
    """
    skills = _read_skills(archive)
    # Told apart so the summary can say which skills were updated rather than installed.
    installed_before = {
        skill.name
        for skill in skills
        if (environment.agent_skills_dir / skill.name / _INSTALLED_BY_SETUP_FILE_NAME).is_file()
    }

    for skill in skills:
        _replace_directory(environment.agent_skills_dir / skill.name, skill)

    installed_tools = environment.ai_tools
    readers = [tool for tool in installed_tools if tool in SKILL_READERS and (tools is None or tool in tools)]
    if AiTool.ClaudeCode in readers:
        for skill in skills:
            _link_directory(
                environment.claude_code_skills_dir / skill.name, environment.agent_skills_dir / skill.name, skill
            )

    # Only after every current skill is in place, so a run that fails partway through never removes anything.
    removed = _remove_unpublished_skills(environment, {skill.name for skill in skills})
    removal_note = f" Removed {', '.join(removed)}, which Roboto no longer publishes." if removed else ""

    changes = _describe_changes(
        installed=[skill.name for skill in skills if skill.name not in installed_before],
        updated=[skill.name for skill in skills if skill.name in installed_before],
    )
    if not readers:
        return StepOutcome(
            step="Agent skills",
            status=StepStatus.ActionNeeded,
            summary=f"{changes} in {environment.agent_skills_dir}. Found no AI tool that reads skills from there."
            + removal_note,
            next_steps=(
                f"To install them for an AI tool that reads skills elsewhere, follow {AGENT_SKILLS_REPO_URL}.",
            ),
        )

    # Every tool setup installs skills for, apart from Claude Code, reads them from the shared skills directory, so
    # leaving one out of ``tools`` doesn't keep the skills from it.
    also_reading = [
        tool.value
        for tool in installed_tools
        if tool in SKILL_READERS and tool is not AiTool.ClaudeCode and tool not in readers
    ]
    also_reading_note = (
        f" Also read by {', '.join(also_reading)}, from {environment.agent_skills_dir}." if also_reading else ""
    )

    return StepOutcome(
        step="Agent skills",
        status=StepStatus.Done,
        summary=f"{changes} for {', '.join(tool.value for tool in readers)}." + also_reading_note + removal_note,
        next_steps=("Restart your AI tools to load them.",),
    )


def _describe_changes(installed: list[str], updated: list[str]) -> str:
    # For example "Installed new-skill and updated roboto-guide".
    parts = []
    if installed:
        parts.append(f"installed {', '.join(installed)}")
    if updated:
        parts.append(f"updated {', '.join(updated)}")
    sentence = " and ".join(parts)
    return sentence[:1].upper() + sentence[1:]


@dataclasses.dataclass(frozen=True)
class _SkillFile:
    relative_path: pathlib.PurePosixPath
    contents: bytes
    executable: bool


@dataclasses.dataclass(frozen=True)
class _Skill:
    name: str
    files: tuple[_SkillFile, ...]


def _read_skills(archive: bytes) -> list[_Skill]:
    files_by_skill: dict[str, list[_SkillFile]] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            for member in tar.getmembers():
                # Only regular files are read, so no link or device file is ever created. Each is written by its
                # path under skills/<name>/, and only when every part of that path is an ordinary name, so nothing
                # in the archive can place a file outside its skill's directory.
                if not member.isfile():
                    continue
                parts = pathlib.PurePosixPath(member.name).parts
                if len(parts) < 4 or parts[1] != "skills" or not _SKILL_NAME.fullmatch(parts[2]):
                    continue
                if any(_UNSAFE_PATH_PART.search(part) for part in parts[2:]):
                    continue
                extracted = tar.extractfile(member)
                if extracted is None:
                    continue
                files_by_skill.setdefault(parts[2], []).append(
                    _SkillFile(
                        relative_path=pathlib.PurePosixPath(*parts[3:]),
                        contents=extracted.read(),
                        executable=bool(member.mode & 0o100),
                    )
                )
    # Data that isn't a gzipped tar archive raises TarError. A truncated download raises EOFError, and a corrupted
    # one zlib.error, or OSError when its checksum fails.
    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:
        raise AgentSkillsArchiveError(f"The download isn't a readable archive: {exc}") from None

    skills = [
        _Skill(name=name, files=tuple(files))
        for name, files in sorted(files_by_skill.items())
        if any(f.relative_path == pathlib.PurePosixPath("SKILL.md") for f in files)
    ]
    if not skills:
        raise AgentSkillsArchiveError("The download holds no skills.")
    return skills


def _replace_directory(target: pathlib.Path, skill: _Skill) -> None:
    _put_in_place(target, lambda staging: _write_skill(staging, skill))


def _link_directory(link: pathlib.Path, shared_copy: pathlib.Path, skill: _Skill) -> None:
    # True when an earlier run made ``link``, and also when Claude Code's skills directory is itself a link to the
    # shared one, where replacing ``link`` would delete the skill just installed.
    if link.resolve() == shared_copy.resolve():
        return
    _put_in_place(link, lambda staging: _link_or_copy(staging, shared_copy, skill))


def _link_or_copy(path: pathlib.Path, shared_copy: pathlib.Path, skill: _Skill) -> None:
    try:
        path.symlink_to(shared_copy, target_is_directory=True)
    except OSError:
        # Windows allows symbolic links only in Developer Mode or with administrator rights.
        _write_skill(path, skill)


def _write_skill(directory: pathlib.Path, skill: _Skill) -> None:
    for skill_file in skill.files:
        path = directory.joinpath(*skill_file.relative_path.parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(skill_file.contents)
        if skill_file.executable:
            # Whoever the user's umask lets read the file may also run it.
            mode = path.stat().st_mode
            path.chmod(mode | ((mode & 0o444) >> 2))
    # Written after the skill's own files, so it replaces any file of the same name in the archive.
    directory.joinpath(_INSTALLED_BY_SETUP_FILE_NAME).write_text(_INSTALLED_BY_SETUP_FILE_CONTENTS)


def _put_in_place(target: pathlib.Path, build: typing.Callable[[pathlib.Path], None]) -> None:
    """Replace ``target`` with what ``build`` makes beside it, so no failure leaves ``target`` half replaced.

    If ``build`` or the swap fails, ``target`` stays as it was. That covers an old copy that Windows won't rename or
    delete because a program has one of its files open.
    """
    staging = target.with_name(f".{target.name}.tmp")
    retired = target.with_name(f".{target.name}.old")
    # A run killed between the two renames below leaves the old copy only at ``retired``. It moves back to ``target``
    # before the leftovers are removed, so a copy stays in place even if this run fails too.
    if os.path.lexists(retired) and not os.path.lexists(target):
        os.replace(retired, target)
    # A run that was killed partway through can leave either one behind, holding a SKILL.md an AI tool could load.
    _remove(staging)
    _remove(retired)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        build(staging)

        # Renaming can't replace a directory that isn't empty, so the old copy moves aside first. The new copy is
        # already complete, so an AI tool reading the skill finds the old copy or the new one, except in the instant
        # between the two renames.
        had_previous_copy = target.is_symlink() or target.exists()
        if had_previous_copy:
            os.replace(target, retired)
        try:
            os.replace(staging, target)
        except BaseException:
            # Includes Ctrl-C arriving between the two renames, which would otherwise leave no copy in place.
            if had_previous_copy:
                os.replace(retired, target)
            raise
        _remove(retired)
    finally:
        _remove(staging)


def _remove_unpublished_skills(environment: SetupEnvironment, published: set[str]) -> list[str]:
    removed: list[str] = []
    for shared_copy in _skills_installed_by_setup(environment.agent_skills_dir):
        if shared_copy.name in published:
            continue
        # Removed while the shared copy still exists, so a link to it can still be recognized by where it leads.
        _remove_claude_code_copy(environment.claude_code_skills_dir / shared_copy.name, shared_copy)
        _remove_installed_skill(shared_copy)
        removed.append(shared_copy.name)
    return removed


def _skills_installed_by_setup(skills_dir: pathlib.Path) -> list[pathlib.Path]:
    if not skills_dir.is_dir():
        return []
    # The name pattern skips dot-directories, such as the .<name>.tmp a killed run leaves behind.
    return sorted(
        skill for skill in skills_dir.iterdir() if _SKILL_NAME.fullmatch(skill.name) and _is_installed_by_setup(skill)
    )


def _is_installed_by_setup(directory: pathlib.Path) -> bool:
    # A link never counts, even one leading to a directory setup installed, so removing a skill never deletes files
    # through a link.
    return not directory.is_symlink() and (directory / _INSTALLED_BY_SETUP_FILE_NAME).is_file()


def _remove_installed_skill(directory: pathlib.Path) -> None:
    # SKILL.md goes first, so AI tools stop loading the skill at once, and the marker last, so a run stopped partway
    # through leaves a marked directory that the next run removes.
    (directory / "SKILL.md").unlink(missing_ok=True)
    for child in directory.iterdir():
        if child.name != _INSTALLED_BY_SETUP_FILE_NAME:
            _remove(child)
    shutil.rmtree(directory)


def _is_claude_code_copy(claude_code_copy: pathlib.Path, shared_copy: pathlib.Path) -> bool:
    # Either a link to the shared copy, or the copy setup makes where the platform doesn't allow links.
    return claude_code_copy.resolve() == shared_copy.resolve() or _is_installed_by_setup(claude_code_copy)


def _remove_claude_code_copy(claude_code_copy: pathlib.Path, shared_copy: pathlib.Path) -> None:
    if claude_code_copy.resolve() == shared_copy.resolve():
        # Either a link to the shared copy, made by setup or by the user, which would be left pointing nowhere; or
        # the shared copy itself, reached through a Claude Code skills directory that links to the shared one, which
        # the caller removes.
        if claude_code_copy.is_symlink():
            claude_code_copy.unlink()
    elif _is_installed_by_setup(claude_code_copy):
        # The copy setup makes where the platform doesn't allow links.
        _remove_installed_skill(claude_code_copy)


def _remove(path: pathlib.Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
