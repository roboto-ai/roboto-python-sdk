# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Secrets: sensitive values, such as API keys or passwords, that actions can use while they run.

A secret's value is kept in a secret store and never passes through Roboto's APIs. Use
:py:class:`~roboto.domain.secrets.Secret` to create and find secrets, and to read and update their values.
"""

from .record import (
    AwsSecretRetrievalLocation,
    AwsSecretsManagerAccessCreds,
    CreateSecretRequest,
    GetSecretAccessCredsResponse,
    SecretAccessCreds,
    SecretRecord,
    SecretStoreType,
)
from .secret import Secret, is_secret_uri

__all__ = [
    "is_secret_uri",
    "AwsSecretsManagerAccessCreds",
    "AwsSecretRetrievalLocation",
    "CreateSecretRequest",
    "GetSecretAccessCredsResponse",
    "SecretRecord",
    "SecretStoreType",
    "SecretAccessCreds",
    "Secret",
]
