# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Local action invocation command."""

import argparse
import os
import pathlib

from ....action_runtime import (
    prepare_invocation_environment,
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

SECTION_TEMPLATE = f"{'#'*10} {{SECTION_NAME}} {'#'*10}"


def invoke_local(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    """Invoke an action locally using Docker.

    Supports four scenarios:
    1. No args: Use current directory as action root
    2. Path arg: Use specified path as action root
    3. Action name: Fetch from platform, use temp workspace
    4. Action name + --workspace-dir: Fetch from platform, use specified workspace
    """
    print(SECTION_TEMPLATE.format(SECTION_NAME="setup"))

    # 1. Validate input specification
    validate_input_specification(args, parser)

    # 2. Resolve action source (local path or platform action)
    action_or_path = getattr(args, "action_or_path", None)
    action_source = resolve_action_source(action_or_path, args, context)

    # Warn if workspace_dir is provided for local action
    if action_source.is_local and args.workspace_dir is not None:
        print(
            "Warning: --workspace-dir is ignored for local actions. "
            "It is only applicable when invoking actions fetched from the platform."
        )

    # 3. Resolve workspace directory
    workdir, is_temp_workdir = resolve_workspace(action_source, args.workspace_dir)

    # 4. Setup workspace
    preserve_workspace = getattr(args, "preserve_workspace", False)
    workspace = Workspace.setup_within(workdir, clear=preserve_workspace is False)

    # 5. Resolve organization
    org_id = resolve_organization(args.org, context.roboto_client)

    # 6. Validate parameters
    provided_params = getattr(args, "params", {})
    validate_parameters(action_source.action_params, provided_params)

    # 7. Parse input specification
    invocation_input = parse_input_spec(args)

    # 8. Prepare invocation environment
    prepare_invocation_environment(
        action_parameters=action_source.action_params,
        provided_parameter_values=provided_params,
        parameters_values_file=workspace.parameters_file,
        secrets_file=workspace.secrets_file,
        requires_downloaded_inputs=action_source.requires_downloaded_inputs,
        input_data=invocation_input,
        input_download_dir=workspace.input_dir,
        inputs_data_manifest_file=workspace.input_data_manifest_file,
        dataset_metadata_changeset_path=workspace.dataset_metadata_changeset_file,
        org_id=org_id,
        roboto_client=context.roboto_client,
        roboto_search=RobotoSearch.for_roboto_client(context.roboto_client, org_id),
    )

    # 9. Run action
    dataset_id = (
        getattr(args, "dataset_id", None)
        or actions.InvocationDataSource.unspecified().data_source_id
    )

    runner = DockerActionRunner(
        workspace=workspace,
        action_source=action_source,
        org_id=org_id,
        roboto_endpoint=context.roboto_client.endpoint,
        dataset_id=dataset_id,
        provided_params=provided_params,
        cleanup_workdir=is_temp_workdir,
        dry_run=getattr(args, "dry_run", False),
        log_level=args.log_level,
    )

    print(SECTION_TEMPLATE.format(SECTION_NAME="action"))
    runner.run()


def invoke_local_parser(parser: argparse.ArgumentParser) -> None:
    """Setup parser for local invocation command."""

    # Local directory path or action reference
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

    # Arguments shared with platform-based invocation
    add_org_arg(parser)
    add_input_specification_args(parser)
    add_parameter_args(parser)

    # Misc
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
    parser.add_argument(
        "--preserve-workspace",
        dest="preserve_workspace",
        action="store_true",
        default=False,
        help=(
            "Preserve existing workspace contents before execution. "
            "By default, the workspace is cleared to ensure a clean state. "
            "Use this flag to keep existing workspace contents, which can be useful "
            "when iterating on action development with the same file-based input data "
            "to avoid re-downloading data on each invocation."
        ),
    )


invoke_local_command = RobotoCommand(
    name="invoke-local",
    logic=invoke_local,
    setup_parser=invoke_local_parser,
    command_kwargs={"help": "Invoke an action locally using Docker."},
)
