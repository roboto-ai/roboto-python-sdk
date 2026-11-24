# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import os
import pathlib

from ....action_runtime import (
    prepare_invocation_input_data,
    prepare_invocation_parameters,
    prepare_metadata_changeset_manifest,
)
from ....domain import actions
from ....roboto_search import RobotoSearch
from ...command import RobotoCommand
from ...common_args import add_org_arg
from ...context import CLIContext
from .action_resolution import (
    resolve_action_source,
)
from .cli_args import (
    add_input_specification_args,
    add_parameter_args,
)
from .docker_action_runner import (
    DockerActionRunner,
)
from .input_parsing import (
    parse_input_spec,
    validate_input_specification,
)
from .validation import (
    resolve_organization,
    validate_parameters,
)
from .workspace import (
    Workspace,
    resolve_workspace,
)

SECTION_TEMPLATE = f"{'#' * 10} {{SECTION_NAME}} {'#' * 10}"


def invoke_local(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    """Run an action on this machine in a Docker container, and print the setup steps and the container's output.

    The ``action_or_path`` argument and ``--workspace-dir`` decide which action runs and in which workspace
    directory:

    1. Omitted: the action that the nearest ``action.json`` in the current directory or its parents defines, run in
       ``.workspace`` under that directory.
    2. A path: the action that ``action.json`` in that directory defines, run in ``.workspace`` under it.
    3. An action reference: the action fetched from Roboto, run in a temporary directory that is deleted after the run.
    4. An action reference with ``--workspace-dir``: the action fetched from Roboto, run in that directory, which is
       kept after the run.

    Each run first empties the workspace directory.

    An invalid input specification, such as ``--file-path`` without ``--dataset``, exits with status 2 after
    ``parser.error`` prints the usage text and the reason to stderr. Ctrl-C while the action runs stops the container,
    killing it if it has not stopped within 5 seconds, and the command then ends normally after the same cleanup as a
    finished run.

    Raises:
        ActionRuntimeException: No ``action.json`` is found for a local action.
        ValueError: A ``--parameter`` names a parameter the action does not define.
    """
    print(SECTION_TEMPLATE.format(SECTION_NAME="setup"))

    validate_input_specification(args, parser)

    action_or_path = getattr(args, "action_or_path", None)
    action_source = resolve_action_source(action_or_path, args, context)

    if action_source.is_local and args.workspace_dir is not None:
        print(
            "Warning: --workspace-dir is ignored for local actions. "
            "It is only applicable when invoking actions fetched from the platform."
        )

    workdir, is_temp_workdir = resolve_workspace(action_source, args.workspace_dir)

    workspace = Workspace.setup_within(workdir)

    org_id = resolve_organization(args.org, context.roboto_client)

    provided_params = getattr(args, "params", {})
    validate_parameters(action_source.action_params, provided_params)

    invocation_input = parse_input_spec(args)

    prepare_invocation_parameters(
        action_parameters=action_source.action_params,
        provided_parameter_values=provided_params,
        parameters_values_file=workspace.parameters_file,
        secrets_file=workspace.secrets_file,
        org_id=org_id,
        roboto_client=context.roboto_client,
    )

    roboto_cache_dir = context.roboto_config.get_cache_dir()
    cache_download_path = roboto_cache_dir / "files"
    prepare_invocation_input_data(
        requires_downloaded_inputs=action_source.requires_downloaded_inputs,
        input_data=invocation_input,
        # Downloaded files go to the Roboto cache directory, which outlives the emptied workspace, so a later run skips
        # files already saved there; each is then hard-linked into the workspace's input directory.
        target_directory=workspace.input_dir,
        download_directory=cache_download_path,
        inputs_data_manifest_file=workspace.input_data_manifest_file,
        roboto_client=context.roboto_client,
        roboto_search=RobotoSearch.for_roboto_client(context.roboto_client, org_id),
    )

    prepare_metadata_changeset_manifest(
        dataset_metadata_changeset_path=workspace.dataset_metadata_changeset_file,
    )

    dataset_id = getattr(args, "dataset_id", None) or actions.InvocationDataSource.unspecified().data_source_id

    runner = DockerActionRunner(
        workspace=workspace,
        action_source=action_source,
        org_id=org_id,
        dataset_id=dataset_id,
        provided_params=provided_params,
        cleanup_workdir=is_temp_workdir,
        roboto_config=context.roboto_config,
        dry_run=getattr(args, "dry_run", False),
        log_level=args.log_level,
    )

    print(SECTION_TEMPLATE.format(SECTION_NAME="action"))
    runner.run()


def invoke_local_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "action_or_path",
        nargs="?",
        help=(
            f"Action to invoke locally. Can be:{os.linesep}"
            f"  - A path to local action directory (e.g., '.', './my-action', '/abs/path'){os.linesep}"
            f"  - An action reference (e.g., 'my-action', 'org/my-action', 'action@digest'){os.linesep}"
            f"  - Omitted to use current directory{os.linesep}"
            f"{os.linesep}"
            f"Examples:{os.linesep}"
            f"  roboto actions invoke-local                    # Use current directory (implied){os.linesep}"
            f"  roboto actions invoke-local .                  # Use current directory (explicit){os.linesep}"
            f"  roboto actions invoke-local ./my-action        # Use local action{os.linesep}"
            f"  roboto actions invoke-local my-action          # Fetch from platform{os.linesep}"
            f"  roboto actions invoke-local org/my-action      # Fetch from specific org{os.linesep}"
        ),
    )

    # Shared with `roboto actions invoke`.
    add_org_arg(parser)
    add_input_specification_args(parser)
    add_parameter_args(parser)

    parser.add_argument(
        "--workspace-dir",
        type=pathlib.Path,
        help=(
            "Workspace directory for local execution. "
            "Only applicable when invoking a platform action (not an action defined in a local directory). "
            "If not specified, a temporary directory is created."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run in dry-run mode. "
            "Actions should use this flag to gate side effects such as uploading files, "
            "modifying metadata, or making non-idempotent API calls."
        ),
    )


invoke_local_command = RobotoCommand(
    name="invoke-local",
    logic=invoke_local,
    setup_parser=invoke_local_parser,
    command_kwargs={"help": "Invoke an action locally using Docker."},
)
