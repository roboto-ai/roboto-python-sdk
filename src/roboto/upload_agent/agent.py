# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing

import pydantic

from .. import Collection
from ..config import DEFAULT_ROBOTO_DIR
from ..domain import datasets
from ..env import resolve_env_variables
from ..http import RobotoClient
from ..logging import default_logger
from ..time import utcnow
from ..updates import MetadataChangeset
from .files import (
    UPLOAD_COMPLETE_FILENAME,
    UPLOAD_IN_PROGRESS_FILENAME,
    UploadAgentConfig,
    UploadCompleteFile,
    UploadConfigFile,
    UploadInProgressFile,
)

logger = default_logger()


DEFAULT_ROBOTO_UPLOAD_FILE = DEFAULT_ROBOTO_DIR / "default_roboto_upload.json"
"""Path of the template file ``UploadAgent.create_upload_configs`` copies into each directory.

It is ``~/.roboto/default_roboto_upload.json``.
"""


class UploadAgent:
    """Service that uploads directories on local disk to Roboto datasets.

    A directory is queued for upload when it holds an upload config file, named by
    :py:attr:`~roboto.upload_agent.files.UploadAgentConfig.upload_config_filename`. ``create_upload_configs`` writes
    those files, and ``process_uploads`` uploads the directories that have one.

    Args:
        agent_config: Directories to scan, the name of the upload config file, and what to delete after an upload.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
        default_roboto_upload_file: Template file ``create_upload_configs`` copies into each directory. ``None`` uses
            ``DEFAULT_ROBOTO_UPLOAD_FILE``.
    """

    __roboto_client: RobotoClient
    __agent_config: UploadAgentConfig
    __default_roboto_upload_file: pathlib.Path

    def __init__(
        self,
        agent_config: UploadAgentConfig,
        roboto_client: typing.Optional[RobotoClient] = None,
        default_roboto_upload_file: typing.Optional[pathlib.Path] = None,
    ):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__agent_config = agent_config
        self.__default_roboto_upload_file = default_roboto_upload_file or DEFAULT_ROBOTO_UPLOAD_FILE

    def create_upload_configs(self):
        """Write an upload config file into each directory directly under a search path that has none.

        A directory is skipped when it is empty or already holds an upload config file, an upload-in-progress file,
        or an upload-complete file. Search paths that are not directories are skipped.

        Each file written is a copy of the template at ``default_roboto_upload_file``, with each ``$NAME`` and
        ``${NAME}`` replaced by the value of environment variable ``NAME``. When the template is missing or cannot be
        read or parsed, each file holds a config with every field at its default.
        """
        directories_to_consider: list[pathlib.Path] = []

        for search_path in self.__agent_config.search_paths:
            if not search_path.is_dir():
                continue

            directories_to_consider.extend([subdir for subdir in search_path.iterdir() if subdir.is_dir()])

        upload_config_file_contents = UploadConfigFile()
        if self.__default_roboto_upload_file.is_file():
            try:
                upload_config_file_contents = UploadConfigFile.model_validate_json(
                    resolve_env_variables(self.__default_roboto_upload_file.read_text())
                )
                logger.info(
                    "Successfully loaded default config file %s, using it for new uploads.",
                    self.__default_roboto_upload_file,
                )
            except Exception:
                logger.warning(
                    "Couldn't parse default config file at %s, using blank contents '{}' instead.",
                    self.__default_roboto_upload_file,
                )
        else:
            logger.info(
                "No default upload config file found at %s, using blank contents '{}' instead.",
                self.__default_roboto_upload_file,
            )

        for subdir in directories_to_consider:
            if len(list(subdir.iterdir())) == 0:
                logger.info("Directory %s is empty, skipping", subdir)
                continue

            upload_config_file = subdir / self.__agent_config.upload_config_filename
            if upload_config_file.is_file():
                logger.info("Directory %s already has an upload config file, skipping", subdir)
                continue

            upload_in_progress_file = subdir / UPLOAD_IN_PROGRESS_FILENAME
            if upload_in_progress_file.is_file():
                logger.info("Directory %s has an upload in progress file, skipping", subdir)
                continue

            upload_complete_file = subdir / UPLOAD_COMPLETE_FILENAME
            if upload_complete_file.is_file():
                logger.info("Directory %s has an upload completed file, skipping", subdir)
                continue

            upload_config_file.write_text(upload_config_file_contents.model_dump_json(indent=2))
            logger.info("Wrote upload config file to %s", upload_config_file)

    def process_uploads(self, merge_uploads: bool = False) -> collections.abc.Sequence[datasets.Dataset]:
        """Upload each directory that holds an upload config file, and return the datasets uploaded to.

        Upload config files are found by searching each search path recursively; a file that cannot be parsed is
        logged and skipped. For each directory, in order:

        1. Skip it if it holds an upload-complete file.
        2. Choose its dataset: the one named by its upload-in-progress file, so an interrupted upload resumes into
           the dataset it started; otherwise the merged dataset, with ``merge_uploads``; otherwise a new dataset built
           from the config file's ``dataset`` section.
        3. Write an upload-in-progress file naming that dataset.
        4. Upload the directory's files, filtered by the config file's ``include_patterns`` and ``exclude_patterns``.
           Uploaded files are deleted from disk when the config file's ``delete_uploaded_files`` says so, or, when it
           is unset, the agent config's.
        5. Delete the upload config file, write an upload-complete file, delete the upload-in-progress file, then
           upload the upload-complete file to the dataset.
        6. With the agent config's ``delete_empty_directories``, remove the directory if nothing but the
           upload-complete file is left in it.
        7. Add the dataset to each collection in the config file's ``add_to_collections``. A failure is logged and
           does not stop the run.

        A failure in steps 2 to 6 stops the run. A directory that got past step 3 keeps a marker file, so the next run
        resumes it into the same dataset or, once its upload-complete file is written, skips it.

        Args:
            merge_uploads: Whether to upload every directory into one new dataset, created in the agent config's
                ``default_org_id``. Each directory's config file then updates that dataset: its description replaces
                the dataset's, an unset one clearing it, its metadata and tags are added, and its
                ``add_to_collections`` is ignored. ``False`` uploads each directory to its own dataset.

        Returns:
            With ``merge_uploads``, the merged dataset. Otherwise, each dataset this call created or resumed an
            upload into.

        Raises:
            RobotoNotFoundException: An upload-in-progress file names a dataset that no longer exists, or that the
                caller cannot see.
        """

        upload_config_files = self.__get_upload_config_files()
        if len(upload_config_files) == 0:
            logger.info("No upload config files found under any search path, nothing to do.")
            return []
        else:
            logger.info(
                "Found %d total upload config files across all search paths, starting uploads.",
                len(upload_config_files),
            )

        update_dataset: typing.Optional[datasets.Dataset] = None
        created_datasets: list[datasets.Dataset] = []

        if merge_uploads:
            update_dataset = datasets.Dataset.create(
                roboto_client=self.__roboto_client,
                caller_org_id=self.__agent_config.default_org_id,
            )

            created_datasets.append(update_dataset)

        for upload_config_file, path in upload_config_files:
            uploaded_dataset = self.__handle_upload_config_file(
                file=upload_config_file, path=path, update_dataset=update_dataset
            )

            if uploaded_dataset is not None:
                created_datasets.append(uploaded_dataset)

                if upload_config_file.dataset.add_to_collections is not None:
                    for collection_id in upload_config_file.dataset.add_to_collections:
                        try:
                            collection = Collection.from_id(collection_id, roboto_client=self.__roboto_client)
                            collection.add_dataset(uploaded_dataset.dataset_id)
                            logger.info(
                                "Added dataset %s to collection %s",
                                uploaded_dataset.dataset_id,
                                collection_id,
                            )
                        except Exception:
                            # Any failure is logged and skipped: the dataset is already uploaded, and the other
                            # collections and directories still proceed.
                            logger.error(
                                "Failed to add dataset %s to collection %s",
                                uploaded_dataset.dataset_id,
                                collection_id,
                            )

        return created_datasets

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
            for upload_config_file in search_path.rglob(self.__agent_config.upload_config_filename):
                try:
                    parsed_file = UploadConfigFile.model_validate_json(upload_config_file.read_text())

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
                logger.info("No upload config files found for search path: %s", search_path)
            else:
                logger.info(
                    "Found %d upload config files under search path: %s",
                    found,
                    search_path,
                )

        return upload_config_files

    def __delete_uploaded_dir_if_safe(self, path: pathlib.Path):
        """Remove ``path`` if it is empty or holds only the upload-complete file."""
        if not path.is_dir():
            return

        files = [f for f in path.iterdir()]

        if len(files) > 1:
            return

        if len(files) == 1:
            if files[0].name != UPLOAD_COMPLETE_FILENAME:
                return

            files[0].unlink(missing_ok=True)

        path.rmdir()

        logger.info("Cleaned up empty upload directory %s", path)

    def __handle_upload_config_file(
        self,
        file: UploadConfigFile,
        path: pathlib.Path,
        update_dataset: typing.Optional[datasets.Dataset] = None,
    ) -> typing.Optional[datasets.Dataset]:
        """Upload the directory holding the upload config file at ``path``, as ``process_uploads`` describes.

        Returns ``None`` when the directory was already uploaded or ``update_dataset`` is given, since the caller
        already holds that dataset.
        """
        dir_to_upload = path.parent

        upload_in_progress_file = dir_to_upload / UPLOAD_IN_PROGRESS_FILENAME
        upload_complete_file = dir_to_upload / UPLOAD_COMPLETE_FILENAME

        if upload_complete_file.is_file():
            try:
                parsed_complete_file = UploadCompleteFile.model_validate_json(upload_complete_file.read_text())
                logger.info(
                    "Found upload-complete file for dataset %s at path %s, skipping upload",
                    parsed_complete_file.dataset_id,
                    upload_complete_file.resolve(),
                )
            except pydantic.ValidationError:
                logger.warning(
                    "Couldn't parse file as a valid upload-complete file. Still ignoring upload to be safe, but "
                    + "it might not have worked: %s",
                    upload_in_progress_file,
                )

            return None

        in_progress_dataset: typing.Optional[datasets.Dataset] = None

        if upload_in_progress_file.is_file():
            try:
                parsed_in_progress_file = UploadInProgressFile.model_validate_json(upload_in_progress_file.read_text())
                in_progress_dataset = datasets.Dataset.from_id(parsed_in_progress_file.dataset_id)
                logger.warning(
                    "Found upload-in-progress file for dataset %s at path %s, resuming upload",
                    in_progress_dataset.dataset_id,
                    upload_in_progress_file.resolve(),
                )
            except pydantic.ValidationError:
                logger.warning(
                    "Couldn't parse file as a valid upload-in-progress file, ignoring: %s",
                    upload_in_progress_file,
                )

        dataset: datasets.Dataset
        should_write_in_progress_file: bool

        # An upload-in-progress file wins over update_dataset: an earlier run already chose this directory's dataset
        # and was interrupted before it finished.
        if in_progress_dataset is not None:
            dataset = in_progress_dataset
            should_write_in_progress_file = False

        elif update_dataset is not None:
            logger.info(
                "Applying update to existing dataset %s for directory: %s",
                update_dataset.dataset_id,
                dir_to_upload,
            )
            dataset = update_dataset
            dataset.update(
                description=file.dataset.description,
                metadata_changeset=MetadataChangeset(
                    put_fields=file.dataset.metadata,
                    put_tags=file.dataset.tags,
                ),
            )
            logger.info("Successfully updated dataset %s", dataset.dataset_id)
            should_write_in_progress_file = True

        else:
            logger.info("Creating a dataset for directory: %s", dir_to_upload)
            dataset = datasets.Dataset.create(
                description=file.dataset.description,
                metadata=file.dataset.metadata,
                tags=file.dataset.tags,
                caller_org_id=file.dataset.org_id,
                roboto_client=self.__roboto_client,
            )
            logger.info("Created dataset %s for path %s", dataset.dataset_id, path)
            should_write_in_progress_file = True

        if should_write_in_progress_file:
            logger.debug("Writing in progress file to %s", upload_in_progress_file.resolve())
            upload_in_progress_file.write_text(
                UploadInProgressFile(
                    version="v1",
                    dataset_id=dataset.dataset_id,
                    started=dataset.record.created,
                ).model_dump_json(indent=2)
            )

        delete_uploaded_files = self.__agent_config.delete_uploaded_files
        if file.upload.delete_uploaded_files is not None:
            delete_uploaded_files = file.upload.delete_uploaded_files

        logger.info(
            "Uploading files from %s to dataset %s. Delete after upload is %s",
            dir_to_upload,
            dataset.dataset_id,
            delete_uploaded_files,
        )

        exclude_patterns = file.upload.exclude_patterns or []
        # The upload-in-progress file stays local; the upload-complete file is uploaded on its own below.
        exclude_patterns.append(f"**/{UPLOAD_IN_PROGRESS_FILENAME}")

        dataset.upload_directory(
            directory_path=dir_to_upload,
            exclude_patterns=exclude_patterns,
            include_patterns=file.upload.include_patterns,
            delete_after_upload=delete_uploaded_files,
        )

        if path.is_file():
            logger.info("Deleting marker file %s", path)
            path.unlink(missing_ok=True)

        logger.debug("Writing upload complete file to %s", upload_complete_file.resolve())
        upload_complete_file.write_text(
            UploadCompleteFile(version="v1", dataset_id=dataset.dataset_id, completed=utcnow()).model_dump_json(
                indent=2
            )
        )

        # Delete the upload-in-progress file only once the upload-complete file exists, so an interrupted run leaves
        # one of the two and no later run uploads the directory to a second dataset.
        upload_in_progress_file.unlink(missing_ok=True)

        # Uploaded after every other file, so a trigger can treat its arrival as a sign that the directory is fully
        # uploaded. It also records which dataset the directory went to, and when.
        dataset.upload_file(upload_complete_file, UPLOAD_COMPLETE_FILENAME)

        logger.info(f"Upload completed, view at {self.__roboto_client.frontend_endpoint}/datasets/{dataset.dataset_id}")

        if self.__agent_config.delete_empty_directories:
            self.__delete_uploaded_dir_if_safe(dir_to_upload)

        if update_dataset is not None:
            return None

        return dataset
