# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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
    """Action that ``roboto actions invoke-local`` runs: one read from a local directory, or one fetched from Roboto.

    A local action sets ``action_config`` and ``action_root``; an action fetched from Roboto sets only
    ``action_record``. The properties read from whichever of the two is set.
    """

    action_config: typing.Optional[actions.ActionConfig] = None
    """Configuration read from the local directory's ``action.json``, or ``None`` for an action fetched from Roboto."""

    action_record: typing.Optional[actions.ActionRecord] = None
    """Record of the action fetched from Roboto, or ``None`` for a local action."""

    action_root: typing.Optional[pathlib.Path] = None
    """Local directory that holds ``action.json``, or ``None`` for an action fetched from Roboto."""

    @property
    def is_local(self) -> bool:
        """Whether the action was read from a local directory."""
        return self.action_root is not None

    @property
    def action_params(self) -> list[actions.ActionParameter]:
        """Parameters that an invocation of the action can give values for."""
        if self.action_config and self.action_config.release is not None:
            return self.action_config.release.parameters
        if self.action_config:
            return self.action_config.parameters
        elif self.action_record:
            return self.action_record.parameters
        return []

    @property
    def requires_downloaded_inputs(self) -> bool:
        """Whether the action's input files are downloaded before it runs. ``True`` when the action leaves it unset."""
        if self.action_config and self.action_config.release is not None:
            return self.action_config.release.requires_downloaded_inputs
        if self.action_config and self.action_config.requires_downloaded_inputs is not None:
            return self.action_config.requires_downloaded_inputs
        elif self.action_record and self.action_record.requires_downloaded_inputs is not None:
            return self.action_record.requires_downloaded_inputs
        return True

    @property
    def container_params(self) -> typing.Optional[actions.ContainerParameters]:
        """How to run the action's container image, or ``None`` when the action sets none."""
        if self.action_config and self.action_config.release is not None:
            config = self.action_config.release.substrate_config
            if not isinstance(config, actions.FargateSubstrateConfig):
                return None
            return actions.ContainerParameters(
                entry_point=config.entry_point, command=config.command, env_vars=config.env_vars, workdir=config.workdir
            )
        if self.action_config:
            return self.action_config.container_parameters
        elif self.action_record:
            return self.action_record.container_parameters
        return None


def find_action_root_dir(signal_file_name: str = "action.json") -> pathlib.Path:
    """Return the nearest directory, from the current directory upward, that contains ``signal_file_name``.

    The filesystem root itself is never searched.

    Args:
        signal_file_name: Name of the file that marks an action's directory.

    Raises:
        FileNotFoundError: Neither the current directory nor any parent below the filesystem root contains the file.
    """
    current_dir = pathlib.Path.cwd()
    while current_dir != current_dir.parent:
        signal_file = current_dir / signal_file_name
        if signal_file.exists():
            return current_dir
        current_dir = current_dir.parent

    raise FileNotFoundError(f"Could not find '{signal_file_name}' in current directory or any parent directory")


def _is_path(value: str) -> bool:
    """Return whether ``value`` names a local directory rather than an action reference.

    The checks, in order:

    1. ``.`` and ``..`` are paths.
    2. A value that starts with ``./``, ``../`` or ``/`` is a path.
    3. A value with a ``/`` elsewhere is a path only if it exists on disk, since ``<org>/<action>`` is also an action
       reference.
    4. Any other value is an action reference, even when a directory of that name exists.
    """
    if value in (".", ".."):
        return True
    if value.startswith(("./", "../", "/")):
        return True
    if "/" in value:
        return pathlib.Path(value).resolve().exists()
    return False


def _load_local_action_from_path(path: typing.Optional[str]) -> ActionSource:
    """Read the action configuration from ``action.json`` in a local directory, and print the directory.

    A ``path`` of ``None`` uses the nearest directory, from the current directory upward, that contains
    ``action.json``. Raises ``ActionRuntimeException`` when the directory has no ``action.json``, or when ``path`` is
    ``None`` and no directory from the current one upward has one. An ``action.json`` that does not match
    :py:class:`~roboto.domain.actions.ActionConfig` prints its first validation error and exits the process.
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
        # from None leaves the FileNotFoundError out of the traceback.
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
    """Fetch the record of the action that ``action_reference`` names from Roboto.

    ``action_reference`` takes the form ``<name>`` or ``<org_id>/<name>``, either optionally followed by ``@<digest>``
    to pin one version. ``org_id`` owns the action when the reference names no organization, and ``None`` uses the
    organization the caller acts in. Raises ``RobotoNotFoundException`` when the organization has no action with this
    name, or the action has no version with this digest.
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
    """Read the action ``roboto actions invoke-local`` runs from a local directory, or fetch it from Roboto.

    A value that is ``.`` or ``..``, starts with ``./``, ``../`` or ``/``, or contains a ``/`` and exists on disk is a
    local directory; any other value is a reference to an action in Roboto. An ``action.json`` that does not match
    :py:class:`~roboto.domain.actions.ActionConfig` prints its first validation error and exits the process.

    Args:
        action_or_path: Local directory that holds ``action.json``, or a reference to an action in Roboto, as
            ``<name>``, ``<org_id>/<name>``, or either followed by ``@<digest>``. ``None`` uses the nearest directory,
            from the current directory upward, that contains ``action.json``.
        args: Parsed command-line arguments. The ``--org`` organization owns a fetched action when the reference
            names none.

    Raises:
        ActionRuntimeException: The local directory has no ``action.json``.
        RobotoNotFoundException: No action in Roboto matches the reference.
    """
    if action_or_path is None or _is_path(action_or_path):
        return _load_local_action_from_path(action_or_path)
    else:
        return _fetch_platform_action(action_or_path, args.org, context)
