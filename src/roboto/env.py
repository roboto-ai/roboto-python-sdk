# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum
import os
import re
import typing

import pydantic
import pydantic_settings

ROBOTO_ENV_VAR_PREFIX = "ROBOTO_"


def resolve_env_variables(value: str):
    """
    Given any input string, resolves any environment variables in the string against the current environment.
    """
    resolved_value = value

    # Left side of | is $MY_ENV_VAR style, right side is ${MY_ENV_VAR}
    #
    # Each side has the actual variable name inside an inner capture group (separate from $ or ${}) to make it easier
    # to pass to os.getenv
    pattern = re.compile(r"(\$(\w+))|(\$\{(\w+)})")
    matches = pattern.findall(resolved_value)

    for match in matches:
        left, left_word, right, right_word = match

        if left != "" and left_word != "":
            resolved_value = resolved_value.replace(left, os.getenv(left_word, ""))

        if right != "" and right_word != "":
            resolved_value = resolved_value.replace(right, os.getenv(right_word, ""))

    return resolved_value


class RobotoEnvKey(str, enum.Enum):
    ActionParametersFile = f"{ROBOTO_ENV_VAR_PREFIX}ACTION_PARAMETERS_FILE"
    ActionTimeout = f"{ROBOTO_ENV_VAR_PREFIX}ACTION_TIMEOUT"
    ApiKey = f"{ROBOTO_ENV_VAR_PREFIX}API_KEY"
    BearerToken = f"{ROBOTO_ENV_VAR_PREFIX}BEARER_TOKEN"
    """Interchangable with ApiKey"""
    ConfigFile = f"{ROBOTO_ENV_VAR_PREFIX}CONFIG_FILE"
    DatasetMetadataChangesetFile = (
        f"{ROBOTO_ENV_VAR_PREFIX}DATASET_METADATA_CHANGESET_FILE"
    )
    DatasetId = f"{ROBOTO_ENV_VAR_PREFIX}DATASET_ID"
    FileMetadataChangesetFile = f"{ROBOTO_ENV_VAR_PREFIX}FILE_METADATA_CHANGESET_FILE"
    InputDir = f"{ROBOTO_ENV_VAR_PREFIX}INPUT_DIR"
    InvocationId = f"{ROBOTO_ENV_VAR_PREFIX}INVOCATION_ID"
    OrgId = f"{ROBOTO_ENV_VAR_PREFIX}ORG_ID"
    OutputDir = f"{ROBOTO_ENV_VAR_PREFIX}OUTPUT_DIR"
    Profile = f"{ROBOTO_ENV_VAR_PREFIX}PROFILE"
    RobotoEnv = f"{ROBOTO_ENV_VAR_PREFIX}ENV"
    RobotoServiceUrl = f"{ROBOTO_ENV_VAR_PREFIX}SERVICE_URL"
    """Deprecated, use RobotoServiceEndpoint instead. Left here until 0.3.3 is released so we can migrate
    existing actions to use the new env var."""
    RobotoServiceEndpoint = f"{ROBOTO_ENV_VAR_PREFIX}SERVICE_ENDPOINT"

    @staticmethod
    def for_parameter(param_name: str) -> str:
        return f"{ROBOTO_ENV_VAR_PREFIX}PARAM_{param_name}"


_roboto_env_instance: typing.Optional["RobotoEnv"] = None


# You'll notice that the alias values here are duplicates of the RobotoEnvKey values. This is not ideal, but is
# necessary for type checking, because the value of alias needs to be a string literal and not a de-referenced variable.
# Even using f-strings will break the type checking.
class RobotoEnv(pydantic_settings.BaseSettings):
    @classmethod
    def default(cls) -> "RobotoEnv":
        # We need to keep this module level vs. as a class variable, because otherwise pydantic will cast it to a
        # ModelPrivateAttr
        global _roboto_env_instance
        if _roboto_env_instance is None:
            _roboto_env_instance = cls()
        return _roboto_env_instance

    action_parameters_file: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_ACTION_PARAMETERS_FILE"
    )

    action_timeout: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_ACTION_TIMEOUT"
    )

    api_key: typing.Optional[str] = pydantic.Field(
        default=None,
        validation_alias=pydantic.AliasChoices("ROBOTO_API_KEY", "ROBOTO_BEARER_TOKEN"),
    )

    config_file: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_CONFIG_FILE"
    )
    """
    An override for the location of a roboto config file. If not provided, the default ~/.roboto/config.json will be
    used (subject to RobotoConfig's implementation)
    """

    dataset_id: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_DATASET_ID"
    )

    dataset_metadata_changeset_file: typing.Optional[str] = pydantic.Field(
        default=None,
        alias="ROBOTO_DATASET_METADATA_CHANGESET_FILE",
    )

    file_metadata_changeset_file: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_FILE_METADATA_CHANGESET_FILE"
    )

    input_dir: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_INPUT_DIR"
    )

    invocation_id: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_INVOCATION_ID"
    )

    org_id: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_ORG_ID")

    output_dir: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_OUTPUT_DIR"
    )

    profile: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_PROFILE")
    """
    The profile name to use if getting RobotoConfig from a config file.
    """

    roboto_env: typing.Optional[str] = pydantic.Field(default=None, alias="ROBOTO_ENV")

    roboto_service_url: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_SERVICE_URL"
    )
    """Deprecated, use roboto_service_endpoint instead. Left here until 0.3.3 is released so we can migrate
    existing actions to use the new env var."""

    roboto_service_endpoint: typing.Optional[str] = pydantic.Field(
        default=None, alias="ROBOTO_SERVICE_ENDPOINT"
    )
    """A Roboto Service API endpoint to send requests to, typically https://api.roboto.ai"""
