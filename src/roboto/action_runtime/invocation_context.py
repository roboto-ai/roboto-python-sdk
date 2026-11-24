# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import logging
import os
import pathlib
import typing
import urllib.request

from ..domain import (
    actions,
    datasets,
    orgs,
    secrets,
)
from ..env import RobotoEnv, RobotoEnvKey
from ..http import RobotoClient
from ..logging import default_logger
from .action_input import (
    ActionInput,
    ActionInputRecord,
)
from .exceptions import ActionRuntimeException
from .file_changeset import (
    FilesChangesetFileManager,
)

log = default_logger()

_MANIFEST_FETCH_TIMEOUT_S = 30
"""Number of seconds to wait for the input manifest at ``ROBOTO_ACTION_INPUTS_URL``.

Long enough to download a manifest of several megabytes, short enough that a stalled request does not use up the
invocation's timeout."""


def _fetch(url: str) -> str:
    """Fetch the body of a signed URL as text.

    Uses ``urllib`` rather than ``RobotoClient`` because the URL carries its own authorization.
    """
    with urllib.request.urlopen(url, timeout=_MANIFEST_FETCH_TIMEOUT_S) as response:  # noqa: S310
        return typing.cast(bytes, response.read()).decode("utf-8")


def _raise_for_missing_env_var(var_name: str, env_var_name: str) -> typing.NoReturn:
    raise ActionRuntimeException(
        f"Could not find {var_name} from environment. Expected environment variable '{env_var_name}'. "
        "This most likely means you're testing an action outside of Roboto's hosted compute environment, "
        "and the action's runtime environment was not fully setup."
    )


def _raise_for_missing_file(contents: str) -> typing.NoReturn:
    raise ActionRuntimeException(
        f"Could not find file expected to contain {contents}. "
        "This most likely means you're testing an action outside of Roboto's hosted compute environment, "
        "and the action's runtime environment was not fully setup."
    )


class InvocationContext:
    """Context of a running invocation, which an action's code uses to read its inputs, parameters, and secrets.

    It also fetches the invocation, its dataset, and its organization from Roboto, and sets tags and metadata on the
    files the action writes to its output directory.

    Inside Roboto, build one with ``from_env``, which reads the environment variables Roboto sets for an action's
    code. To run the action's code elsewhere, such as in a unit test, build one directly instead, for example
    ``InvocationContext(dataset_id="ds_12345", input_dir=pathlib.Path("input"), invocation_id="iv_12345",
    org_id="og_12345", output_dir=pathlib.Path("output"))``.

    Args:
        dataset_id: ID of the dataset the invocation was invoked on.
        input_dir: Directory Roboto downloads the invocation's selected files into, when it downloads them.
        invocation_id: ID of the invocation.
        org_id: ID of the organization the invocation belongs to.
        output_dir: Directory for the action's output files.
        input_data_manifest_file: Path to a JSON file holding the invocation's input manifest, which ``get_input``
            reads when neither ``ROBOTO_ACTION_INPUTS`` nor ``ROBOTO_ACTION_INPUTS_URL`` is set. ``None`` makes
            ``get_input`` raise in that case.
        parameters_file: Path to a JSON file of the invocation's parameter values. ``None`` treats every parameter
            as unset.
        secrets_file: Path to a JSON file of the values of the parameters that name secrets. ``None`` makes
            ``get_secret_parameter`` raise.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
        dry_run: Whether the invocation is a dry run, in which the action should skip side effects.
        log_level: Name of the log level requested for the invocation: ``ERROR``, ``WARNING``, ``INFO`` or
            ``DEBUG``. ``None`` requests ``INFO``.
    """

    __dataset_id: str
    __dataset: typing.Optional[datasets.Dataset] = None
    __dry_run: bool
    __file_changeset_manager: typing.Optional[FilesChangesetFileManager] = None
    __input_dir: pathlib.Path
    __invocation_id: str
    __invocation: typing.Optional[actions.Invocation] = None
    __log_level: typing.Optional[str]
    __roboto_client: RobotoClient
    __org_id: str
    __org: typing.Optional[orgs.Org] = None
    __output_dir: pathlib.Path
    __input_data_manifest_file: typing.Optional[pathlib.Path]
    __parameters_file: typing.Optional[pathlib.Path]
    __secrets_file: typing.Optional[pathlib.Path]

    # Parsed contents of the parameters and secrets files, read on first use.
    __parameters_cache: typing.Optional[dict[str, typing.Any]] = None
    __secrets_cache: typing.Optional[dict[str, str]] = None

    @classmethod
    def from_env(cls) -> "InvocationContext":
        """Build an InvocationContext from the environment variables Roboto sets for an action's code.

        It requires ``ROBOTO_DATASET_ID``, ``ROBOTO_INVOCATION_ID``, ``ROBOTO_ORG_ID``, ``ROBOTO_INPUT_DIR`` and
        ``ROBOTO_OUTPUT_DIR``, and also reads ``ROBOTO_ACTION_INPUTS_MANIFEST``, ``ROBOTO_ACTION_PARAMETERS_FILE``,
        ``ROBOTO_ACTION_RUNTIME_CONFIG_DIR`` (whose ``secrets.json`` is the secrets file), ``ROBOTO_DRY_RUN`` and
        ``ROBOTO_LOG_LEVEL``. Roboto sets all the required ones when it runs the action. The client comes from
        :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            ActionRuntimeException: A required environment variable is unset, or the input or output directory does
                not exist.

        Examples:
            >>> from roboto import InvocationContext
            >>> context = InvocationContext.from_env()
        """

        env = RobotoEnv.default()

        if not env.dataset_id:
            _raise_for_missing_env_var("dataset id", RobotoEnvKey.DatasetId)

        if not env.invocation_id:
            _raise_for_missing_env_var("invocation id", RobotoEnvKey.InvocationId)

        if not env.org_id:
            _raise_for_missing_env_var("org id", RobotoEnvKey.OrgId)

        if not env.input_dir:
            _raise_for_missing_env_var("input directory", RobotoEnvKey.InputDir)

        input_dir = pathlib.Path(env.input_dir)

        if not input_dir.is_dir():
            raise ActionRuntimeException(f"Input directory '{input_dir}' does not exist.")

        if not env.output_dir:
            _raise_for_missing_env_var("output directory", RobotoEnvKey.OutputDir)

        output_dir = pathlib.Path(env.output_dir)

        if not output_dir.is_dir():
            raise ActionRuntimeException(f"Output directory '{output_dir}' does not exist.")

        parameters_file = pathlib.Path(env.action_parameters_file) if env.action_parameters_file else None

        secrets_file = None
        if env.action_runtime_config_dir:
            secrets_file = pathlib.Path(env.action_runtime_config_dir) / "secrets.json"

        return cls(
            dataset_id=env.dataset_id,
            input_dir=input_dir,
            invocation_id=env.invocation_id,
            org_id=env.org_id,
            output_dir=output_dir,
            input_data_manifest_file=env.action_inputs_manifest_file,
            parameters_file=parameters_file,
            secrets_file=secrets_file,
            roboto_client=RobotoClient.from_env(),
            dry_run=bool(env.dry_run),
            log_level=env.log_level,
        )

    def __init__(
        self,
        dataset_id: str,
        input_dir: pathlib.Path,
        invocation_id: str,
        org_id: str,
        output_dir: pathlib.Path,
        input_data_manifest_file: typing.Optional[pathlib.Path] = None,
        parameters_file: typing.Optional[pathlib.Path] = None,
        secrets_file: typing.Optional[pathlib.Path] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        dry_run: bool = False,
        log_level: typing.Optional[str] = None,
    ):
        self.__dataset = None
        self.__dataset_id = dataset_id
        self.__dry_run = dry_run
        self.__file_changeset_manager = None
        self.__input_dir = input_dir
        self.__invocation = None
        self.__invocation_id = invocation_id
        self.__log_level = log_level
        self.__org = None
        self.__org_id = org_id
        self.__output_dir = output_dir
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__input_data_manifest_file = input_data_manifest_file
        self.__parameters_file = parameters_file
        self.__secrets_file = secrets_file
        self.__parameters_cache = None
        self.__secrets_cache = None

    @property
    def dataset_id(self) -> str:
        """ID of the dataset the invocation was invoked on.

        When the invocation names no dataset, it is a placeholder that matches no dataset, and ``dataset`` raises.
        """
        return self.__dataset_id

    @property
    def dataset(self) -> datasets.Dataset:
        """Dataset the invocation was invoked on, fetched from Roboto on first access and cached.

        Use it to set tags or metadata on the dataset while the action runs, as in
        ``context.dataset.put_tags(["tagged_by_action"])``.

        Accessing it raises :py:class:`~roboto.action_runtime.ActionRuntimeException` when the invocation names no
        dataset, as when the action runs locally, runs from a scheduled trigger, or is invoked from the CLI with
        query-based input data. It raises ``RobotoNotFoundException`` when no dataset has ``dataset_id``.
        """
        if self.__dataset is None:
            UNSPECIFIED_DATASET_ID = actions.InvocationDataSource.unspecified().data_source_id
            if self.dataset_id == UNSPECIFIED_DATASET_ID:
                raise ActionRuntimeException(
                    "No dataset is associated with this invocation. "
                    "This occurs when running locally, using scheduled triggers, "
                    "or invoking via CLI with query-based input data."
                )

            self.__dataset = datasets.Dataset.from_id(self.__dataset_id, roboto_client=self.__roboto_client)
        return self.__dataset

    @property
    def file_changeset_manager(self) -> FilesChangesetFileManager:
        """Manager of the tags and metadata to set on the files the action writes to its output directory.

        Roboto applies them after it uploads the output directory. Name each file by its path relative to
        ``output_dir``, as in ``context.file_changeset_manager.put_tags("result.txt", ["tagged_by_action"])``. To
        tag a file already in Roboto, use the file's own methods instead, as in
        ``context.dataset.get_file_by_path("result.txt").put_tags(["tagged_by_action"])``.

        Built on first access. Accessing it raises ``ValueError`` when ``ROBOTO_FILE_METADATA_CHANGESET_FILE`` is
        unset, as it usually is outside Roboto.
        """
        if self.__file_changeset_manager is None:
            self.__file_changeset_manager = FilesChangesetFileManager()
        return self.__file_changeset_manager

    @property
    def input_dir(self) -> pathlib.Path:
        """Directory Roboto downloads the invocation's selected files into, when it downloads them."""
        return self.__input_dir

    @property
    def invocation_id(self) -> str:
        """ID of the invocation."""
        return self.__invocation_id

    @property
    def invocation(self) -> actions.Invocation:
        """Invocation, fetched from Roboto on first access and cached.

        Accessing it raises ``RobotoNotFoundException`` when no invocation has ``invocation_id``.
        """
        if self.__invocation is None:
            self.__invocation = actions.Invocation.from_id(self.__invocation_id, roboto_client=self.__roboto_client)
        return self.__invocation

    @property
    def is_dry_run(self) -> bool:
        """Whether the invocation is a dry run, in which the action should skip side effects."""
        return self.__dry_run

    @property
    def log_level(self) -> int:
        """Log level requested for the invocation, as a ``logging`` constant such as ``logging.DEBUG``.

        ``logging.INFO`` when no level was requested, or when the requested name is not one of ``ERROR``,
        ``WARNING``, ``INFO`` and ``DEBUG``, in capitals.

        Note:
            Roboto does not apply the level. Pass it to ``logging.getLogger().setLevel()`` for it to take effect.
        """
        if self.__log_level is None:
            return logging.INFO

        log_level_name_to_constant = {
            "ERROR": logging.ERROR,
            "WARNING": logging.WARNING,
            "INFO": logging.INFO,
            "DEBUG": logging.DEBUG,
        }
        return log_level_name_to_constant.get(self.__log_level, logging.INFO)

    @property
    def org_id(self) -> str:
        """ID of the organization the invocation belongs to."""
        return self.__org_id

    @property
    def org(self) -> orgs.Org:
        """Organization the invocation belongs to, fetched from Roboto on first access and cached.

        Accessing it raises ``RobotoNotFoundException`` when no organization has ``org_id``.
        """
        if self.__org is None:
            self.__org = orgs.Org.from_id(self.__org_id, roboto_client=self.__roboto_client)
        return self.__org

    @property
    def output_dir(self) -> pathlib.Path:
        """Directory for the action's output files.

        After the action's code exits with code 0, Roboto uploads every file in it to the invocation's upload
        destination (:py:attr:`~roboto.domain.actions.InvocationRecord.upload_destination`).
        """
        return self.__output_dir

    @property
    def roboto_client(self) -> RobotoClient:
        """Client this context makes requests to Roboto with."""
        return self.__roboto_client

    def get_input(self) -> ActionInput:
        """Return the files, sessions, and topics the invocation was invoked on.

        Reads the invocation's input manifest from the first of these that is set:

        1. ``ROBOTO_ACTION_INPUTS``, which holds the manifest itself.
        2. ``ROBOTO_ACTION_INPUTS_URL``, from which it downloads the manifest.
        3. ``input_data_manifest_file``, given when the context was built.

        It reads the two environment variables even on a context built directly. When the manifest file is missing or
        empty, it returns an empty :py:class:`~roboto.action_runtime.ActionInput`, and logs a warning for a missing
        one.

        Raises:
            ActionRuntimeException: Neither environment variable is set, and the context has no
                ``input_data_manifest_file``.
            pydantic.ValidationError: The manifest is not a valid input manifest.
        """
        inline = os.environ.get(RobotoEnvKey.ActionInputs.value)
        if inline:
            # Set where no setup step writes a manifest file the action's code can read, so there is no file to
            # fall back to; checked first for that reason.
            return ActionInput.from_record(ActionInputRecord.model_validate_json(inline), self.__roboto_client)

        manifest_url = os.environ.get(RobotoEnvKey.ActionInputsUrl.value)
        if manifest_url:
            # The same manifest, set in place of ROBOTO_ACTION_INPUTS when it is too large for an environment
            # variable.
            return ActionInput.from_record(
                ActionInputRecord.model_validate_json(_fetch(manifest_url)), self.__roboto_client
            )

        if self.__input_data_manifest_file is None:
            raise ActionRuntimeException("Couldn't find action input manifest file")

        # prepare_invocation_input_data writes the manifest before the action's code starts, an empty one when the
        # invocation has no inputs, so a missing file means that step failed to write it. Return empty input rather
        # than fail, and log a warning so the action does not run on empty input unnoticed.
        if not self.__input_data_manifest_file.is_file():
            log.warning(
                "Action input manifest %s not found; defaulting to empty input. "
                "Setup is expected to always write this file.",
                self.__input_data_manifest_file,
            )
            return ActionInput()

        # An empty manifest is the legitimate no-input state; resolve it to empty input silently.
        if self.__input_data_manifest_file.stat().st_size == 0:
            return ActionInput()

        input_record = ActionInputRecord.model_validate_json(self.__input_data_manifest_file.read_text())

        return ActionInput.from_record(input_record, self.__roboto_client)

    def get_optional_parameter(self, name: str, default_value: typing.Optional[str] = None) -> typing.Optional[str]:
        """Return the value of an action parameter, or ``default_value`` when the invocation did not set it.

        A value that is not a string is converted with ``str()``. A value that names a secret returns the secret's
        value from the secrets file instead, as ``get_secret_parameter`` does. A context with no parameters file
        returns ``default_value`` for every parameter.

        Args:
            name: Name of the parameter.
            default_value: Value to return when the invocation did not set the parameter.

        Raises:
            ActionRuntimeException: The parameters file cannot be read or does not hold a JSON object, or the value
                names a secret that ``get_secret_parameter`` cannot read.

        Examples:
            Read ``model_version``, or ``"latest"`` when the invocation did not set it:

            >>> import roboto
            >>> context = roboto.InvocationContext.from_env()
            >>> model_version = context.get_optional_parameter("model_version", "latest")
        """
        if self.__parameters_file is None:
            return default_value

        parameter_value = self.__parameters.get(name)

        if parameter_value is None:
            return default_value

        if not isinstance(parameter_value, str):
            parameter_value = str(parameter_value)

        if not secrets.is_secret_uri(parameter_value):
            return parameter_value
        else:
            return self.get_secret_parameter(name)

    def get_parameter(self, name: str) -> str:
        """Return the value of an action parameter, which the invocation must set.

        Reads the value as ``get_optional_parameter`` does, and its failures also apply.

        Args:
            name: Name of the parameter.

        Raises:
            ActionRuntimeException: The invocation did not set the parameter, or the context has no parameters file.
        """
        value = self.get_optional_parameter(name)
        if value is None:
            raise ActionRuntimeException(
                f"Could not find parameter '{name}'. "
                "This most likely means you're testing an action outside of Roboto's hosted compute environment, "
                "and the parameter was not provided."
            )
        return value

    def get_secret_parameter(self, name: str) -> str:
        """Return the value of the secret an action parameter names, read from the secrets file.

        Args:
            name: Name of the parameter.

        Raises:
            ActionRuntimeException: The secrets file holds no value, or an empty one, for the parameter; the context
                has no secrets file; or the file cannot be read or does not hold a JSON object.
        """
        value = self.__secrets.get(name)

        if not value:
            raise ActionRuntimeException(
                f"Couldn't find value for secret parameter '{name}' in secrets file '{self.__secrets_file}'."
            )
        return value

    @property
    def __parameters(self) -> dict[str, typing.Any]:
        """Parameter values in the parameters file, read on first access and cached."""
        if self.__parameters_cache is None:
            if self.__parameters_file is None:
                _raise_for_missing_file("parameters")

            self.__parameters_cache = self.__load_runtime_data_from_file(self.__parameters_file)
        return self.__parameters_cache

    @property
    def __secrets(self) -> dict[str, str]:
        """Secret values in the secrets file, read on first access and cached."""
        if self.__secrets_cache is None:
            if self.__secrets_file is None:
                _raise_for_missing_file("secrets")

            self.__secrets_cache = self.__load_runtime_data_from_file(self.__secrets_file)
        return self.__secrets_cache

    def __load_runtime_data_from_file(self, file_path: pathlib.Path) -> dict[str, typing.Any]:
        """Read the JSON object in a parameters or secrets file.

        Raises ``ActionRuntimeException`` when the file cannot be read or parsed, or its root is not an object.
        """
        result: dict[str, typing.Any] = {}

        try:
            loaded_data = json.loads(file_path.read_text())
        except Exception:
            raise ActionRuntimeException(f"Failed to load {file_path}")
        else:
            if isinstance(loaded_data, dict):
                result = loaded_data
            else:
                raise ActionRuntimeException(
                    f"Expected {file_path} to contain JSON with an object at its root, found: {type(loaded_data)}"
                )

        return result


class ActionRuntime(InvocationContext):
    """Deprecated. Context of a running invocation, under its former name.

    Use :py:class:`~roboto.action_runtime.InvocationContext` instead, which takes the same arguments. Building one
    logs a deprecation warning.
    """

    def __init__(self, *args, **kwargs):
        log.warning(
            "The ActionRuntime utility has been renamed to InvocationContext and is deprecated. "
            "It will be removed in a future release."
        )

        super().__init__(*args, **kwargs)
