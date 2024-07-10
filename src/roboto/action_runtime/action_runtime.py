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

BAD_ENV_BLURB = (
    "This most likely means that you're not running in an action context, "
    + "and are testing a script on a developer machine."
)


class ActionRuntime:
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
        env = RobotoEnv.default()

        if not env.dataset_id:
            raise ActionRuntimeException(
                "Couldn't find dataset_id from environment. " + BAD_ENV_BLURB
            )

        if not env.invocation_id:
            raise ActionRuntimeException(
                "Couldn't find invocation_id from environment. " + BAD_ENV_BLURB
            )

        if not env.org_id:
            raise ActionRuntimeException(
                "Couldn't find org_id from environment. " + BAD_ENV_BLURB
            )

        if not env.input_dir:
            raise ActionRuntimeException(
                "Couldn't find input_dir from environment. " + BAD_ENV_BLURB
            )

        input_dir = pathlib.Path(env.input_dir)

        if not input_dir.is_dir():
            raise ActionRuntimeException(
                f"Input directory '{input_dir}' does not exist."
            )

        if not env.output_dir:
            raise ActionRuntimeException(
                "Couldn't find output_dir from environment. " + BAD_ENV_BLURB
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
        return self.__dataset_id

    @property
    def dataset(self) -> datasets.Dataset:
        if self.__dataset is None:
            self.__dataset = datasets.Dataset.from_id(
                self.__dataset_id, roboto_client=self.__roboto_client
            )
        return self.__dataset

    @property
    def file_changeset_manager(self) -> FilesChangesetFileManager:
        if self.__file_changeset_manager is None:
            self.__file_changeset_manager = FilesChangesetFileManager()
        return self.__file_changeset_manager

    @property
    def input_dir(self) -> pathlib.Path:
        return self.__input_dir

    @property
    def invocation_id(self) -> str:
        return self.__invocation_id

    @property
    def invocation(self) -> actions.Invocation:
        if self.__invocation is None:
            self.__invocation = actions.Invocation.from_id(
                self.__invocation_id, roboto_client=self.__roboto_client
            )
        return self.__invocation

    @property
    def org_id(self) -> str:
        return self.__org_id

    @property
    def org(self) -> orgs.Org:
        if self.__org is None:
            self.__org = orgs.Org.from_id(
                self.__org_id, roboto_client=self.__roboto_client
            )
        return self.__org

    @property
    def output_dir(self) -> pathlib.Path:
        return self.__output_dir
