# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing

import pydantic

from ..domain import datasets
from ..http import RobotoClient
from ..logging import default_logger
from .files import (
    UploadAgentConfig,
    UploadConfigFile,
)

logger = default_logger()


class UploadAgent:
    __roboto_client: RobotoClient
    __agent_config: UploadAgentConfig

    def __init__(
        self,
        aegnt_config: UploadAgentConfig,
        roboto_client: typing.Optional[RobotoClient] = None,
    ):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__agent_config = aegnt_config

    def run(self) -> collections.abc.Sequence[datasets.Dataset]:
        upload_config_files = self.__get_upload_config_files()
        if len(upload_config_files) == 0:
            logger.info(
                "No upload config files found under any search path, nothing to do."
            )
            return []
        else:
            logger.info(
                "Found %d total upload config files across all search paths, starting uploads.",
                len(upload_config_files),
            )

        uploaded_datasets: list[datasets.Dataset] = []

        for upload_config_file, path in upload_config_files:
            uploaded_datasets.append(
                self.__handle_upload_config_file(upload_config_file, path)
            )

        return uploaded_datasets

    def __get_upload_config_files(
        self,
    ) -> collections.abc.Collection[tuple[UploadConfigFile, pathlib.Path]]:
        upload_config_files: list[tuple[UploadConfigFile, pathlib.Path]] = []

        for search_path in self.__agent_config.search_paths:
            if not search_path.is_dir():
                logger.error("Search path is not a directory: %s", search_path)
                continue

            found = 0

            logger.info("Scanning '%s' for upload config files", search_path)
            for upload_config_file in search_path.rglob(
                self.__agent_config.upload_config_filename
            ):
                try:
                    parsed_file = UploadConfigFile.model_validate_json(
                        upload_config_file.read_text()
                    )

                    logger.info("Found upload config file: %s", upload_config_file)
                    upload_config_files.append((parsed_file, upload_config_file))
                    found += 1
                except pydantic.ValidationError as exc:
                    logger.error(
                        "Couldn't parse file as valid upload config files: %s",
                        upload_config_file,
                        exc_info=exc,
                    )

            if found == 0:
                logger.info(
                    "No upload config files found for search path: %s", search_path
                )
            else:
                logger.info(
                    "Found %d upload config files under search path: %s",
                    found,
                    search_path,
                )

        return upload_config_files

    def __handle_upload_config_file(
        self, file: UploadConfigFile, path: pathlib.Path
    ) -> datasets.Dataset:
        logger.info("Creating a dataset for directory: %s", path.parent)
        dataset = datasets.Dataset.create(
            description=file.dataset.description,
            metadata=file.dataset.metadata,
            tags=file.dataset.tags,
            caller_org_id=file.dataset.org_id,
            roboto_client=self.__roboto_client,
        )

        # Default to using the delete-uploaded-files strategy from the agent config file, but override it if it
        # has been explicitly set in the upload file.
        delete_uploaded_files = self.__agent_config.delete_uploaded_files
        if file.upload.delete_uploaded_files is not None:
            delete_uploaded_files = file.upload.delete_uploaded_files

        logger.info(
            "Created dataset %s, uploading files from %s. Delete after upload is %s",
            dataset.dataset_id,
            path.parent,
            delete_uploaded_files,
        )
        dataset.upload_directory(
            directory_path=path.parent,
            exclude_patterns=file.upload.exclude_patterns,
            delete_after_upload=delete_uploaded_files,
        )

        if path.is_file():
            logger.info("Deleting marker file %s", path)
            path.unlink()

        logger.info(
            f"Upload completed, view at https://app.roboto.ai/datasets/{dataset.dataset_id}"
        )

        return dataset
