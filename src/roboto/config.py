# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import pathlib
import typing

import platformdirs
import pydantic

from .env import RobotoEnv, Timeout
from .logging import default_logger
from .sentinels import NotSet, is_set

logger = default_logger()


ROBOTO_API_ENDPOINT = "https://api.roboto.ai"


DEFAULT_ROBOTO_DIR = pathlib.Path.home() / ".roboto"
DEFAULT_ROBOTO_CONFIG_DIR = DEFAULT_ROBOTO_DIR / "config.json"
DEFAULT_ROBOTO_PROFILE_NAME = "default"


_CONFIG_ERROR_SUFFIX = (
    "For more information on setting up the config file used by Roboto's first-party tools, please refer to "
    + "https://docs.roboto.ai/getting-started/programmatic-access.html."
)


def resolve_cache_dir(env: RobotoEnv, ensure_exists: bool) -> pathlib.Path:
    """Resolve the base directory under which the SDK caches files it fetches from Roboto.

    Prefers ``ROBOTO_CACHE_DIR`` from ``env``; absent that, the platform-conventional per-user cache directory.
    ``ensure_exists`` applies only to the platform default: when true, resolving it also creates the directory on disk.
    A directory supplied through ``ROBOTO_CACHE_DIR`` is returned as-is and never created here.
    """
    if env.cache_dir:
        return pathlib.Path(env.cache_dir)

    return platformdirs.user_cache_path(appname="roboto", ensure_exists=ensure_exists)


def resolve_config_file(env: RobotoEnv) -> pathlib.Path:
    """Resolve the path of the Roboto config file: ``ROBOTO_CONFIG_FILE`` from ``env``, else ``~/.roboto/config.json``.

    The file at the returned path may not exist.
    """
    if env.config_file:
        return pathlib.Path(env.config_file)

    return DEFAULT_ROBOTO_CONFIG_DIR


class RobotoConfig(pydantic.BaseModel):
    """
    RobotoConfig captures an ``api_key`` and ``endpoint`` required to programmatically
    interact with Roboto. Multiple profiles can be configured if desired.
    """

    api_key: str
    cache_dir: typing.Optional[pathlib.Path] = None
    default_http_timeout: Timeout = NotSet
    endpoint: str = ROBOTO_API_ENDPOINT

    org_id: typing.Optional[str] = None
    """Organization to act in when the caller names none and ``ROBOTO_ORG_ID`` is unset.
    The CLI and :py:meth:`~roboto.roboto_search.RobotoSearch.from_env` read it.
    Only a member of several organizations needs it. ``roboto setup`` saves it to the config file profile;
    a config built from ``ROBOTO_API_KEY`` or ``ROBOTO_BEARER_TOKEN`` has none."""

    @classmethod
    def from_env(
        cls, profile_override: typing.Optional[str] = None, env: typing.Optional[RobotoEnv] = None
    ) -> "RobotoConfig":
        """Build a config from the access token in the environment, or else from a profile in the Roboto config file.

        A token in ``ROBOTO_API_KEY`` or ``ROBOTO_BEARER_TOKEN`` takes precedence, and is sent to the endpoint in
        ``ROBOTO_SERVICE_ENDPOINT``, or to ``https://api.roboto.ai`` when that is unset. Without a token, the config
        comes from the file at ``ROBOTO_CONFIG_FILE``, or ``~/.roboto/config.json`` when that is unset. Either way,
        ``ROBOTO_CACHE_DIR`` and ``ROBOTO_DEFAULT_HTTP_TIMEOUT``, when set, override the profile's ``cache_dir`` and
        ``default_http_timeout``.

        Args:
            profile_override: Config file profile to read, ahead of ``ROBOTO_PROFILE`` and the file's default profile.
            env: Roboto environment variables to read. Defaults to the process's own, through ``RobotoEnv.default()``.

        Raises:
            FileNotFoundError: No access token is set and the config file doesn't exist.
            OSError: The config file exists but can't be read.
            ValueError: The config file isn't a JSON object, or has no usable profile by the chosen name.
        """
        if env is None:
            env = RobotoEnv.default()

        cache_dir_from_env = pathlib.Path(env.cache_dir) if env.cache_dir else None

        if env.api_key:
            endpoint = env.roboto_service_endpoint or ROBOTO_API_ENDPOINT

            return RobotoConfig(
                api_key=env.api_key,
                cache_dir=cache_dir_from_env,
                endpoint=endpoint,
                default_http_timeout=env.default_http_timeout,
            )

        config_file = resolve_config_file(env)
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
            raise ValueError(f"Roboto config file at path '{config_file}' is not valid JSON. " + _CONFIG_ERROR_SUFFIX)
        if not isinstance(config_file_dict, dict):
            raise ValueError(
                f"Roboto config file at path '{config_file}' is not a JSON object. " + _CONFIG_ERROR_SUFFIX
            )

        profile_name: typing.Optional[str] = env.profile
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
                        profiles[config_profile_name] = RobotoConfigFileProfileV0.model_validate(
                            config_profile
                        ).to_config()
                    except pydantic.ValidationError:
                        pass

        if len(profiles) == 0:
            raise ValueError(f"No user profiles found in config file '{config_file}'. " + _CONFIG_ERROR_SUFFIX)

        # If a profile name was explicitly passed to this function (for example when called in the CLI's entry.py),
        # that blows over anything else we've seen. Otherwise, use the profile name extracted from either
        # an env variable or the default_profile_name param of a config file.
        #
        # If none of those match, just fall back to the default profile name.
        profile_name = profile_override or profile_name or DEFAULT_ROBOTO_PROFILE_NAME

        if profile_name not in profiles.keys():
            raise ValueError(
                f"User profile '{profile_name}' was not found in config file '{config_file}'. " + _CONFIG_ERROR_SUFFIX
            )

        overrides: dict[str, typing.Any] = {}
        if cache_dir_from_env is not None:
            overrides["cache_dir"] = cache_dir_from_env
        if is_set(env.default_http_timeout):
            overrides["default_http_timeout"] = env.default_http_timeout
        return profiles[profile_name].model_copy(update=overrides)

    def get_cache_dir(self) -> pathlib.Path:
        if self.cache_dir is None:
            self.cache_dir = resolve_cache_dir(RobotoEnv.default(), ensure_exists=True)

        return self.cache_dir


class RobotoConfigFileProfileV0(pydantic.BaseModel):
    """V0 Roboto configuration file"""

    token: str
    default_endpoint: str = ROBOTO_API_ENDPOINT

    def to_config(self) -> RobotoConfig:
        return RobotoConfig(api_key=self.token, endpoint=self.default_endpoint)


class RobotoConfigFileV1(pydantic.BaseModel):
    """V1 Roboto configuration file"""

    version: typing.Literal["v1"]
    profiles: dict[str, RobotoConfig]
    default_profile: typing.Optional[str] = DEFAULT_ROBOTO_PROFILE_NAME

    @pydantic.model_validator(mode="after")
    def validate(self):
        if len(self.profiles) == 0:
            raise ValueError("No profiles found in config file.")

        if (self.default_profile or DEFAULT_ROBOTO_PROFILE_NAME) not in self.profiles.keys():
            raise ValueError(f"Default profile '{self.default_profile}' was not found in config file.")

        return self
