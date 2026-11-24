# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import dataclasses
import pathlib
import shutil
import tempfile
import typing

from .action_resolution import ActionSource


@dataclasses.dataclass
class Workspace:
    """Directory layout of a ``roboto actions invoke-local`` workspace.

    The action's container mounts ``root`` at the same path and receives most of the other paths in environment
    variables, each named on its field. Build one with ``setup_within``.
    """

    root: pathlib.Path
    """Workspace directory, which is also the container's ``HOME``."""

    input_dir: pathlib.Path
    """``<root>/input``: directory the invocation's input files are placed in, passed as ``ROBOTO_INPUT_DIR``."""

    output_dir: pathlib.Path
    """``<root>/output``: directory for the action's output files, passed as ``ROBOTO_OUTPUT_DIR``."""

    config_dir: pathlib.Path
    """``<root>/.roboto``: directory of the invocation's runtime configuration.

    Passed as ``ROBOTO_ACTION_RUNTIME_CONFIG_DIR``.
    """

    metadata_dir: pathlib.Path
    """``<root>/output/.metadata``: directory that holds ``dataset_metadata_changeset_file``."""

    parameters_file: pathlib.Path
    """``<root>/.roboto/action_parameters.json``: the invocation's parameter values.

    Passed as ``ROBOTO_ACTION_PARAMETERS_FILE``.
    """

    secrets_file: pathlib.Path
    """``<root>/.roboto/secrets.json``: values of the secrets the parameters name. Deleted when the container exits."""

    input_data_manifest_file: pathlib.Path
    """``<root>/input/action_inputs_manifest.json``: manifest of the invocation's input files.

    Passed as ``ROBOTO_ACTION_INPUTS_MANIFEST``.
    """

    dataset_metadata_changeset_file: pathlib.Path
    """``<root>/output/.metadata/dataset_metadata_changeset.json``: changes the action records to its dataset.

    The changes are to the dataset's tags and metadata. Passed as ``ROBOTO_DATASET_METADATA_CHANGESET_FILE``.
    """

    @classmethod
    def setup_within(cls, workspace_root: pathlib.Path) -> "Workspace":
        """Build a workspace in ``workspace_root``, creating its directories and empty files.

        Deletes everything already in ``workspace_root`` first, so one local invocation never sees files a previous
        one left, as a hosted invocation never does. Creates ``workspace_root`` if it does not exist.
        """
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
    """Return the directory to build an invocation's workspace in, and whether to delete it after the run.

    An action defined in a local directory uses ``<action_root>/.workspace`` and ignores ``workspace_dir_arg``. An
    action fetched from Roboto uses ``workspace_dir_arg``, or a new temporary directory when it is ``None``. Only the
    temporary directory is deleted after the run.

    Args:
        workspace_dir_arg: Value of ``--workspace-dir``, or ``None`` if it was not given.

    Returns:
        ``(workdir, is_temp)``: the workspace directory, and whether it is a temporary directory to delete after the
        run.
    """
    if action_source.is_local:
        # is_local already means action_root is set; this narrows its type.
        if action_source.action_root is None:
            raise RuntimeError("Expected action_source.action_root to be set")
        workdir = action_source.action_root / ".workspace"
        return (workdir, False)

    if workspace_dir_arg is not None:
        print(f"Using {workspace_dir_arg} as local workspace")
        return (workspace_dir_arg, False)

    temp_workdir = pathlib.Path(tempfile.mkdtemp(prefix="roboto_local_invoke_"))
    print(f"Using {temp_workdir} as temporary local workspace")
    return (temp_workdir, True)
