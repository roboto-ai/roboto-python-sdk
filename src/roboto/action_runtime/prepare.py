# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""
Action runtime setup utilities.

This module provides utilities for preparing action runtime (invocation) environments,
both in hosted execution and local development contexts.
"""

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
    """Merge supplied parameter values with action parameter defaults."""
    log.info("Merging action parameters with defaults")
    supplied_values = parameter_values or {}

    # Start with defaults for all parameters that have them
    merged = {param.name: param.default for param in action_parameters if param.default is not None}

    # Override with supplied values
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

        # GM (2025-11-26):
        # Fix for ENG-1848: Handle multi-dataset input files
        # Previously: files downloaded to `<input_dir>/<relative_path>`
        # Now: files from multiple datasets prefixed with `<dataset_id>/<relative_path>`
        # Single dataset maintains backward compatibility to avoid breaking existing actions
        # that do not use `InvocationContext.get_input()`
        if unique_dataset_count > 1:
            target = target_directory / record.association_id / record.relative_path
        else:
            # backward compat behavior
            target = target_directory / record.relative_path

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
    # Resolve and optionally download inputs
    resolved_input: typing.Optional[ActionInputRecord] = None
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

        # Modify resolved paths to be relative to the target directory
        if requires_downloaded_inputs and download_directory != target_directory:
            resolved_input = _hardlink_resolved_input_to_target_directory(resolved_input, target_directory)

        log.info("Writing input manifest to %s", inputs_data_manifest_file)
        _ensure_file_path_exists(inputs_data_manifest_file)
        inputs_data_manifest_file.write_text(resolved_input.model_dump_json())


def prepare_metadata_changeset_manifest(
    dataset_metadata_changeset_path: pathlib.Path,
):
    log.info(
        "Creating dataset metadata changeset file at %s",
        dataset_metadata_changeset_path,
    )
    _ensure_file_path_exists(dataset_metadata_changeset_path)
