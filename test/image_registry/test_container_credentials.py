# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime

import pytest

from roboto.image_registry import (
    ContainerCredentials,
)
from roboto.time import utcnow


@pytest.mark.parametrize(
    "expiration, expectation",
    [
        (utcnow() - datetime.timedelta(minutes=1), True),
        (utcnow() + datetime.timedelta(minutes=1), False),
    ],
)
def test_container_credentials_is_expired(
    expiration: datetime.datetime, expectation: bool
):
    # Arrange
    credentials = ContainerCredentials(
        username="username",
        password="password",
        registry_url="registry_url",
        expiration=expiration,
    )

    # Act
    result = credentials.is_expired()

    # Assert
    assert result == expectation
