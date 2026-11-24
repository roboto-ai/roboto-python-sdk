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
"""URL of the Roboto API, used when neither ``ROBOTO_SERVICE_ENDPOINT`` nor a config file profile gives an endpoint."""


DEFAULT_ROBOTO_DIR = pathlib.Path.home() / ".roboto"
"""Directory where the Roboto CLI, SDK and upload agent keep their files: ``~/.roboto`` in the user's home directory."""

DEFAULT_ROBOTO_CONFIG_DIR = DEFAULT_ROBOTO_DIR / "config.json"
"""Path of the Roboto config file when ``ROBOTO_CONFIG_FILE`` is unset: ``~/.roboto/config.json``."""

DEFAULT_ROBOTO_PROFILE_NAME = "default"
"""Name of the config file profile used when neither the caller, ``ROBOTO_PROFILE``, nor the file names another."""


_CONFIG_ERROR_SUFFIX = (
    "For more information on setting up the config file used by Roboto's first-party tools, please refer to "
    + "https://docs.roboto.ai/getting-started/programmatic-access.html."
)


def resolve_cache_dir(env: RobotoEnv, ensure_exists: bool) -> pathlib.Path:
    """Return the directory under which the Roboto CLI and SDK cache data they download from Roboto.

    ``RobotoConfig.get_cache_dir`` finds the cache directory through it when the config sets no ``cache_dir``, so most
    code never calls it.

    Args:
        env: Roboto environment variables, whose ``ROBOTO_CACHE_DIR`` names the directory when set.
        ensure_exists: Whether to create the operating system's per-user cache directory when this returns it. A
            directory named by ``ROBOTO_CACHE_DIR`` is never created.

    Returns:
        ``ROBOTO_CACHE_DIR`` when set, otherwise the operating system's per-user cache directory for ``roboto``, such
        as ``~/.cache/roboto`` on Linux.
    """
    if env.cache_dir:
        return pathlib.Path(env.cache_dir)

    return platformdirs.user_cache_path(appname="roboto", ensure_exists=ensure_exists)


def resolve_config_file(env: RobotoEnv) -> pathlib.Path:
    """Return the path of the Roboto config file, which may not exist.

    ``RobotoConfig.from_env`` finds the file to read, and ``roboto auth login`` and ``roboto setup`` the file to write,
    through it, so most code never calls it.

    Args:
        env: Roboto environment variables, whose ``ROBOTO_CONFIG_FILE`` names the file when set.

    Returns:
        ``ROBOTO_CONFIG_FILE`` when set, otherwise ``~/.roboto/config.json``.
    """
    if env.config_file:
        return pathlib.Path(env.config_file)

    return DEFAULT_ROBOTO_CONFIG_DIR


def requested_profile_name(profile_override: typing.Optional[str], env: RobotoEnv) -> typing.Optional[str]:
    """Return the config file profile named by the caller or by ``ROBOTO_PROFILE``.

    ``RobotoConfig.from_env``, ``roboto auth login`` and ``roboto setup`` choose a profile through it, so most code
    never calls it.

    Args:
        profile_override: Profile the caller names, ahead of ``ROBOTO_PROFILE``. An empty value counts as none.
        env: Roboto environment variables, whose ``ROBOTO_PROFILE`` applies when ``profile_override`` names none.

    Returns:
        The profile's name, or ``None`` when neither names one, which selects the config file's default profile.
        ``ROBOTO_PROFILE`` set to an empty value names the ``default`` profile.
    """
    if profile_override:
        return profile_override
    if env.profile is None:
        return None
    return env.profile or DEFAULT_ROBOTO_PROFILE_NAME


def resolved_profile_name(requested: typing.Optional[str], default_profile: typing.Optional[str]) -> str:
    """Return the profile ``requested`` names, else the file's ``default_profile``, else ``default``.

    ``RobotoConfig.from_env`` chooses the profile to read, and ``roboto auth login`` and ``roboto setup`` the profile to
    save a new token to, through it, so most code never calls it.

    Args:
        requested: Profile the caller or ``ROBOTO_PROFILE`` names, from ``requested_profile_name``.
        default_profile: The config file's ``default_profile``, or ``None`` when it names none.
    """
    return requested or default_profile or DEFAULT_ROBOTO_PROFILE_NAME


class RobotoConfig(pydantic.BaseModel):
    """Settings for making requests to Roboto: an access token, the API endpoint, an HTTP timeout and a cache directory.

    Each profile in the Roboto config file holds these fields. ``from_env`` builds a config from the environment or
    from one of those profiles, and :py:meth:`~roboto.http.RobotoClient.from_config` builds a client from it.
    """

    api_key: str
    """Access token to authenticate requests with, such as a personal access token beginning with ``robo_pat_``."""

    cache_dir: typing.Optional[pathlib.Path] = None
    """Cache directory the ``roboto cache`` commands report on and clear.

    ``None`` uses the directory ``resolve_cache_dir`` returns.
    """

    default_http_timeout: Timeout = NotSet
    """Seconds to wait for each HTTP request to Roboto before giving up.

    ``None`` waits indefinitely, and ``NotSet`` uses the client's default of 30 seconds.
    """

    endpoint: str = ROBOTO_API_ENDPOINT
    """URL of the Roboto API to send requests to."""

    org_id: typing.Optional[str] = None
    """Organization to act in when the caller names none and ``ROBOTO_ORG_ID`` is unset.

    The CLI and :py:meth:`~roboto.roboto_search.RobotoSearch.from_env` read it. Only a member of several organizations
    needs it. ``roboto setup`` saves it to the config file profile; a config built from ``ROBOTO_API_KEY`` or
    ``ROBOTO_BEARER_TOKEN`` has none.
    """

    @classmethod
    def from_env(
        cls, profile_override: typing.Optional[str] = None, env: typing.Optional[RobotoEnv] = None
    ) -> "RobotoConfig":
        """Build a config from the access token in the environment, or else from a profile in the Roboto config file.

        A token in ``ROBOTO_API_KEY`` or ``ROBOTO_BEARER_TOKEN`` takes precedence, and is sent to the endpoint in
        ``ROBOTO_SERVICE_ENDPOINT``, or to ``https://api.roboto.ai`` when that is unset; the config file is then not
        read. Without a token, the config comes from a profile in the file at ``ROBOTO_CONFIG_FILE``, or
        ``~/.roboto/config.json`` when that is unset. In both cases, ``ROBOTO_CACHE_DIR`` and
        ``ROBOTO_DEFAULT_HTTP_TIMEOUT``, when set, supply ``cache_dir`` and ``default_http_timeout`` over any value in
        the profile.

        Args:
            profile_override: Config file profile to read, ahead of ``ROBOTO_PROFILE`` and the file's default profile.
                Ignored when the environment holds a token.
            env: Roboto environment variables to read. Defaults to the process's own, through
                :py:meth:`~roboto.env.RobotoEnv.default`.

        Raises:
            FileNotFoundError: No access token is set and the config file does not exist.
            OSError: The config file exists but cannot be read.
            ValueError: The config file is not a JSON object, holds no valid profile, or has no profile by the chosen
                name.

        Examples:
            Make requests to Roboto with the config file's ``prod`` profile:

            >>> from roboto.http import RobotoClient
            >>> config = RobotoConfig.from_env(profile_override="prod")
            >>> roboto_client = RobotoClient.from_config(config)
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

        default_profile: typing.Optional[str] = None
        profiles: dict[str, RobotoConfig] = {}

        # A file that fails validation as a v1 file is read in the earlier format, a JSON object mapping each profile
        # name to a profile. Entries of that object that are not valid profiles in that format are skipped.
        try:
            model = RobotoConfigFileV1.model_validate(config_file_dict)
            profiles = model.profiles
            default_profile = model.default_profile

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

        profile_name = resolved_profile_name(requested_profile_name(profile_override, env), default_profile)

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
        """Return the cache directory the ``roboto cache`` commands report on and clear.

        When ``cache_dir`` is ``None``, this sets it to the directory ``resolve_cache_dir`` returns, creating that
        directory when it is the operating system's per-user cache directory.
        """
        if self.cache_dir is None:
            self.cache_dir = resolve_cache_dir(RobotoEnv.default(), ensure_exists=True)

        return self.cache_dir


class RobotoConfigFileProfileV0(pydantic.BaseModel):
    """Profile in a Roboto config file of the earlier format, which maps each profile name directly to a profile.

    ``RobotoConfig.from_env`` reads a file in this format when it is not a valid ``RobotoConfigFileV1``. Such a file
    names no default profile, so the profile named ``default`` is used when neither the caller nor ``ROBOTO_PROFILE``
    names one.
    """

    token: str
    """Access token to authenticate requests with."""

    default_endpoint: str = ROBOTO_API_ENDPOINT
    """URL of the Roboto API to send requests to."""

    def to_config(self) -> RobotoConfig:
        """Return this profile as a ``RobotoConfig``, with ``token`` as its ``api_key``."""
        return RobotoConfig(api_key=self.token, endpoint=self.default_endpoint)


class RobotoConfigFileV1(pydantic.BaseModel):
    """Contents of a Roboto config file in the ``v1`` format, which lists its profiles under ``profiles``.

    ``RobotoConfig.from_env`` reads a file in this format, and ``roboto auth login`` and ``roboto setup`` write one.
    Building it raises ``pydantic.ValidationError`` when:

    - ``version`` is not ``"v1"``.
    - ``profiles`` is empty.
    - ``profiles`` has no profile by the name ``default_profile`` gives.
    """

    version: typing.Literal["v1"]
    """Format of the config file, always ``"v1"``."""

    profiles: dict[str, RobotoConfig]
    """Profiles keyed by name, each holding the settings for one access token and endpoint."""

    default_profile: typing.Optional[str] = DEFAULT_ROBOTO_PROFILE_NAME
    """Name of the profile to use when neither the caller nor ``ROBOTO_PROFILE`` names one.

    ``None`` uses the profile named ``default``.
    """

    @pydantic.model_validator(mode="after")
    def validate(self):
        """Reject a config file with no profiles, or whose default profile is not among them."""
        if len(self.profiles) == 0:
            raise ValueError("No profiles found in config file.")

        if (self.default_profile or DEFAULT_ROBOTO_PROFILE_NAME) not in self.profiles.keys():
            raise ValueError(f"Default profile '{self.default_profile}' was not found in config file.")

        return self
