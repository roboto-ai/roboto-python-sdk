# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import json
import pathlib
import typing

from ..domain import actions, files, secrets
from ..exceptions import (
    RobotoDomainException,
    RobotoNotFoundException,
    RobotoUnauthorizedException,
)
from ..http import RobotoClient
from ..logging import default_logger
from ..paths import join_within
from ..roboto_search import RobotoSearch
from .action_input import (
    ActionInputRecord,
    ActionInputResolver,
)
from .exceptions import PrepareEnvException
from .exit_codes import ExitCode

log = default_logger()


def _ensure_file_path_exists(p: pathlib.Path):
    if p.exists():
        return

    if not p.parent.exists():
        p.parent.mkdir(parents=True)

    p.touch()


def _merge_parameters_with_defaults(
    action_parameters: collections.abc.Iterable[actions.ActionParameter],
    parameter_values: typing.Optional[collections.abc.Mapping[str, typing.Any]],
) -> dict[str, typing.Any]:
    """Return ``parameter_values`` plus the default of each parameter it leaves out that has a default."""
    log.info("Merging action parameters with defaults")
    supplied_values = parameter_values or {}

    merged = {param.name: param.default for param in action_parameters if param.default is not None}
    merged |= supplied_values

    return merged


def prepare_invocation_parameters(
    action_parameters: collections.abc.Iterable[actions.ActionParameter],
    provided_parameter_values: collections.abc.Mapping[str, typing.Any],
    parameters_values_file: pathlib.Path,
    secrets_file: pathlib.Path,
    org_id: typing.Optional[str],
    roboto_client: RobotoClient,
):
    """Write an invocation's parameter values, and the values of the secrets they name, to files the action reads.

    Roboto calls this when it sets up an invocation, before the action's code starts, and ``roboto actions
    invoke-local`` calls it to run an action on your computer. The action reads both files through
    :py:class:`~roboto.action_runtime.InvocationContext`. Each file holds a JSON object keyed by parameter name, and
    is created, with its parent directories, when missing.

    A parameter that ``provided_parameter_values`` leaves out takes its default, when it has one. A value that is a
    secret URI (``roboto-secret://<name>`` or ``roboto-secret://<name>@<org_id>``) is written as given to
    ``parameters_values_file``, and the secret's value is written under the same parameter name to ``secrets_file``.
    ``secrets_file`` is written only when some value names a secret.

    Args:
        action_parameters: Parameters the action declares, whose defaults fill in the values left out.
        provided_parameter_values: Parameter values the invocation gives, by parameter name. They override defaults.
        parameters_values_file: File to write every parameter value to.
        secrets_file: File to write the values of the secrets the parameters name to.
        org_id: Organization that owns a secret whose URI names none. ``None`` uses the organization the caller acts
            in.
        roboto_client: Client to make requests to Roboto with.

    Raises:
        PrepareEnvException: A parameter names a secret that does not exist or the caller cannot read. Its exit code
            is :py:attr:`~roboto.action_runtime.ExitCode.InternalError`.
    """
    merged_parameters = _merge_parameters_with_defaults(action_parameters, provided_parameter_values)

    secret_params: dict[str, str] = {}
    for param_name, param_value in merged_parameters.items():
        if secrets.is_secret_uri(param_value):
            log.info(
                "Param '%s' is a secret, resolving value",
                param_name,
            )
            try:
                secret = secrets.Secret.from_uri(
                    uri=param_value,
                    roboto_client=roboto_client,
                    fallback_org_id=org_id,
                )
                actual_value = secret.read_value().get_secret_value()
                secret_params[param_name] = actual_value
            except (RobotoNotFoundException, RobotoUnauthorizedException):
                raise PrepareEnvException(
                    ExitCode.InternalError,
                    f"Failed to retrieve secret {param_value}, because it does not exist.",
                ) from None

    if secret_params:
        log.info("Writing secret action parameter values to %s", secrets_file)
        _ensure_file_path_exists(secrets_file)
        secrets_file.write_text(json.dumps(secret_params, indent=2))

    log.info(
        "Writing action parameter values to %s",
        parameters_values_file,
    )
    _ensure_file_path_exists(parameters_values_file)
    parameters_values_file.write_text(json.dumps(merged_parameters, indent=2))


def _hardlink_resolved_input_to_target_directory(
    resolved_input: ActionInputRecord,
    target_directory: pathlib.Path,
) -> ActionInputRecord:
    files_relative_to_target_dir: list[tuple[files.FileRecord, typing.Optional[pathlib.Path]]] = []

    unique_dataset_count = len(set([record.association_id for record, _ in resolved_input.files]))
    for record, cached_path in resolved_input.files:
        if not cached_path:
            files_relative_to_target_dir.append((record, None))
            continue

        # A directory per dataset keeps two datasets' files at the same path apart. Input from one dataset keeps
        # each file at its path within the dataset, where actions that read the input directory without
        # InvocationContext.get_input expect it.
        if unique_dataset_count > 1:
            target = join_within(target_directory / record.association_id, record.relative_path)
        else:
            target = join_within(target_directory, record.relative_path)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.hardlink_to(cached_path)

        files_relative_to_target_dir.append((record, target))

    return resolved_input.model_copy(update={"files": files_relative_to_target_dir})


def prepare_invocation_input_data(
    requires_downloaded_inputs: bool,
    input_data: typing.Optional[actions.InvocationInput],
    target_directory: pathlib.Path,
    download_directory: pathlib.Path,
    inputs_data_manifest_file: pathlib.Path,
    roboto_client: RobotoClient,
    roboto_search: RobotoSearch,
):
    """Resolve an invocation's input to the files, sessions, and topics it selects, and write them to a manifest.

    Roboto calls this when it sets up an invocation, before the action's code starts, and ``roboto actions
    invoke-local`` calls it to run an action on your computer. The action reads the manifest through
    :py:meth:`~roboto.action_runtime.InvocationContext.get_input`, which expects it to exist once setup completes, so
    an invocation with no input, such as one run against only a dataset, gets a manifest that selects nothing.

    With ``requires_downloaded_inputs``, the selected files are downloaded to ``download_directory`` and, when
    ``target_directory`` differs from it, hard-linked into ``target_directory`` at their paths within their datasets.
    When the files come from more than one dataset, each link goes under a directory named for its dataset's ID, as
    ``<target_directory>/<dataset_id>/<path>``. The manifest records each file's linked path, or its downloaded path
    when no link is made.

    Args:
        requires_downloaded_inputs: Whether to download the selected files.
        input_data: Input selectors of the invocation. ``None`` selects nothing.
        target_directory: Directory the action reads its input files from.
        download_directory: Directory to download the files to, as
            :py:meth:`~roboto.action_runtime.action_input.ActionInputResolver.resolve_input_spec` lays them out.
        inputs_data_manifest_file: File to write the manifest to, as
            :py:class:`~roboto.action_runtime.action_input.ActionInputRecord` JSON. Created, with its parent
            directories, when missing.
        roboto_client: Client to make requests to Roboto with.
        roboto_search: :py:class:`~roboto.roboto_search.RobotoSearch` that runs the selectors' RoboQL queries.

    Raises:
        PrepareEnvException: A request to Roboto failed, such as a lookup of an ID that matches nothing. Its exit
            code is :py:attr:`~roboto.action_runtime.ExitCode.InternalError` when Roboto failed (HTTP status 500 or
            above) and :py:attr:`~roboto.action_runtime.ExitCode.UsageError` otherwise.
        ExceptionGroup: With ``requires_downloaded_inputs``, one or more files still failed to download after three
            attempts.
        RobotoIllegalArgumentException: A file's path within its dataset resolves outside ``target_directory``.
    """
    resolved_input = ActionInputRecord()
    if input_data is not None:
        log.info("Resolving input data")

        input_resolver = ActionInputResolver.from_env(
            roboto_client=roboto_client,
            roboto_search=roboto_search,
        )

        try:
            resolved_input = input_resolver.resolve_input_spec(
                input_data,
                download=requires_downloaded_inputs,
                download_path=download_directory,
            )
        except RobotoDomainException as exc:
            msg = f"Failed to retrieve invocation input data! Reason: {exc.message}"
            log.error(msg)
            is_server_error = exc.http_status_code >= 500
            raise PrepareEnvException(ExitCode.InternalError if is_server_error else ExitCode.UsageError, msg) from None

        if requires_downloaded_inputs and download_directory != target_directory:
            resolved_input = _hardlink_resolved_input_to_target_directory(resolved_input, target_directory)

    log.info("Writing input manifest to %s", inputs_data_manifest_file)
    _ensure_file_path_exists(inputs_data_manifest_file)
    inputs_data_manifest_file.write_text(resolved_input.model_dump_json())


def prepare_metadata_changeset_manifest(
    dataset_metadata_changeset_path: pathlib.Path,
):
    """Create the empty file in which an action records changes to its dataset's tags and metadata.

    Roboto calls this when it sets up an invocation, before the action's code starts, and ``roboto actions
    invoke-local`` calls it to run an action on your computer. Roboto applies the changes the action records when the
    invocation finishes.

    Args:
        dataset_metadata_changeset_path: File to create, with its parent directories. An existing file is left
            unchanged.
    """
    log.info(
        "Creating dataset metadata changeset file at %s",
        dataset_metadata_changeset_path,
    )
    _ensure_file_path_exists(dataset_metadata_changeset_path)
