# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import json
import pathlib
import typing

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


def _raise_for_missing_env_var(var_name: str, env_var_name: str) -> typing.NoReturn:
    raise ActionRuntimeException(
        f"Could not find {var_name} from environment. Expected environment variable '{env_var_name}'. "
        "This most likely means you're testing an action using a script on a developer machine, "
        "and the script leaves this environment variable unset."
    )


class InvocationContext:
    """A utility for performing common lookups and other operations during a Roboto Action's runtime.

    The easiest and most common way to initialize this is:
    >>> from roboto import InvocationContext
    >>> context = InvocationContext.from_env()

    ...which will inspect environment variables to initialize the InvocationContext.

    If you want to test a script using InvocationContext in a setting such as a developer machine or unit test,
    and you don't want to set environment variables to mirror Roboto's remote execution environment,
    initialize InvocationContext directly:

    >>> import pathlib
    >>> from roboto import InvocationContext
    >>> context = InvocationContext(
    ...     dataset_id="ds_XXXXXXXXXXXX",
    ...     input_dir=pathlib.Path("/path/to/local/input/dir"),
    ...     invocation_id="iv_XXXXXXXXXXXX",
    ...     org_id="og_XXXXXXXXXXXX",
    ...     output_dir=pathlib.Path("/path/to/local/output/dir"),
    ... )
    """

    __dataset_id: str
    __dataset: typing.Optional[datasets.Dataset] = None
    __file_changeset_manager: typing.Optional[FilesChangesetFileManager] = None
    __input_dir: pathlib.Path
    __invocation_id: str
    __invocation: typing.Optional[actions.Invocation] = None
    __roboto_client: RobotoClient
    __roboto_env: RobotoEnv
    __org_id: str
    __org: typing.Optional[orgs.Org] = None
    __output_dir: pathlib.Path

    @classmethod
    def from_env(cls) -> "InvocationContext":
        """Initialize an InvocationContext from values in environment variables.
        Will throw an exception if any required environment variables are not available.

        All required environment variables will be available at runtime
        when an action is running in Roboto's remote execution environment.

        Example:
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
            raise ActionRuntimeException(
                f"Input directory '{input_dir}' does not exist."
            )

        if not env.output_dir:
            _raise_for_missing_env_var("output directory", RobotoEnvKey.OutputDir)

        output_dir = pathlib.Path(env.output_dir)

        if not output_dir.is_dir():
            raise ActionRuntimeException(
                f"Output directory '{output_dir}' does not exist."
            )

        return cls(
            dataset_id=env.dataset_id,
            input_dir=input_dir,
            invocation_id=env.invocation_id,
            org_id=env.org_id,
            output_dir=output_dir,
            roboto_env=env,
            roboto_client=RobotoClient.from_env(),
        )

    def __init__(
        self,
        dataset_id: str,
        input_dir: pathlib.Path,
        invocation_id: str,
        org_id: str,
        output_dir: pathlib.Path,
        roboto_env: RobotoEnv,
        roboto_client: typing.Optional[RobotoClient] = None,
    ):
        self.__dataset = None
        self.__dataset_id = dataset_id
        self.__file_changeset_manager = None
        self.__input_dir = input_dir
        self.__invocation = None
        self.__invocation_id = invocation_id
        self.__org = None
        self.__org_id = org_id
        self.__output_dir = output_dir
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__roboto_env = roboto_env

    @property
    def dataset_id(self) -> str:
        """
        The ID of the dataset whose data this action is operating on.
        """
        return self.__dataset_id

    @property
    def dataset(self) -> datasets.Dataset:
        """
        A :class:`~roboto.domain.datasets.Dataset` object for the dataset whose data this action is operating on.

        This object will be lazy-initialized the first time it is accessed, which might result in a
        :class:`~roboto.exceptions.domain.RobotoNotFoundException` if the dataset does not exist.
        After the first call, the dataset will be cached.

        This is particularly useful for adding tags or metadata to a dataset at runtime, for example:

        >>> from roboto import InvocationContext
        >>> context = InvocationContext.from_env()
        >>> context.dataset.put_tags(["tagged_by_action"])
        >>> context.dataset.put_metadata({"voltage_spikes_seen": 693})
        """
        if self.__dataset is None:
            self.__dataset = datasets.Dataset.from_id(
                self.__dataset_id, roboto_client=self.__roboto_client
            )
        return self.__dataset

    @property
    def file_changeset_manager(self) -> FilesChangesetFileManager:
        """
        A :class:`~roboto.action_runtime.file_changeset.FilesChangesetFileManager` which can be used to associate
        tags and metadata with the yet-to-be-uploaded files in this invocation's output directory.
        In practice, you might use this like:

        >>> from roboto import InvocationContext
        >>> context = InvocationContext.from_env()
        >>> my_output_file = context.output_dir / "my_output_file.txt"
        >>> my_output_file.write_text("Hello World")
        >>> context.file_changeset_manager.put_tags(my_output_file.name, ["tagged_by_action"])
        >>> context.file_changeset_manager.put_fields(
        ... my_output_file.name, {"roboto_proficiency": "extreme - I can annotate output files!"}
        ... )

        This only works for files that have not yet been uploaded to Roboto.
        To tag existing files, you should instead use:

        >>> from roboto import InvocationContext
        >>> context = InvocationContext.from_env()
        >>> existing_file = context.dataset.get_file_by_path("some_file_that_already_exists.txt")
        >>> existing_file.put_tags(["tagged_by_action"])
        >>> existing_file.put_metadata({"roboto_proficiency": "also extreme - I can annotate input files!"})

        For more info, see the top-level docs on the FilesChangesetFileManager class.
        """
        if self.__file_changeset_manager is None:
            self.__file_changeset_manager = FilesChangesetFileManager()
        return self.__file_changeset_manager

    @property
    def input_dir(self) -> pathlib.Path:
        """
        The directory where the action's input files are located.
        """
        return self.__input_dir

    @property
    def invocation_id(self) -> str:
        """
        The ID of the currently running action invocation.
        """
        return self.__invocation_id

    @property
    def invocation(self) -> actions.Invocation:
        """
        An :class:`~roboto.domain.actions.Invocation` object for the currently running action invocation.

        This object will be lazy-initialized the first time it is accessed, which might result in a
        :class:`~roboto.exceptions.domain.RobotoNotFoundException` if the invocation does not exist.
        After the first call, the invocation will be cached.
        """
        if self.__invocation is None:
            self.__invocation = actions.Invocation.from_id(
                self.__invocation_id, roboto_client=self.__roboto_client
            )
        return self.__invocation

    @property
    def org_id(self) -> str:
        """
        The ID of the org which invoked the currently running action.
        """
        return self.__org_id

    @property
    def org(self) -> orgs.Org:
        """
        An :class:`~roboto.domain.orgs.Org` object for the org which invoked the currently running action.

        This object will be lazy-initialized the first time it is accessed, which might result in a
        :class:`~roboto.exceptions.domain.RobotoNotFoundException` if the org does not exist.
        After the first call, the org will be cached.
        """
        if self.__org is None:
            self.__org = orgs.Org.from_id(
                self.__org_id, roboto_client=self.__roboto_client
            )
        return self.__org

    @property
    def output_dir(self) -> pathlib.Path:
        """
        The directory where the action's output files are expected. After the user portion of the action runtime
        concludes (i.e. when their container exits with a 0 exit code), every file in this directory will be uploaded
        to the dataset associated with this action invocation.
        """
        return self.__output_dir

    @property
    def roboto_client(self) -> RobotoClient:
        """
        The :class:`~roboto.http.RobotoClient` instance used by this action runtime.
        """
        return self.__roboto_client

    def get_input(self) -> ActionInput:
        """
        Instance of :class:`~roboto.action_runtime.ActionInput` containing resolved references to input data.
        """
        action_inputs_manifest_file = self.__roboto_env.action_inputs_manifest_file
        if action_inputs_manifest_file is None:
            raise ActionRuntimeException("Couldn't find action input manifest file")

        if action_inputs_manifest_file.stat().st_size == 0:
            return ActionInput()

        input_record = ActionInputRecord.model_validate_json(
            action_inputs_manifest_file.read_text()
        )

        return ActionInput.from_record(input_record, self.__roboto_client)

    def get_optional_parameter(
        self, name: str, default_value: typing.Optional[str] = None
    ) -> typing.Optional[str]:
        """
        Retrieve the value of the action parameter with the given name,
        defaulting to `default_value` if the parameter is not set.

        Args:
            name: The name of the parameter to retrieve.
            default_value: The value to return if the parameter is not set. Defaults to None.

        Returns:
            The parameter value, or default_value if not set.
            If the value is a secret URI, returns the resolved secret value.

        Examples:
            >>> import roboto
            >>> context = roboto.InvocationContext.from_env()
            >>> context.get_optional_parameter("model_version", "latest")
            "latest"
        """
        parameter_env_name = RobotoEnvKey.for_parameter(name)
        parameter_value = self.__roboto_env.get_env_var(
            parameter_env_name, default_value
        )

        if parameter_value is None or not secrets.is_secret_uri(parameter_value):
            return parameter_value
        else:
            return self.get_secret_parameter(name)

    def get_parameter(self, name: str) -> str:
        """
        Gets the value of the action parameter with the given name,
        raising an `ActionRuntimeException` if the parameter is not set.
        """
        parameter_env_name = RobotoEnvKey.for_parameter(name)
        parameter_value = self.__roboto_env.get_env_var(parameter_env_name)
        if parameter_value is None:
            _raise_for_missing_env_var(f"parameter '{name}'", parameter_env_name)

        if not secrets.is_secret_uri(parameter_value):
            return parameter_value
        else:
            return self.get_secret_parameter(name)

    def get_secret_parameter(self, name: str) -> str:
        """
        Gets the value of the secret action parameter with the given name.
        """
        if self.__roboto_env.action_runtime_config_dir is None:
            _raise_for_missing_env_var(
                "action runtime config dir", RobotoEnvKey.ActionRuntimeConfigDir
            )

        secrets_file = (
            pathlib.Path(self.__roboto_env.action_runtime_config_dir) / "secrets.json"
        )
        if not secrets_file.exists():
            raise ActionRuntimeException(
                f"Secrets file '{secrets_file}' does not exist."
            )

        secrets_dict = json.loads(secrets_file.read_text())

        value = secrets_dict.get(name, "")

        if not value:
            raise ActionRuntimeException(
                f"Couldn't find value for secret parameter '{name}' in secrets file '{secrets_file}'."
            )
        return value


class ActionRuntime(InvocationContext):
    """Deprecated. Use InvocationContext instead."""

    def __init__(self, *args, **kwargs):
        log.warning(
            "The ActionRuntime utility has been renamed to InvocationContext and is deprecated. "
            "It will be removed in a future release."
        )

        super().__init__(*args, **kwargs)
