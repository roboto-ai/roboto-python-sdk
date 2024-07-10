# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import urllib.parse
import uuid

import pytest

from roboto.http import (
    PaginationToken,
    PaginationTokenEncoding,
    PaginationTokenScheme,
)


def unique_id() -> str:
    return uuid.uuid4().hex


@pytest.mark.parametrize(
    ["data", "encoding", "scheme"],
    [
        # Format of page tokens used by DDB queries
        (
            {"dataset_id": unique_id(), "org_id": unique_id()},
            PaginationTokenEncoding.Json,
            PaginationTokenScheme.V1,
        ),
        # Format of page tokens used by S3 list objects
        (
            "20230707T184705-NT16AuFL.txt",
            PaginationTokenEncoding.Raw,
            PaginationTokenScheme.V1,
        ),
    ],
)
def test_pagination_token_roundtrip(data, encoding, scheme):
    # Arrange
    pagination_token = PaginationToken(scheme, encoding, data)

    # Act
    token = str(pagination_token)

    # Assert
    assert PaginationToken.from_token(token).data == data


@pytest.mark.parametrize(
    ["scheme"],
    [("v2",), ("xx",), ("1",), ("",), ("not-a-scheme",)],
)
def test_pagination_token_fails_if_scheme_not_supported(scheme: str):
    # Arrange / Act / Assert
    with pytest.raises(ValueError):
        PaginationToken.from_token(f"{scheme}:raw:20230707T184705-NT16AuFL.txt")


@pytest.mark.parametrize(
    ["data", "encoding", "scheme"],
    [
        # Format of page tokens used by DDB queries
        (
            {"dataset_id": unique_id(), "org_id": unique_id()},
            PaginationTokenEncoding.Json,
            PaginationTokenScheme.V1,
        ),
        # Formate of page tokens used by S3 list objects
        (
            "20230707T184705-NT16AuFL.txt",
            PaginationTokenEncoding.Raw,
            PaginationTokenScheme.V1,
        ),
    ],
)
def test_pagination_token_is_urlsafe(data, encoding, scheme):
    # Arrange
    pagination_token = PaginationToken(scheme, encoding, data)

    # Act
    token = str(pagination_token)

    # Assert
    assert urllib.parse.quote_plus(token) == token
