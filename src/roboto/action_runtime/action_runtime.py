# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pathlib
import typing

from ..domain import actions, datasets, orgs
from ..env import RobotoEnv
from ..http import RobotoClient
from .exceptions import ActionRuntimeException
from .file_changeset import (
    FilesChangesetFileManager,
)

_BAD_ENV_BLURB = (
    "This most likely means that you're not running in an action context, "
    + "and are testing a script on a developer machine."
)


class ActionRuntime:
    """
    A utility for performing common lookups and other operations during a Roboto action's runtime. The easiest and
    most common way to initialize this is:

    >>> from roboto import ActionRuntime
    >>> action_runtime = ActionRuntime.from_env()

    ...which will inspect environment variables to initialize the ActionRuntime.

    If you want to test a script using ActionRuntime in a setting such as a developer machine or unit test,
    and you don't want to set environment variables to mirror Roboto's remote execution environment,
    you can also initialize ActionRuntime directly like:

    >>> import pathlib
    >>> from roboto import ActionRuntime
    >>>
    >>> action_runtime = ActionRuntime(
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
    __org_id: str
    __org: typing.Optional[orgs.Org] = None
    __output_dir: pathlib.Path

    @classmethod
    def from_env(cls) -> "ActionRuntime":
        """
        Initializes an ActionRuntime based on values in environment variables. This will throw an exception if
        any required environment variables are not available. All of these will be available at runtime in Roboto's
        remote execution environment.

        Example:
            >>> from roboto import ActionRuntime
            >>> action_runtime = ActionRuntime.from_env()
        """
        env = RobotoEnv.default()

        if not env.dataset_id:
            raise ActionRuntimeException(
                "Couldn't find dataset_id from environment. " + _BAD_ENV_BLURB
            )

        if not env.invocation_id:
            raise ActionRuntimeException(
                "Couldn't find invocation_id from environment. " + _BAD_ENV_BLURB
            )

        if not env.org_id:
            raise ActionRuntimeException(
                "Couldn't find org_id from environment. " + _BAD_ENV_BLURB
            )

        if not env.input_dir:
            raise ActionRuntimeException(
                "Couldn't find input_dir from environment. " + _BAD_ENV_BLURB
            )

        input_dir = pathlib.Path(env.input_dir)

        if not input_dir.is_dir():
            raise ActionRuntimeException(
                f"Input directory '{input_dir}' does not exist."
            )

        if not env.output_dir:
            raise ActionRuntimeException(
                "Couldn't find output_dir from environment. " + _BAD_ENV_BLURB
            )

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
            roboto_client=RobotoClient.from_env(),
        )

    def __init__(
        self,
        dataset_id: str,
        input_dir: pathlib.Path,
        invocation_id: str,
        org_id: str,
        output_dir: pathlib.Path,
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

        >>> from roboto import ActionRuntime
        >>> action_runtime = ActionRuntime.from_env()
        >>> action_runtime.dataset.put_tags(["tagged_by_action"])
        >>> action_runtime.dataset.put_metadata({"voltage_spikes_seen": 693})
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
        tags and metadata with the yet-to-be-uploaded files in this invocation's output directory. In practice, you
        might use this like:

        >>> from roboto import ActionRuntime
        >>> action_runtime = ActionRuntime.from_env()
        >>>
        >>> my_output_file = action_runtime.output_dir / "nested" / "my_output_file.txt"
        >>> my_output_file.write_text("Hello World")
        >>>
        >>> action_runtime.file_changeset_manager.put_tags("nested/my_output_file.txt", ["tagged_by_action"])
        >>> action_runtime.file_changeset_manager.put_fields(
        ... "nested/my_output_file.txt", {"roboto_proficiency": "extreme - I can annotate output files!"}
        ... )

        This only works for files that don't exist yet. To tag existing files (such as files in the input directory),
        you should instead use:

        >>> from roboto import ActionRuntime
        >>> action_runtime = ActionRuntime.from_env()
        >>>
        >>> existing_file = action_runtime.dataset.get_file_by_path("some_file_that_already_exists.txt")
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
