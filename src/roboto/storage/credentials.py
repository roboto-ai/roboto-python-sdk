# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ..time import utcnow
from .object_store import Credentials


class RobotoCredentials(pydantic.BaseModel):
    """Temporary AWS credentials for reading or writing files in one S3 bucket where Roboto stores them.

    ``GET /v1/datasets/id/{dataset_id}/credentials`` and ``GET /v1/files/association/id/{association_id}/credentials``
    return one for each bucket that holds the resource's files, and ``GET /v1/files/upload/{upload_id}/credentials``
    returns the one an upload writes with. :py:meth:`~roboto.storage.FileService.download` and
    :py:meth:`~roboto.storage.FileService.upload` fetch them to move file contents. They stop working at
    ``expiration``.
    """

    access_key_id: str
    """AWS access key ID of the credentials."""

    bucket: str
    """Name of the S3 bucket the credentials reach."""

    expiration: datetime.datetime
    """Time the credentials expire."""

    secret_access_key: str
    """AWS secret access key of the credentials."""

    session_token: str
    """AWS session token to send with ``access_key_id`` and ``secret_access_key``."""

    region: str
    """AWS region of ``bucket``."""

    required_prefix: str
    """Key prefix in ``bucket`` under which Roboto stores the files of the resource the credentials were issued for.

    In a bucket Roboto manages, the credentials reach only keys under this prefix. In a bucket an organization brings
    to Roboto, credentials for a dataset's or topic's files reach the whole bucket.
    """

    send_requests_to: typing.Optional[str] = None
    """URL that receives the requests signed with these credentials in place of S3, or ``None`` if they go to S3.

    Each request is still signed for S3, then sent to this URL followed by the host and path it was signed for, with
    its query unchanged: a request signed for ``https://<host>/<path>?<query>`` goes to
    ``<send_requests_to>/<host>/<path>?<query>``.
    """

    def is_expired(self) -> bool:
        """Return whether the credentials have expired, as of now."""
        return utcnow() >= self.expiration

    def to_dict(self) -> dict[str, typing.Any]:
        """Return the credentials as a JSON-compatible dictionary, with ``expiration`` as an ISO 8601 string."""
        return self.model_dump(mode="json")

    def to_object_store_credentials(self) -> Credentials:
        """Return the credentials as the :py:class:`~roboto.storage.object_store.Credentials` an object store reads.

        :py:meth:`~roboto.storage.FileService.download` and :py:meth:`~roboto.storage.FileService.upload` convert the
        credentials they fetch through it, so most code never calls it. ``bucket`` and ``required_prefix`` are left
        out; the object store takes the bucket from each file's URI.
        """
        return {
            "access_key": self.access_key_id,
            "secret_key": self.secret_access_key,
            "token": self.session_token,
            "expiry_time": self.expiration.isoformat(),
            "region": self.region,
            "send_requests_to": self.send_requests_to,
        }
