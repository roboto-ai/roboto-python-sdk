# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import pathlib
import typing
from typing import Any, Optional

import boto3
import botocore.config
import botocore.credentials
import botocore.session

from ...association import Association
from ...http import RobotoClient
from ...query import QuerySpecification
from ...sentinels import (
    NotSet,
    NotSetType,
    remove_not_set,
)
from ...updates import MetadataChangeset
from ..events import Event
from ..topics import Topic
from .operations import UpdateFileRecordRequest
from .progress import (
    NoopProgressMonitorFactory,
    ProgressMonitorFactory,
)
from .record import CredentialProvider, FileRecord


class File:
    __record: FileRecord
    __roboto_client: RobotoClient

    @staticmethod
    def construct_s3_obj_arn(bucket: str, key: str) -> str:
        return f"arn:aws:s3:::{bucket}/{key}"

    @staticmethod
    def construct_s3_obj_uri(
        bucket: str, key: str, version: Optional[str] = None
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
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "File":
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/files/record/{file_id}").to_record(FileRecord)
        return cls(record, roboto_client)

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        owner_org_id: Optional[str] = None,
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
    def description(self) -> Optional[str]:
        return self.__record.description

    @property
    def file_id(self) -> str:
        return self.__record.file_id

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

    def delete(self) -> None:
        self.__roboto_client.delete(f"/v1/files/{self.file_id}")

    def download(
        self,
        local_path: pathlib.Path,
        credential_provider: CredentialProvider,
        progress_monitor_factory: ProgressMonitorFactory = NoopProgressMonitorFactory(),
    ):
        local_path.parent.mkdir(parents=True, exist_ok=True)
        s3_client = File.generate_s3_client(credential_provider)

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

    def get_events(self) -> collections.abc.Generator[Event, None, None]:
        return Event.get_by_file(self.file_id)

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
        for topic in Topic.get_by_file(owner_org_id=self.org_id, file_id=self.file_id):
            if include is not None and topic.name not in include:
                continue

            if exclude is not None and topic.name in exclude:
                continue

            yield topic

    def put_metadata(self, metadata: dict[str, typing.Any]) -> "File":
        return self.update(metadata_changeset=MetadataChangeset(put_fields=metadata))

    def put_tags(self, tags: list[str]) -> "File":
        return self.update(metadata_changeset=MetadataChangeset(put_tags=tags))

    def to_association(self) -> Association:
        return Association.file(self.file_id)

    def to_dict(self) -> dict[str, Any]:
        return self.__record.model_dump(mode="json")

    def update(
        self,
        description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
    ) -> "File":
        request = remove_not_set(
            UpdateFileRecordRequest(
                description=description, metadata_changeset=metadata_changeset
            )
        )
        self.__record = self.__roboto_client.put(
            f"v1/files/record/{self.file_id}", data=request
        ).to_record(FileRecord)
        return self
