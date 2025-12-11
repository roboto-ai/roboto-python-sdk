# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Action source resolution utilities.

This module handles determining where actions come from (local filesystem vs platform)
and loading action metadata and configuration.
"""

import argparse
import dataclasses
import pathlib
import typing

from ....action_runtime.exceptions import (
    ActionRuntimeException,
)
from ....domain import actions
from ...common_args import (
    parse_action_reference_string,
)
from ...context import CLIContext
from ...validation import (
    pydantic_validation_handler,
)


@dataclasses.dataclass
class ActionSource:
    """Encapsulates where an action comes from and provides convenient access to action properties.

    Either action_config (local action) or action_record (platform action) should be set, not both.
    """

    action_config: typing.Optional[actions.ActionConfig] = None
    action_record: typing.Optional[actions.ActionRecord] = None
    action_root: typing.Optional[pathlib.Path] = None

    @property
    def is_local(self) -> bool:
        """Returns True when action_root is not None (local action)."""
        return self.action_root is not None

    @property
    def action_params(self) -> list[actions.ActionParameter]:
        """Returns parameters from config or record."""
        if self.action_config:
            return self.action_config.parameters
        elif self.action_record:
            return self.action_record.parameters
        return []

    @property
    def requires_downloaded_inputs(self) -> bool:
        """Returns flag from config or record."""
        if self.action_config and self.action_config.requires_downloaded_inputs is not None:
            return self.action_config.requires_downloaded_inputs
        elif self.action_record and self.action_record.requires_downloaded_inputs is not None:
            return self.action_record.requires_downloaded_inputs
        return True

    @property
    def container_params(self) -> typing.Optional[actions.ContainerParameters]:
        """Returns container parameters from config or record."""
        if self.action_config:
            return self.action_config.container_parameters
        elif self.action_record:
            return self.action_record.container_parameters
        return None


def find_action_root_dir(signal_file_name: str = "action.json") -> pathlib.Path:
    """Walk filesystem upward from current directory to find action root.

    Searches for a directory containing the signal file (default: action.json).
    Stops at filesystem root to avoid infinite loop.

    Args:
        signal_file_name: Name of file to search for (default: "action.json")

    Returns:
        Path to directory containing the signal file.

    Raises:
        FileNotFoundError: If signal file is not found in any parent directory.
    """
    current_dir = pathlib.Path.cwd()
    while current_dir != current_dir.parent:
        signal_file = current_dir / signal_file_name
        if signal_file.exists():
            return current_dir
        current_dir = current_dir.parent

    raise FileNotFoundError(f"Could not find '{signal_file_name}' in current directory or any parent directory")


def _is_path(value: str) -> bool:
    """Determine if string is a file path vs action reference.

    Heuristics:
    - Starts with ./ or ../ or / → path
    - Is exactly "." or ".." → path
    - Contains / but not at start → could be org/action, check if path exists
    - Otherwise → action reference

    Args:
        value: String to evaluate

    Returns:
        True if value appears to be a path, False if action reference
    """
    if value in (".", ".."):
        return True
    if value.startswith(("./", "../", "/")):
        return True
    if "/" in value:
        # Could be org/action reference
        # Check if it exists as a path
        return pathlib.Path(value).resolve().exists()
    return False


def _load_local_action_from_path(path: typing.Optional[str]) -> ActionSource:
    """Load action from local filesystem path.

    Args:
        path: Path to action directory, or None to use current directory

    Returns:
        ActionSource with action_config and action_root set

    Raises:
        ActionRuntimeException: If action.json cannot be found in the specified directory
    """
    try:
        action_root = pathlib.Path.cwd()
        if path is None:
            action_root = find_action_root_dir()
        else:
            action_root = pathlib.Path(path).resolve()

        print(f"Action root: {action_root}")

        action_config_path = action_root / "action.json"
        with pydantic_validation_handler("action.json"):
            action_config = actions.ActionConfig.from_file(action_config_path)
    except FileNotFoundError:
        # Re-raise with no stack trace
        raise ActionRuntimeException(
            f"Could not find action.json in {action_root}. "
            "To invoke an action from a local directory, it must contain an action.json file. "
            "Provide a path to a local action directory "
            "or an action reference to fetch the action definition from the platform."
        ) from None

    return ActionSource(
        action_config=action_config,
        action_record=None,
        action_root=action_root,
    )


def _fetch_platform_action(action_reference: str, org_id: typing.Optional[str], context: CLIContext) -> ActionSource:
    """Fetch action from Roboto platform.

    Args:
        action_reference: Action reference string (e.g., "my-action", "org/my-action")
        org_id: Optional organization ID
        context: CLI context with roboto_client

    Returns:
        ActionSource with action_record set
    """
    action_ref = parse_action_reference_string(action_reference)
    owner_org_id = action_ref.owner if action_ref.owner else org_id

    action_record = actions.Action.from_name(
        name=action_ref.name,
        digest=action_ref.digest,
        owner_org_id=owner_org_id,
        roboto_client=context.roboto_client,
    ).record

    print("Fetching action from platform")

    return ActionSource(
        action_config=None,
        action_record=action_record,
        action_root=None,
    )


def resolve_action_source(
    action_or_path: typing.Optional[str], args: argparse.Namespace, context: CLIContext
) -> ActionSource:
    """Resolve action source from command-line arguments.

    Args:
        action_or_path: Optional positional argument (path or action reference)
        args: Parsed command-line arguments
        context: CLI context

    Returns:
        ActionSource indicating where the action comes from
    """
    if action_or_path is None or _is_path(action_or_path):
        return _load_local_action_from_path(action_or_path)
    else:
        return _fetch_platform_action(action_or_path, args.org, context)
