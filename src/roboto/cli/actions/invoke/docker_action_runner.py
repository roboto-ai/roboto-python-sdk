# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
import shutil
import socket
import subprocess
import typing

from ....action_runtime import (
    ActionRuntimeException,
)
from ....config import RobotoConfig
from ....env import RobotoEnvKey
from .action_resolution import ActionSource
from .workspace import Workspace


class DockerActionRunner:
    """Runner that runs an action on this machine in a Docker container.

    ``roboto actions invoke-local`` builds it once the workspace holds the action's parameters and input data, and
    calls ``run``.
    """

    def __init__(
        self,
        workspace: Workspace,
        action_source: ActionSource,
        org_id: str,
        dataset_id: str,
        provided_params: dict[str, typing.Any],
        cleanup_workdir: bool,
        roboto_config: RobotoConfig,
        dry_run: bool = False,
        log_level: typing.Optional[str] = None,
    ):
        self.workspace = workspace
        """Local directories and files the action reads and writes, mounted into the container."""

        self.action_source = action_source
        """Action to run: one defined in a local directory, or one fetched from Roboto."""

        self.org_id = org_id
        """ID of the organization the action runs in."""

        self.dataset_id = dataset_id
        """ID of the dataset passed to the action in ``ROBOTO_DATASET_ID``, a placeholder when the run names none."""

        self.provided_params = provided_params
        """Parameter values given on the command line, keyed by parameter name."""

        self.cleanup_workdir = cleanup_workdir
        """Whether to delete the workspace once the container exits."""

        self.roboto_config = roboto_config
        """Configuration whose endpoint and API key the action uses to make requests to Roboto."""

        self.dry_run = dry_run
        """Whether the action runs as a dry run, passed to it in ``ROBOTO_DRY_RUN``."""

        self.log_level = log_level
        """Log level passed to the action in ``ROBOTO_LOG_LEVEL``, or ``None`` to leave it unset."""

    def run(self) -> None:
        """Run the action in a Docker container and wait for it to exit.

        For an action defined in a local directory, first builds its image from the ``Dockerfile`` in that directory;
        for one fetched from Roboto, runs the image the action names. After the container exits, deletes the secrets
        file and, when ``cleanup_workdir`` is set, the workspace.

        Raises:
            ActionRuntimeException: A local action's directory has no ``Dockerfile`` or its image fails to build, or an
                action fetched from Roboto names no image.
        """
        cmd = self.__build_run_command()
        self.__execute_container(cmd)

    def __build_run_command(self) -> list[str]:
        """Build the ``docker run`` command for this run.

        The container runs as the current user and group, so files the action writes are owned by that user. The
        workspace is mounted at the same path it has on this machine, so the paths in the ``ROBOTO_*`` variables
        resolve inside the container.
        """
        image_name = self.__resolve_image()
        env_vars = self.__build_environment()

        cmd = [
            "docker",
            "run",
            "--rm",
            "-it",
            "-u",
            f"{os.getuid()}:{os.getgid()}",
            "-v",
            f"{self.workspace.root}:{self.workspace.root}",
        ]

        container_parameters = self.action_source.container_params

        # A variable the action's container parameters set is overridden when this run sets the same name.
        merged_env_vars = {}
        if container_parameters and container_parameters.env_vars:
            merged_env_vars.update(container_parameters.env_vars)
        merged_env_vars.update(env_vars)

        for key, value in merged_env_vars.items():
            cmd.extend(["-e", f"{key}={value}"])

        if container_parameters and container_parameters.workdir:
            cmd.extend(["-w", container_parameters.workdir])

        # Only the first element of entry_point is passed; the rest are not.
        if container_parameters and container_parameters.entry_point:
            cmd.append("--entrypoint")
            cmd.append(container_parameters.entry_point[0])

        cmd.append(image_name)

        if container_parameters and container_parameters.command:
            cmd.extend(container_parameters.command)

        return cmd

    def __build_environment(self) -> dict[str, str]:
        """Build the environment variables the action reads, with values for this run.

        These are the ``ROBOTO_*`` variables that name the workspace's directories and files, the organization and
        dataset, and the endpoint and API key to make requests to Roboto with, plus one ``ROBOTO_PARAM_<name>`` for
        each parameter value given. ``HOME`` is the workspace root.
        """
        # No invocation exists in Roboto for a local run, so ROBOTO_INVOCATION_ID is a fixed placeholder.
        env_vars = {
            RobotoEnvKey.DatasetId.value: self.dataset_id,
            RobotoEnvKey.InputDir.value: str(self.workspace.input_dir),
            RobotoEnvKey.OutputDir.value: str(self.workspace.output_dir),
            RobotoEnvKey.InvocationId.value: "inv_LOCAL_DOCKER_INVOCATION",
            RobotoEnvKey.OrgId.value: self.org_id,
            RobotoEnvKey.RobotoServiceEndpoint.value: self.roboto_config.endpoint,
            RobotoEnvKey.ApiKey.value: self.roboto_config.api_key,
            RobotoEnvKey.ActionRuntimeConfigDir.value: str(self.workspace.config_dir),
            RobotoEnvKey.ActionInputsManifest.value: str(self.workspace.input_data_manifest_file),
            RobotoEnvKey.ActionParametersFile.value: str(self.workspace.parameters_file),
            RobotoEnvKey.DatasetMetadataChangesetFile.value: str(self.workspace.dataset_metadata_changeset_file),
            RobotoEnvKey.DryRun.value: str(self.dry_run).lower(),
            RobotoEnvKey.RobotoEnv.value: f"LOCAL ({socket.getfqdn()})",
            "HOME": str(self.workspace.root),
        }

        if self.log_level is not None:
            env_vars[RobotoEnvKey.LogLevel.value] = self.log_level

        if self.provided_params:
            for param_name, param_value in self.provided_params.items():
                env_var_name = RobotoEnvKey.for_parameter(param_name)
                env_vars[env_var_name] = str(param_value)

        return env_vars

    def __execute_container(self, cmd: list[str]) -> None:
        """Run ``cmd`` until the container exits, then delete the secrets file and, if asked to, the workspace."""
        # For a local action this is the action's own directory. invoke_local sets cleanup_workdir only for a
        # temporary workspace, which local actions never use, so that directory is never deleted.
        if self.action_source.is_local and self.action_source.action_root:
            workdir = self.action_source.action_root
        else:
            workdir = self.workspace.input_dir.parent

        with subprocess.Popen(cmd, text=True) as run_proc:
            try:
                run_proc.wait()
            except KeyboardInterrupt:
                # The user pressed Ctrl-C. Send SIGTERM to `docker run`, and kill it if it has not exited within 5
                # seconds. The KeyboardInterrupt is not re-raised, so the command ends normally after cleanup.
                run_proc.terminate()
                try:
                    run_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print("Container did not stop gracefully, killing...")
                    run_proc.kill()
                    run_proc.wait()
            finally:
                # The secrets file holds the values of secrets the parameters name. Delete it however the run ends,
                # so those values do not stay on disk.
                self.workspace.secrets_file.unlink(missing_ok=True)

                if self.cleanup_workdir and workdir.exists():
                    shutil.rmtree(workdir)

    def __resolve_image(self) -> str:
        """Return the image to run, building it first for an action defined in a local directory.

        A local action's image is built from the ``Dockerfile`` in its directory and tagged ``<action name>:latest``.
        An action fetched from Roboto runs the image its record names. Raises ``ActionRuntimeException`` when a local
        action's directory has no ``Dockerfile``, ``docker build`` fails, or an action fetched from Roboto names no
        image.
        """
        if self.action_source.is_local:
            if self.action_source.action_root is None:
                # Unreachable: is_local means action_root is set. The check narrows its type.
                raise ActionRuntimeException(
                    "Failed to determine action directory for local action invocation. "
                    "Please specify a valid action directory path or run the command from within "
                    "an action directory containing an action.json file."
                )

            dockerfile_path = self.action_source.action_root / "Dockerfile"
            if not dockerfile_path.exists():
                raise ActionRuntimeException(
                    f"Dockerfile not found in {self.action_source.action_root}. "
                    "Local actions must have a Dockerfile in the action root directory."
                )

            if self.action_source.action_config is None:
                # Unreachable from `roboto actions invoke-local`, which loads action.json for every local action.
                raise ActionRuntimeException(
                    f"Failed to load action configuration from {self.action_source.action_root}. "
                    f"The action.json file may be missing or invalid. "
                    f"Please ensure that {self.action_source.action_root / 'action.json'} exists "
                    "and contains valid action configuration with a 'name' field."
                )

            image_name = f"{self.action_source.action_config.name}:latest"
            print(f"Building Docker image from Dockerfile: {image_name}")

            build_cmd = [
                "docker",
                "build",
                "-t",
                image_name,
                str(self.action_source.action_root),
            ]

            result = subprocess.run(build_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise ActionRuntimeException(f"Failed to build Docker image: {result.stderr}")

            return image_name

        if self.action_source.action_record is not None and self.action_source.action_record.uri:
            return self.action_source.action_record.uri

        raise ActionRuntimeException(
            "Cannot resolve Docker image for action execution. "
            "For local actions, a Dockerfile must exist in the action root directory. "
            "For platform actions, the action record must have an image_uri specified. "
            "Please check your action configuration."
        )
