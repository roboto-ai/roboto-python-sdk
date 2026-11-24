# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import os
import pathlib
import re
import typing

import pydantic
import pydantic_settings

from .compat import StrEnum
from .sentinels import NotSet, NotSetType

ROBOTO_ENV_VAR_PREFIX = "ROBOTO_"
"""Prefix of the name of every environment variable in ``RobotoEnvKey``."""

Timeout: typing.TypeAlias = typing.Optional[typing.Union[float, NotSetType]]
"""Timeout of a request to Roboto, in seconds.

``None`` waits indefinitely, and ``NotSet`` uses the client's default timeout.
"""


def resolve_env_variables(value: str):
    """Return ``value`` with each ``$NAME`` and ``${NAME}`` replaced by the value of environment variable ``NAME``.

    A variable that is unset is replaced with the empty string.

    Args:
        value: Text that may name environment variables.
    """
    resolved_value = value

    # The left alternative matches $NAME and the right matches ${NAME}. Each captures the whole reference and,
    # in an inner group, the bare name to look up.
    pattern = re.compile(r"(\$(\w+))|(\$\{(\w+)})")
    matches = pattern.findall(resolved_value)

    for match in matches:
        left, left_word, right, right_word = match

        if left != "" and left_word != "":
            resolved_value = resolved_value.replace(left, os.getenv(left_word, ""))

        if right != "" and right_word != "":
            resolved_value = resolved_value.replace(right, os.getenv(right_word, ""))

    return resolved_value


class RobotoEnvKey(StrEnum):
    """Names of the environment variables the SDK reads, and that Roboto sets for an action's code.

    Each member's value is the variable's name, such as ``ROBOTO_DATASET_ID``.
    """

    ActionInputs = f"{ROBOTO_ENV_VAR_PREFIX}ACTION_INPUTS"
    """Input manifest of the invocation, as JSON: the files, sessions, and topics it was invoked on.

    Set when Roboto does not download the invocation's selected files and the manifest fits in an environment
    variable. :py:meth:`~roboto.action_runtime.InvocationContext.get_input` reads the manifest from the first of
    ``ROBOTO_ACTION_INPUTS``, ``ROBOTO_ACTION_INPUTS_URL`` and ``ROBOTO_ACTION_INPUTS_MANIFEST`` that is set."""

    ActionInputsUrl = f"{ROBOTO_ENV_VAR_PREFIX}ACTION_INPUTS_URL"
    """URL to fetch the invocation's input manifest from, when it is too large for ``ROBOTO_ACTION_INPUTS``."""

    ActionInputsManifest = f"{ROBOTO_ENV_VAR_PREFIX}ACTION_INPUTS_MANIFEST"
    """Path to a JSON file holding the invocation's input manifest.

    When Roboto downloads the selected files, this manifest also gives each file's path under ``ROBOTO_INPUT_DIR``."""

    ActionParametersFile = f"{ROBOTO_ENV_VAR_PREFIX}ACTION_PARAMETERS_FILE"
    """Path to a JSON file of the invocation's parameter values, with the action's defaults filled in."""

    ActionRuntimeConfigDir = f"{ROBOTO_ENV_VAR_PREFIX}ACTION_RUNTIME_CONFIG_DIR"
    """Directory of the invocation's runtime configuration.

    Holds ``secrets.json``, the values of the parameters that name secrets."""

    ActionTimeout = f"{ROBOTO_ENV_VAR_PREFIX}ACTION_TIMEOUT"
    """Number of seconds the invocation may run before Roboto cancels it."""

    ApiKey = f"{ROBOTO_ENV_VAR_PREFIX}API_KEY"
    """Access token the SDK authenticates with, read ahead of ``ROBOTO_BEARER_TOKEN`` and the config file."""

    BearerToken = f"{ROBOTO_ENV_VAR_PREFIX}BEARER_TOKEN"
    """Access token the SDK authenticates with when ``ROBOTO_API_KEY`` is unset."""

    ConfigFile = f"{ROBOTO_ENV_VAR_PREFIX}CONFIG_FILE"
    """Path to the Roboto config file. Unset reads ``~/.roboto/config.json``."""

    CacheDir = f"{ROBOTO_ENV_VAR_PREFIX}CACHE_DIR"
    """Directory the SDK caches data from Roboto in. Unset uses the operating system's per-user cache directory."""

    DatasetMetadataChangesetFile = f"{ROBOTO_ENV_VAR_PREFIX}DATASET_METADATA_CHANGESET_FILE"
    """Path to a file in which the action records changes to its dataset's tags and metadata.

    Roboto applies the changes when the invocation finishes."""

    DatasetId = f"{ROBOTO_ENV_VAR_PREFIX}DATASET_ID"
    """ID of the dataset the invocation was invoked on."""

    DryRun = f"{ROBOTO_ENV_VAR_PREFIX}DRY_RUN"
    """Whether the invocation is a dry run, in which the action should skip side effects.

    ``roboto actions invoke-local --dry-run`` sets it."""

    FileMetadataChangesetFile = f"{ROBOTO_ENV_VAR_PREFIX}FILE_METADATA_CHANGESET_FILE"
    """Path to a file in which the action records tag and metadata changes for the files in ``ROBOTO_OUTPUT_DIR``.

    Roboto applies the changes after it uploads those files."""

    InputDir = f"{ROBOTO_ENV_VAR_PREFIX}INPUT_DIR"
    """Directory Roboto downloads the invocation's selected files into, when it downloads them."""

    InvocationId = f"{ROBOTO_ENV_VAR_PREFIX}INVOCATION_ID"
    """ID of the invocation."""

    LogLevel = f"{ROBOTO_ENV_VAR_PREFIX}LOG_LEVEL"
    """Log level requested for the invocation: ``ERROR``, ``WARNING``, ``INFO`` or ``DEBUG``.

    The action applies it; :py:attr:`~roboto.action_runtime.InvocationContext.log_level` reads it."""

    OrgId = f"{ROBOTO_ENV_VAR_PREFIX}ORG_ID"
    """ID of the organization to act in.

    Roboto sets it to the invocation's organization. The CLI and
    :py:meth:`~roboto.roboto_search.RobotoSearch.from_env` use it when the caller names no organization."""

    OutputDir = f"{ROBOTO_ENV_VAR_PREFIX}OUTPUT_DIR"
    """Directory for the action's output files, which Roboto uploads to a dataset when the invocation finishes."""

    Profile = f"{ROBOTO_ENV_VAR_PREFIX}PROFILE"
    """Name of the config file profile to read.

    Unset uses the config file's default profile, and an empty value names the profile ``default``."""

    RobotoEnv = f"{ROBOTO_ENV_VAR_PREFIX}ENV"
    """Description of where the SDK runs, recorded as the origination of the files and directories it uploads.

    Roboto sets it in an action's container, such as ``invocation: <invocation_id>``. Unset, uploads record
    ``roboto <SDK version>``."""

    RobotoServiceUrl = f"{ROBOTO_ENV_VAR_PREFIX}SERVICE_URL"
    """Deprecated. URL of the Roboto API.

    Use ``ROBOTO_SERVICE_ENDPOINT`` instead; the SDK never reads this variable."""

    RobotoServiceEndpoint = f"{ROBOTO_ENV_VAR_PREFIX}SERVICE_ENDPOINT"
    """URL of the Roboto API to send requests to, when the access token comes from the environment.

    Unset uses ``https://api.roboto.ai``."""

    StageInputs = f"{ROBOTO_ENV_VAR_PREFIX}STAGE_INPUTS"
    """Whether Roboto downloads the invocation's selected files into ``ROBOTO_INPUT_DIR`` before the action's code runs.

    ``1`` when the action's :py:attr:`~roboto.domain.actions.Action.requires_downloaded_inputs` is true, and ``0``
    otherwise. Either way, the action learns what it was invoked on from its input manifest."""

    @staticmethod
    def for_parameter(param_name: str) -> str:
        """Return the name of the environment variable that holds the value of action parameter ``param_name``.

        Roboto sets one such variable, ``ROBOTO_PARAM_<param_name>``, for each parameter value of an invocation.

        Args:
            param_name: Name of the action parameter.
        """
        return f"{ROBOTO_ENV_VAR_PREFIX}PARAM_{param_name}"


_roboto_env_instance: typing.Optional["RobotoEnv"] = None


# Each alias repeats its RobotoEnvKey value as a string literal, because type checking requires a literal alias: an
# enum member or an f-string fails it.
class RobotoEnv(pydantic_settings.BaseSettings):
    """Values of the Roboto environment variables the SDK reads, parsed when the instance is created.

    Each field reads the variable ``RobotoEnvKey`` names, and is ``None`` when that variable is unset unless its
    docstring says otherwise. ``default`` returns one instance shared across the process.
    """

    @classmethod
    def default(cls) -> "RobotoEnv":
        """Return the process's shared ``RobotoEnv``, created from the environment on the first call.

        Later changes to the environment do not reach it; create a ``RobotoEnv`` to read the current values.
        """
        # Held at module level because pydantic would turn a class variable into a ModelPrivateAttr.
        global _roboto_env_instance
        if _roboto_env_instance is None:
            _roboto_env_instance = cls()
        return _roboto_env_instance

    action_inputs_manifest_file: typing.Optional[pathlib.Path] = pydantic.Field(
        default=None, alias="ROBOTO_ACTION_INPUTS_MANIFEST"
    )
    """Path to a JSON file holding the invocation's input manifest, from ``ROBOTO_ACTION_INPUTS_MANIFEST``."""

    action_parameters_file: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_ACTION_PARAMETERS_FILE")
    """Path to a JSON file of the invocation's parameter values, from ``ROBOTO_ACTION_PARAMETERS_FILE``."""

    action_runtime_config_dir: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_ACTION_RUNTIME_CONFIG_DIR"
    )
    """Directory of the invocation's runtime configuration, from ``ROBOTO_ACTION_RUNTIME_CONFIG_DIR``."""

    action_timeout: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_ACTION_TIMEOUT")
    """Number of seconds the invocation may run before Roboto cancels it, from ``ROBOTO_ACTION_TIMEOUT``."""

    api_key: typing.Optional[str] = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("ROBOTO_API_KEY", "ROBOTO_BEARER_TOKEN"),
    )
    """Access token, from ``ROBOTO_API_KEY``, or from ``ROBOTO_BEARER_TOKEN`` when that is unset."""

    cache_dir: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_CACHE_DIR")
    """Directory the SDK caches data from Roboto in, from ``ROBOTO_CACHE_DIR``.

    ``None`` uses the operating system's per-user cache directory."""

    config_file: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_CONFIG_FILE")
    """Path to the Roboto config file, from ``ROBOTO_CONFIG_FILE``. ``None`` reads ``~/.roboto/config.json``."""

    dataset_id: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_DATASET_ID")
    """ID of the dataset the invocation was invoked on, from ``ROBOTO_DATASET_ID``."""

    dataset_metadata_changeset_file: typing.Optional[str] = pydantic.Field(
        default=None,
        alias="ROBOTO_DATASET_METADATA_CHANGESET_FILE",
    )
    """Path to the dataset's tag and metadata changes file, from ``ROBOTO_DATASET_METADATA_CHANGESET_FILE``."""

    default_http_timeout: Timeout = pydantic.Field(default=NotSet, alias="ROBOTO_DEFAULT_HTTP_TIMEOUT")
    """Seconds to wait for a request to Roboto before giving up, from ``ROBOTO_DEFAULT_HTTP_TIMEOUT``.

    ``NotSet`` when the variable is unset, which uses the config file profile's ``default_http_timeout``, or 30
    seconds. A request that times out is sent again only when repeating it cannot apply a change twice, as with a GET.
    """

    dry_run: typing.Optional[bool] = pydantic.Field(default=False, alias="ROBOTO_DRY_RUN")
    """Whether the invocation is a dry run, from ``ROBOTO_DRY_RUN``. ``False`` when the variable is unset.

    ``roboto actions invoke-local --dry-run`` sets it, so an action can be tested without changing anything in
    Roboto. During a dry run, an action should skip side effects, such as:

    - Uploading files to datasets.
    - Changing metadata.
    - Requests to other services that change their state.

    Actions read it through :py:attr:`~roboto.action_runtime.InvocationContext.is_dry_run`.
    """

    file_metadata_changeset_file: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_FILE_METADATA_CHANGESET_FILE"
    )
    """Path to the file of tag and metadata changes for output files, from ``ROBOTO_FILE_METADATA_CHANGESET_FILE``."""

    input_dir: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_INPUT_DIR")
    """Directory the invocation's selected files are downloaded into, from ``ROBOTO_INPUT_DIR``."""

    invocation_id: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_INVOCATION_ID")
    """ID of the invocation, from ``ROBOTO_INVOCATION_ID``."""

    log_level: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_LOG_LEVEL")
    """Log level requested for the invocation, from ``ROBOTO_LOG_LEVEL``."""

    org_id: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_ORG_ID")
    """ID of the organization to act in, from ``ROBOTO_ORG_ID``."""

    output_dir: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_OUTPUT_DIR")
    """Directory for the action's output files, from ``ROBOTO_OUTPUT_DIR``."""

    profile: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_PROFILE")
    """Name of the config file profile to read, from ``ROBOTO_PROFILE``. ``None`` reads the file's default profile."""

    roboto_env: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_ENV")
    """Description of where the SDK runs, recorded on the files and directories it uploads, from ``ROBOTO_ENV``."""

    roboto_service_url: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_SERVICE_URL")
    """Deprecated. URL of the Roboto API, from ``ROBOTO_SERVICE_URL``.

    Use ``roboto_service_endpoint`` instead; the SDK never reads this field."""

    roboto_service_endpoint: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_SERVICE_ENDPOINT")
    """URL of the Roboto API to send requests to, from ``ROBOTO_SERVICE_ENDPOINT``.

    Applies when the access token comes from the environment. ``None`` uses ``https://api.roboto.ai``."""

    def get_env_var(self, var_name: str, default_value: typing.Optional[str] = None) -> typing.Optional[str]:
        """Return the current value of environment variable ``var_name``, or ``default_value`` when it is unset.

        Reads the process's environment at call time, not the values this instance parsed.

        Args:
            var_name: Name of the environment variable.
            default_value: Value to return when the variable is unset.
        """
        return os.getenv(var_name, default_value)
