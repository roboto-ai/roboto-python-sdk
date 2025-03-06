# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing
import urllib.parse

import boto3
import botocore.config
import botocore.credentials
import botocore.session

from ...association import Association
from ...http import BatchRequest, RobotoClient
from ...query import QuerySpecification
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ...updates import MetadataChangeset
from ..topics import Topic
from .file_creds import (
    CredentialProvider,
    FileCredentialsHelper,
)
from .operations import (
    ImportFileRequest,
    RenameFileRequest,
    UpdateFileRecordRequest,
)
from .progress import (
    NoopProgressMonitorFactory,
    ProgressMonitorFactory,
)
from .record import FileRecord, IngestionStatus


class File:
    """
    Files can be uploaded to datasets. Once uploaded, they can be tagged,
    post-processed by actions, added to collections, visualized, and searched.
    """

    __record: FileRecord
    __roboto_client: RobotoClient

    @staticmethod
    def construct_s3_obj_arn(bucket: str, key: str, partition: str = "aws") -> str:
        return f"arn:{partition}:s3:::{bucket}/{key}"

    @staticmethod
    def construct_s3_obj_uri(
        bucket: str, key: str, version: typing.Optional[str] = None
    ) -> str:
        base_uri = f"s3://{bucket}/{key}"
        if version:
            base_uri += f"?versionId={version}"
        return base_uri

    @staticmethod
    def generate_s3_client(
        credential_provider: CredentialProvider, tcp_keepalive: bool = True
    ):
        creds = credential_provider()
        refreshable_credentials = (
            botocore.credentials.RefreshableCredentials.create_from_metadata(
                metadata=creds,
                refresh_using=credential_provider,
                method="roboto-api",
            )
        )
        botocore_session = botocore.session.get_session()
        botocore_session._credentials = refreshable_credentials
        botocore_session.set_config_variable("region", creds["region"])
        session = boto3.Session(botocore_session=botocore_session)

        return session.client(
            "s3", config=botocore.config.Config(tcp_keepalive=tcp_keepalive)
        )

    @classmethod
    def from_id(
        cls,
        file_id: str,
        version_id: typing.Optional[int] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "File":
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/files/record/{file_id}",
            query={"version_id": version_id} if version_id is not None else None,
        ).to_record(FileRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_path_and_dataset_id(
        cls,
        file_path: typing.Union[str, pathlib.Path],
        dataset_id: str,
        version_id: typing.Optional[int] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "File":
        roboto_client = RobotoClient.defaulted(roboto_client)
        url_quoted_file_path = urllib.parse.quote(str(file_path), safe="")
        record = roboto_client.get(
            f"v1/files/record/path/{url_quoted_file_path}/association/{dataset_id}",
            query={"version_id": version_id} if version_id is not None else None,
        ).to_record(FileRecord)
        return cls(record, roboto_client)

    @classmethod
    def import_batch(
        cls,
        requests: collections.abc.Sequence[ImportFileRequest],
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Sequence["File"]:
        roboto_client = RobotoClient.defaulted(roboto_client)

        # Requests explicitly need to be cast to list because of Pydantic serialization not working appropriately
        # with collections.abc
        request: BatchRequest[ImportFileRequest] = BatchRequest(requests=list(requests))

        records = roboto_client.post(
            "v1/files/import/batch", data=request, idempotent=True
        ).to_record_list(FileRecord)
        return [cls(record, roboto_client) for record in records]

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        owner_org_id: typing.Optional[str] = None,
    ) -> collections.abc.Generator["File", None, None]:
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec or QuerySpecification()

        known = set(FileRecord.model_fields.keys())
        actual = set()
        for field in spec.fields():
            # Support dot notation for nested fields
            # E.g., "metadata.SoftwareVersion"
            if "." in field:
                actual.add(field.split(".")[0])
            else:
                actual.add(field)
        unknown = actual - known
        if unknown:
            plural = len(unknown) > 1
            msg = (
                "are not known attributes of File"
                if plural
                else "is not a known attribute of File"
            )
            raise ValueError(f"{unknown} {msg}. Known attributes: {known}")

        while True:
            paginated_results = roboto_client.post(
                "v1/files/query", data=spec, owner_org_id=owner_org_id, idempotent=True
            ).to_paginated_list(FileRecord)

            for record in paginated_results.items:
                yield cls(record, roboto_client)

            if paginated_results.next_token:
                spec.after = paginated_results.next_token
            else:
                break

    def __init__(
        self, record: FileRecord, roboto_client: typing.Optional[RobotoClient] = None
    ):
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def dataset_id(self) -> str:
        return self.__record.association_id

    @property
    def description(self) -> typing.Optional[str]:
        return self.__record.description

    @property
    def file_id(self) -> str:
        return self.__record.file_id

    @property
    def ingestion_status(self) -> IngestionStatus:
        return self.__record.ingestion_status

    @property
    def org_id(self) -> str:
        return self.__record.org_id

    @property
    def record(self) -> FileRecord:
        return self.__record

    @property
    def relative_path(self) -> str:
        return self.__record.relative_path

    @property
    def metadata(self) -> dict[str, typing.Any]:
        return self.__record.metadata

    @property
    def tags(self) -> list[str]:
        return self.__record.tags

    @property
    def uri(self) -> str:
        return self.__record.uri

    @property
    def version(self) -> int:
        return self.__record.version

    def delete(self) -> None:
        self.__roboto_client.delete(f"/v1/files/{self.file_id}")

    def download(
        self,
        local_path: pathlib.Path,
        credential_provider: typing.Optional[CredentialProvider] = None,
        progress_monitor_factory: ProgressMonitorFactory = NoopProgressMonitorFactory(),
    ):
        local_path.parent.mkdir(parents=True, exist_ok=True)

        defaulted_credential_provider: CredentialProvider
        if credential_provider is None:
            defaulted_credential_provider = FileCredentialsHelper(
                self.__roboto_client
            ).get_dataset_download_creds_provider(self.dataset_id, self.record.bucket)
        else:
            defaulted_credential_provider = credential_provider

        s3_client = File.generate_s3_client(defaulted_credential_provider)

        res = s3_client.head_object(Bucket=self.record.bucket, Key=self.record.key)
        download_bytes = int(res.get("ContentLength", 0))

        source = self.record.key.replace(f"{self.record.org_id}/datasets/", "")

        progress_monitor = progress_monitor_factory.download_monitor(
            source=source, size=download_bytes
        )
        try:
            s3_client.download_file(
                Bucket=self.record.bucket,
                Key=self.record.key,
                Filename=str(local_path),
                Callback=progress_monitor.update,
            )
        finally:
            progress_monitor.close()

    def get_signed_url(
        self,
        override_content_type: typing.Optional[str] = None,
        override_content_disposition: typing.Optional[str] = None,
    ) -> str:
        query_params: dict[str, str] = {}

        if override_content_disposition:
            query_params["override_content_disposition"] = override_content_disposition

        if override_content_type:
            query_params["override_content_type"] = override_content_type

        res = self.__roboto_client.get(
            f"v1/files/{self.file_id}/signed-url",
            query=query_params,
            owner_org_id=self.org_id,
        )
        return res.to_dict(json_path=["data", "url"])

    def get_topic(self, topic_name: str) -> Topic:
        return Topic.from_name_and_file(
            topic_name=topic_name,
            file_id=self.file_id,
            owner_org_id=self.org_id,
            roboto_client=self.__roboto_client,
        )

    def get_topics(
        self,
        include: typing.Optional[collections.abc.Sequence[str]] = None,
        exclude: typing.Optional[collections.abc.Sequence[str]] = None,
    ) -> collections.abc.Generator["Topic", None, None]:
        for topic in Topic.get_by_file(
            owner_org_id=self.org_id,
            file_id=self.file_id,
            roboto_client=self.__roboto_client,
        ):
            if include is not None and topic.name not in include:
                continue

            if exclude is not None and topic.name in exclude:
                continue

            yield topic

    def mark_ingested(self) -> "File":
        """
        Marks this file as fully ingested and ready for additional post-processing or analysis.

        This file will have :py:attr:`IngestionStatus.Ingested` afterwards.
        """
        return self.update(ingestion_complete=True)

    def put_metadata(self, metadata: dict[str, typing.Any]) -> "File":
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: list[str]) -> "File":
        return self.update(metadata_changeset=MetadataChangeset(put_tags=tags))

    def refresh(self) -> "File":
        self.__record = self.__roboto_client.get(
            f"v1/files/record/{self.file_id}"
        ).to_record(FileRecord)
        return self

    def rename_file(self, file_id: str, new_path: str) -> FileRecord:

        response = self.__roboto_client.put(
            f"v1/files/{self.file_id}/rename",
            data=RenameFileRequest(
                association_id=self.dataset_id,
                new_path=new_path,
            ),
        )

        return response.to_record(FileRecord)

    def to_association(self) -> Association:
        return Association.file(self.file_id, self.version)

    def to_dict(self) -> dict[str, typing.Any]:
        return self.__record.model_dump(mode="json")

    def update(
        self,
        description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        ingestion_complete: typing.Union[typing.Literal[True], NotSetType] = NotSet,
    ) -> "File":
        request = remove_not_set(
            UpdateFileRecordRequest(
                description=description,
                metadata_changeset=metadata_changeset,
                ingestion_complete=ingestion_complete,
            )
        )
        self.__record = self.__roboto_client.put(
            f"v1/files/record/{self.file_id}", data=request
        ).to_record(FileRecord)
        return self
