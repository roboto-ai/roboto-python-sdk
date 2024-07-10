# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pathlib
import typing

import pydantic

from roboto import sentinels
from roboto.domain import datasets, files
from roboto.env import RobotoEnv, RobotoEnvKey
from roboto.logging import default_logger
from roboto.updates import MetadataChangeset

logger = default_logger()


class FilesChangesetItem(pydantic.BaseModel):
    relative_path: str
    update: files.UpdateFileRecordRequest


class FilesChangesetFileManager:
    __path: pathlib.Path

    def __init__(self):
        path_str = RobotoEnv.default().file_metadata_changeset_file
        if path_str is None:
            raise ValueError(
                "Couldn't locate expected file metadata changeset file from env var "
                + RobotoEnvKey.FileMetadataChangesetFile
            )

        path = pathlib.Path(path_str)
        if not path.exists():
            path.touch()

        self.__path = path

    def put_tags(self, relative_path: str, tags: list[str]):
        self.append_update(
            relative_path,
            files.UpdateFileRecordRequest(
                metadata_changeset=MetadataChangeset(put_tags=tags)
            ),
        )

    def remove_tags(self, relative_path: str, tags: list[str]):
        self.append_update(
            relative_path,
            files.UpdateFileRecordRequest(
                metadata_changeset=MetadataChangeset(remove_tags=tags)
            ),
        )

    def put_fields(self, relative_path: str, metadata: dict[str, typing.Any]):
        self.append_update(
            relative_path,
            files.UpdateFileRecordRequest(
                metadata_changeset=MetadataChangeset(put_fields=metadata)
            ),
        )

    def remove_fields(self, relative_path: str, keys: list[str]):
        self.append_update(
            relative_path,
            files.UpdateFileRecordRequest(
                metadata_changeset=MetadataChangeset(remove_fields=keys)
            ),
        )

    def set_description(self, relative_path: str, description: typing.Optional[str]):
        self.append_update(
            relative_path, files.UpdateFileRecordRequest(description=description)
        )

    def append_update(self, relative_path: str, update: files.UpdateFileRecordRequest):
        # Duplicates are OK, as we'll ignore them at upload time
        with open(self.__path, "a") as f:
            print(
                FilesChangesetItem(
                    relative_path=relative_path, update=update
                ).model_dump_json(),
                file=f,
            )

    def apply_to_dataset(self, dataset: datasets.Dataset):
        if RobotoEnv.default().output_dir is None:
            raise ValueError(
                "Couldn't apply changes with no specified output dir via env var "
                + RobotoEnvKey.OutputDir
            )

        with open(self.__path, "r") as f:
            lines = f.readlines()

        try:
            items = [FilesChangesetItem.model_validate_json(line) for line in lines]
        except pydantic.ValidationError as ve:
            logger.error(
                "Got malformed files metadata changeset file, ignoring.", exc_info=ve
            )
            return

        updates_by_path: dict[str, files.UpdateFileRecordRequest] = {}

        for item in items:
            existing_update = updates_by_path.get(item.relative_path)

            if existing_update is None:
                updates_by_path[item.relative_path] = item.update
            else:
                new_update = existing_update

                if sentinels.is_set(item.update.description):
                    new_update.description = item.update.description
                if sentinels.is_set(
                    existing_update.metadata_changeset
                ) and sentinels.is_set(item.update.metadata_changeset):
                    new_update.metadata_changeset = (
                        existing_update.metadata_changeset.combine(
                            item.update.metadata_changeset
                        )
                    )

                updates_by_path[item.relative_path] = new_update

        relevant_files: list[files.File] = []

        for dataset_file in dataset.list_files():
            if dataset_file.relative_path in updates_by_path.keys():
                relevant_files.append(dataset_file)

        if len(relevant_files) == 0:
            logger.info("No file metadata update requests")
        else:
            logger.info(
                f"Attempting to update metadata for {len(relevant_files)} files"
            )

        for relevant_file in relevant_files:
            update_by_path = updates_by_path[relevant_file.relative_path]
            relevant_file.update(
                description=update_by_path.description,
                metadata_changeset=update_by_path.metadata_changeset,
            )
