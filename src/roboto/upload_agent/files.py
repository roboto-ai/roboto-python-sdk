# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import pathlib
import typing

import pydantic

from ..domain.datasets import CreateDatasetRequest

UPLOAD_COMPLETE_FILENAME = ".roboto_upload_complete.json"
"""Name of the file the upload agent writes into a directory it has uploaded, holding an ``UploadCompleteFile``."""

UPLOAD_IN_PROGRESS_FILENAME = ".roboto_upload_in_progress.json"
"""Name of the file the upload agent writes into a directory it is uploading, holding an ``UploadInProgressFile``."""


class UploadConfigFileDatasetSection(CreateDatasetRequest):
    """Settings for the dataset a directory is uploaded to, from the ``dataset`` section of an upload config file.

    Carried in ``UploadConfigFile.dataset``. The upload agent creates the dataset with ``description``, ``metadata``
    and ``tags``, and ignores ``name``, ``device_id`` and ``custom_fields``. When
    :py:meth:`~roboto.upload_agent.agent.UploadAgent.process_uploads` merges every directory into one dataset
    (``roboto-agent run --merge-uploads``), it applies ``description``, ``metadata`` and ``tags`` to that dataset as
    an update, and ignores ``org_id`` and ``add_to_collections``. Building it raises ``pydantic.ValidationError`` when
    ``name`` is longer than 120 characters.
    """

    org_id: typing.Optional[str] = None
    """Organization to create the dataset in.

    Required when the caller belongs to more than one organization; otherwise the caller's only organization.
    """

    add_to_collections: typing.Optional[typing.List[str]] = None
    """IDs of the collections to add the dataset to once its upload finishes. ``None`` adds it to none.

    The agent logs each collection it cannot add the dataset to and goes on to the next.
    """


class UploadConfigFileUploadSection(pydantic.BaseModel):
    """Settings for which files the upload agent uploads, from the ``upload`` section of an upload config file.

    Carried in ``UploadConfigFile.upload``. Both pattern lists are passed to
    :py:meth:`~roboto.domain.datasets.Dataset.upload_directory`, which describes how they match.
    """

    delete_uploaded_files: typing.Optional[bool] = None
    """Whether to delete the directory's local files once they are uploaded.

    ``None`` uses ``UploadAgentConfig.delete_uploaded_files``.
    """

    exclude_patterns: typing.Optional[typing.List[str]] = None
    """Gitignore-style patterns for the files to skip. ``None`` skips none.

    The agent never uploads its ``.roboto_upload_in_progress.json`` file, whatever the patterns.
    """

    include_patterns: typing.Optional[typing.List[str]] = None
    """Gitignore-style patterns for the files to upload. ``None`` uploads every file; an empty list uploads none."""


class UploadConfigFile(pydantic.BaseModel):
    """Contents of an upload config file, which marks a directory for the upload agent to upload.

    The agent looks for files by the name ``UploadAgentConfig.upload_config_filename`` gives (``.roboto_upload.json``
    by default) at any depth under its search paths. It uploads each file's directory with its subdirectories, then
    deletes the file, and logs and skips a file it cannot parse. Building it raises ``pydantic.ValidationError`` when
    ``version`` is not ``"v1"``, or when a section holds a value its model rejects.
    """

    version: typing.Literal["v1"] = "v1"
    """Format of the upload config file, always ``"v1"``."""

    dataset: UploadConfigFileDatasetSection = pydantic.Field(default_factory=UploadConfigFileDatasetSection)
    """Settings for the dataset the directory is uploaded to."""

    upload: UploadConfigFileUploadSection = pydantic.Field(default_factory=UploadConfigFileUploadSection)
    """Settings for which of the directory's files to upload."""


class UploadAgentConfig(pydantic.BaseModel):
    """Settings of the upload agent: which directories it scans and what it does with files once they are uploaded.

    ``roboto-agent configure`` writes them to ``~/.roboto/upload_agent.json``, and ``roboto-agent run`` reads them
    from there. To upload from Python, pass them to :py:class:`~roboto.upload_agent.agent.UploadAgent`. Building it
    raises ``pydantic.ValidationError`` when ``version`` is not ``"v1"``.
    """

    version: typing.Literal["v1"] = "v1"
    """Format of the settings, always ``"v1"``."""

    default_org_id: typing.Optional[str] = None
    """Organization to create the dataset in when every directory is uploaded into one dataset.

    :py:meth:`~roboto.upload_agent.agent.UploadAgent.process_uploads` does so when ``merge_uploads`` is set, as
    ``roboto-agent run --merge-uploads`` sets it. Required for merged uploads when the caller belongs to more than one
    organization; otherwise the caller's only organization. A dataset for a single directory uses the upload config
    file's ``dataset.org_id`` instead.
    """

    delete_empty_directories: bool = False
    """Whether to delete a directory after uploading it when nothing but its ``.roboto_upload_complete.json`` is left.

    Most useful with ``delete_uploaded_files``: the agent keeps uploaded files unless that setting removes them, and
    always keeps subdirectories, so a directory that has any is never deleted.
    """

    delete_uploaded_files: bool = False
    """Whether to delete a directory's local files once they are uploaded.

    An upload config file's ``upload.delete_uploaded_files`` overrides it for that file's directory.
    """

    search_paths: list[pathlib.Path]
    """Directories to search, at any depth, for upload config files.

    The agent logs and skips a path that is not a directory.
    """

    upload_config_filename: str = ".roboto_upload.json"
    """Name of the upload config file the agent looks for."""


class UploadInProgressFile(pydantic.BaseModel):
    """Contents of the file the upload agent writes into a directory when it starts uploading it.

    The upload agent reads and writes it; nothing else does. The agent never uploads the file and deletes it once the
    upload finishes. A later run that finds one, after an upload was interrupted, resumes the upload to the dataset it
    names instead of creating a dataset; the agent ignores a file it cannot parse.
    """

    version: typing.Literal["v1"] = "v1"
    """Format of the file, always ``"v1"``."""

    dataset_id: str
    """ID of the dataset the directory is being uploaded to."""

    started: datetime.datetime
    """Time the upload started, which the agent records as the time the dataset was created."""


class UploadCompleteFile(pydantic.BaseModel):
    """Contents of the file the upload agent writes into a directory once it has uploaded it.

    The upload agent reads and writes it; nothing else does. The agent uploads the file to the dataset after every
    other file, so a trigger can watch for it to start work once every file is in the dataset. A later run skips a
    directory that holds one, even when it cannot parse the file.
    """

    version: typing.Literal["v1"] = "v1"
    """Format of the file, always ``"v1"``."""

    dataset_id: str
    """ID of the dataset the directory was uploaded to."""

    completed: datetime.datetime
    """Time the upload finished."""
