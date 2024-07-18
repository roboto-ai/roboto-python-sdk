# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import pathlib
import typing

import pydantic

from .env import RobotoEnv
from .logging import default_logger

logger = default_logger()


ROBOTO_API_ENDPOINT = "https://api.roboto.ai"


DEFAULT_ROBOTO_DIR = pathlib.Path.home() / ".roboto"
DEFAULT_ROBOTO_CONFIG_DIR = DEFAULT_ROBOTO_DIR / "config.json"
DEFAULT_ROBOTO_PROFILE_NAME = "default"


_CONFIG_ERROR_SUFFIX = (
    "For more information on setting up the config file used by Roboto's first-party tools, please refer to "
    + "https://docs.roboto.ai/getting-started/programmatic-access.html."
)


class RobotoConfig(pydantic.BaseModel):
    api_key: str
    endpoint: str = ROBOTO_API_ENDPOINT

    @classmethod
    def from_env(cls, profile_override: typing.Optional[str] = None) -> "RobotoConfig":
        default_env = RobotoEnv.default()

        # If ROBOTO_API_KEY or ROBOTO_BEARER_TOKEN are provided, use that api_key, and either get the endpoint
        # from the environment, or use the default endpoint
        if default_env.api_key:
            endpoint = default_env.roboto_service_endpoint or ROBOTO_API_ENDPOINT

            return RobotoConfig(api_key=default_env.api_key, endpoint=endpoint)

        # Try to read a Roboto config file, either from an env variable specified location, or the default location
        # ~/.roboto/config.json
        if default_env.config_file:
            config_file = pathlib.Path(default_env.config_file)
        else:
            config_file = DEFAULT_ROBOTO_CONFIG_DIR

        if not config_file.is_file():
            raise FileNotFoundError(
                f"No Roboto config file found at specified path '{config_file}'. This may mean that a "
                + "config file was never created, or that your ROBOTO_CONFIG_FILE override environment "
                + "variable is set incorrectly. "
                + _CONFIG_ERROR_SUFFIX
            )

        try:
            config_file_dict = json.loads(config_file.read_text())
        except json.JSONDecodeError:
            raise ValueError(
                f"Roboto config file at path '{config_file}' is not valid JSON. "
                + _CONFIG_ERROR_SUFFIX
            )

        profile_name: typing.Optional[str] = default_env.profile
        profiles: dict[str, RobotoConfig] = {}

        # First try to interpret it as a V1 new-style config file
        try:
            model = RobotoConfigFileV1.model_validate(config_file_dict)
            profiles = model.profiles
            if model.default_profile is not None and profile_name is None:
                profile_name = model.default_profile

        # If that doesn't work, interpret the config file as a list of profiles (V0 format)
        except pydantic.ValidationError:
            for config_profile_name, config_profile in config_file_dict.items():
                if type(config_profile) is dict:
                    try:
                        profiles[config_profile_name] = (
                            RobotoConfigFileProfileV0.model_validate(
                                config_profile
                            ).to_config()
                        )
                    except pydantic.ValidationError:
                        pass

        if len(profiles) == 0:
            raise ValueError(
                f"No user profiles found in config file '{config_file}'. "
                + _CONFIG_ERROR_SUFFIX
            )

        # If a profile name was explicitly passed to this function (for example when called in the CLI's entry.py),
        # that blows over anything else we've seen. Otherwise, use the profile name extracted from either
        # an env variable or the default_profile_name param of a config file.
        #
        # If none of those match, just fall back to the default profile name.
        profile_name = profile_override or profile_name or DEFAULT_ROBOTO_PROFILE_NAME

        if profile_name not in profiles.keys():
            raise ValueError(
                f"User profile '{profile_name}' was not found in config file '{config_file}'. "
                + _CONFIG_ERROR_SUFFIX
            )

        return profiles[profile_name]


class RobotoConfigFileProfileV0(pydantic.BaseModel):
    token: str
    default_endpoint: str = ROBOTO_API_ENDPOINT

    def to_config(self) -> RobotoConfig:
        return RobotoConfig(api_key=self.token, endpoint=self.default_endpoint)


class RobotoConfigFileV1(pydantic.BaseModel):
    version: typing.Literal["v1"]
    profiles: dict[str, RobotoConfig]
    default_profile: typing.Optional[str] = DEFAULT_ROBOTO_PROFILE_NAME

    @pydantic.model_validator(mode="after")
    def validate(self):
        if len(self.profiles) == 0:
            raise ValueError("No profiles found in config file.")

        if (
            self.default_profile or DEFAULT_ROBOTO_PROFILE_NAME
        ) not in self.profiles.keys():
            raise ValueError(
                f"Default profile '{self.default_profile}' was not found in config file."
            )

        return self
