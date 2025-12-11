# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Workspace management utilities.

This module handles managing local workspace directory structure and lifecycle
for local action execution.
"""

import dataclasses
import pathlib
import shutil
import tempfile
import typing

from .action_resolution import ActionSource


@dataclasses.dataclass
class Workspace:
    """Workspace directory structure for local action execution.

    Manages all paths needed for local Docker-based action invocation,
    including input/output directories and runtime configuration.
    """

    root: pathlib.Path
    input_dir: pathlib.Path
    output_dir: pathlib.Path
    config_dir: pathlib.Path
    metadata_dir: pathlib.Path
    parameters_file: pathlib.Path
    secrets_file: pathlib.Path
    input_data_manifest_file: pathlib.Path
    dataset_metadata_changeset_file: pathlib.Path

    @classmethod
    def setup_within(cls, workspace_root: pathlib.Path) -> "Workspace":
        """Create and initialize workspace directory structure.

        Creates all necessary directories and files for local action execution:
        - input/ - for downloaded input data
        - output/ - for action output
        - .roboto/ - for runtime config

        Args:
            workspace_root: Path to workspace directory.

        Returns:
            Workspace instance with all paths configured.
        """
        # Clear existing contents to ensure a clean fs between local invocations.
        # (Hosted invocations always run in a clean room).
        if workspace_root.exists():
            for item in workspace_root.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

        input_dir = workspace_root / "input"
        output_dir = workspace_root / "output"
        config_dir = workspace_root / ".roboto"
        metadata_dir = output_dir / ".metadata"

        for dir_path in [
            input_dir,
            output_dir,
            config_dir,
            metadata_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)

        parameters_file = config_dir / "action_parameters.json"
        secrets_file = config_dir / "secrets.json"
        input_data_manifest_file = input_dir / "action_inputs_manifest.json"
        dataset_metadata_changeset_file = metadata_dir / "dataset_metadata_changeset.json"
        for file_path in [
            parameters_file,
            secrets_file,
            input_data_manifest_file,
            dataset_metadata_changeset_file,
        ]:
            file_path.touch(exist_ok=True)

        return cls(
            root=workspace_root,
            input_dir=input_dir,
            output_dir=output_dir,
            config_dir=config_dir,
            metadata_dir=metadata_dir,
            parameters_file=parameters_file,
            secrets_file=secrets_file,
            input_data_manifest_file=input_data_manifest_file,
            dataset_metadata_changeset_file=dataset_metadata_changeset_file,
        )


def resolve_workspace(
    action_source: ActionSource, workspace_dir_arg: typing.Optional[pathlib.Path]
) -> tuple[pathlib.Path, bool]:
    """Resolve workspace directory and whether it's temporary.

    Args:
        action_source: Source of the action
        workspace_dir_arg: Optional workspace directory from command-line

    Returns:
        Tuple of (workdir, is_temp) where is_temp indicates if cleanup is needed
    """
    if action_source.is_local:
        # Local action: use .workspace in action root
        assert action_source.action_root is not None
        workdir = action_source.action_root / ".workspace"
        return (workdir, False)

    # Platform action
    if workspace_dir_arg is not None:
        print(f"Using {workspace_dir_arg} as local workspace")
        return (workspace_dir_arg, False)

    # Create temporary workspace
    temp_workdir = pathlib.Path(tempfile.mkdtemp(prefix="roboto_local_invoke_"))
    print(f"Using {temp_workdir} as temporary local workspace")
    return (temp_workdir, True)
