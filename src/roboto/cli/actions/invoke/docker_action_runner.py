# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""DockerActionRunner for local action invocation.

This module provides the DockerActionRunner class which encapsulates Docker image
resolution, building, command construction, and container execution for local
action invocation.
"""

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
    """Encapsulates Docker execution lifecycle for local action invocation.

    This class consolidates Docker image resolution, environment setup,
    command building, and container execution into a single interface.
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
        """Initialize DockerActionRunner.

        Args:
            workspace: Workspace instance with all paths
            action_source: ActionSource indicating where action comes from
            org_id: Organization ID
            dataset_id: Dataset ID for invocation
            provided_params: User-provided parameter values
            cleanup_workdir: Whether to clean up workdir after execution
            roboto_config: RobotoConfig instance
            dry_run: Whether to run in dry-run mode (gates side effects)
            log_level: Log level for the action invocation
        """
        self.workspace = workspace
        self.action_source = action_source
        self.org_id = org_id
        self.dataset_id = dataset_id
        self.provided_params = provided_params
        self.cleanup_workdir = cleanup_workdir
        self.roboto_config = roboto_config
        self.dry_run = dry_run
        self.log_level = log_level

    def run(self) -> None:
        """Execute the action in a Docker container.

        This orchestrates the full Docker execution lifecycle:
        1. Build Docker command (which resolves image and environment)
        2. Execute container with cleanup
        """
        cmd = self.__build_run_command()
        self.__execute_container(cmd)

    def __build_run_command(self) -> list[str]:
        """Build Docker run command with proper configuration.

        Resolves the Docker image and builds environment variables, then
        constructs the full Docker run command.

        Configures:
        - Volume mounts (workspace directories and config)
        - Environment variables (ROBOTO_* + action parameters + container env_vars)
        - User/group settings (current user/group)
        - Container parameters (entrypoint, command, workdir)

        Returns:
            Docker command as list of strings
        """
        # Resolve image and build environment
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

        # Get container parameters from action source
        container_parameters = self.action_source.container_params

        # Merge environment variables: runtime env_vars take precedence over container env_vars
        merged_env_vars = {}
        if container_parameters and container_parameters.env_vars:
            merged_env_vars.update(container_parameters.env_vars)
        merged_env_vars.update(env_vars)

        # Add environment variables
        for key, value in merged_env_vars.items():
            cmd.extend(["-e", f"{key}={value}"])

        # Add workdir if specified
        if container_parameters and container_parameters.workdir:
            cmd.extend(["-w", container_parameters.workdir])

        # Add entrypoint if specified
        if container_parameters and container_parameters.entry_point:
            cmd.append("--entrypoint")
            cmd.append(container_parameters.entry_point[0])

        # Add image name
        cmd.append(image_name)

        # Add command if specified
        if container_parameters and container_parameters.command:
            cmd.extend(container_parameters.command)

        return cmd

    def __build_environment(self) -> dict[str, str]:
        """Build environment variables for Docker container.

        Determines workdir based on action source:
        - Local actions: use action_root
        - Platform actions: use workspace.input_dir.parent

        Returns:
            Dictionary of environment variables
        """
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

        # Add log level if specified
        if self.log_level is not None:
            env_vars[RobotoEnvKey.LogLevel.value] = self.log_level

        # Add action parameters as environment variables
        if self.provided_params:
            for param_name, param_value in self.provided_params.items():
                env_var_name = RobotoEnvKey.for_parameter(param_name)
                env_vars[env_var_name] = str(param_value)

        return env_vars

    def __execute_container(self, cmd: list[str]) -> None:
        """Execute Docker container and handle cleanup.

        Args:
            cmd: Docker command to execute
        """
        # Determine workdir for cleanup
        if self.action_source.is_local and self.action_source.action_root:
            workdir = self.action_source.action_root
        else:
            workdir = self.workspace.input_dir.parent

        with subprocess.Popen(cmd, text=True) as run_proc:
            try:
                run_proc.wait()
            except KeyboardInterrupt:
                run_proc.terminate()
                try:
                    run_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print("Container did not stop gracefully, killing...")
                    run_proc.kill()
                    run_proc.wait()
            finally:
                # Always delete secrets file to avoid it sitting around on disk
                self.workspace.secrets_file.unlink(missing_ok=True)

                # Clean up workdir if requested
                if self.cleanup_workdir and workdir.exists():
                    shutil.rmtree(workdir)

    def __resolve_image(self) -> str:
        """Resolve Docker image for action execution.

        For local actions:
        - Look for Dockerfile in action_root
        - Build Docker image from Dockerfile
        - Return image name/tag

        For platform-fetched actions:
        - Use action_record.uri
        - Return image URI

        Returns:
            Docker image name/URI to use for execution.

        Raises:
            ActionRuntimeException: If image cannot be resolved.
        """
        # Local action with Dockerfile
        if self.action_source.is_local:
            if self.action_source.action_root is None:
                # Defensive check, should be an impossible code path
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
                # Defensive check, should be an impossible code path
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

        # Platform action with image_uri
        if self.action_source.action_record is not None and self.action_source.action_record.uri:
            return self.action_source.action_record.uri

        raise ActionRuntimeException(
            "Cannot resolve Docker image for action execution. "
            "For local actions, a Dockerfile must exist in the action root directory. "
            "For platform actions, the action record must have an image_uri specified. "
            "Please check your action configuration."
        )
