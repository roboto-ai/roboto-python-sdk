# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Exceptions the SDK raises when Roboto rejects a request or fails to complete it.

Any request can fail in the following ways, so method docstrings do not list them:

- :py:class:`~roboto.exceptions.RobotoUnauthorizedException`: the caller lacks permission for the request.
- :py:class:`~roboto.exceptions.domain.RobotoAuthenticationFailureException`: the caller's token is expired or
  malformed. Import it from ``roboto.exceptions.domain``.
- :py:class:`~roboto.exceptions.RobotoNoOrgProvidedException`: the request needs an organization, the caller belongs
  to more than one, and the request named none.
- :py:class:`~roboto.exceptions.RobotoServiceException`: Roboto failed unexpectedly.
- :py:class:`~roboto.exceptions.RobotoServiceUnavailableException`: Roboto could not accept the request, such as under
  heavy load. Retrying later may succeed.

Each is a subclass of :py:class:`~roboto.exceptions.RobotoDomainException`.
"""

from .domain import (
    ReadPlanExecutionErrorKind,
    RobotoBoardRevisionConflictException,
    RobotoClientToolResultsNotPendingException,
    RobotoConditionException,
    RobotoConflictException,
    RobotoContextTooLongException,
    RobotoDashboardRevisionConflictException,
    RobotoDatasetNotFoundException,
    RobotoDeprecatedException,
    RobotoDeviceNotFoundException,
    RobotoDomainException,
    RobotoExpiredException,
    RobotoFailedToGenerateException,
    RobotoFeatureNotAvailableException,
    RobotoHttpExceptionParse,
    RobotoIllegalArgumentException,
    RobotoInternalException,
    RobotoInvalidRequestException,
    RobotoInvalidStateTransitionException,
    RobotoLayoutConflictException,
    RobotoLimitExceededException,
    RobotoNoOrgProvidedException,
    RobotoNotFoundException,
    RobotoNotImplementedException,
    RobotoNotReadyException,
    RobotoOperationTimeoutException,
    RobotoOrgCreationRefusedException,
    RobotoOrgEmailDomainChangeRefusedException,
    RobotoReadPlanExecutionException,
    RobotoResponseTooLargeException,
    RobotoServiceException,
    RobotoServiceUnavailableException,
    RobotoThreadReadOnlyException,
    RobotoUnauthorizedException,
    RobotoUnknownFieldAddressException,
    RobotoUnknownOperationException,
    RobotoUnrecognizedErrorException,
)
from .http import (
    ClientError,
    HttpError,
    ServerError,
)
from .ingestion import (
    IngestionException,
    TimestampFieldNotFoundException,
)

__all__ = [
    "ClientError",
    "HttpError",
    "IngestionException",
    "ReadPlanExecutionErrorKind",
    "ServerError",
    "TimestampFieldNotFoundException",
    "RobotoBoardRevisionConflictException",
    "RobotoClientToolResultsNotPendingException",
    "RobotoConditionException",
    "RobotoConflictException",
    "RobotoContextTooLongException",
    "RobotoDashboardRevisionConflictException",
    "RobotoDatasetNotFoundException",
    "RobotoDeviceNotFoundException",
    "RobotoDeprecatedException",
    "RobotoDomainException",
    "RobotoExpiredException",
    "RobotoFailedToGenerateException",
    "RobotoFeatureNotAvailableException",
    "RobotoHttpExceptionParse",
    "RobotoIllegalArgumentException",
    "RobotoReadPlanExecutionException",
    "RobotoResponseTooLargeException",
    "RobotoInternalException",
    "RobotoInvalidRequestException",
    "RobotoInvalidStateTransitionException",
    "RobotoLayoutConflictException",
    "RobotoLimitExceededException",
    "RobotoNotFoundException",
    "RobotoNotImplementedException",
    "RobotoNotReadyException",
    "RobotoNoOrgProvidedException",
    "RobotoServiceException",
    "RobotoServiceUnavailableException",
    "RobotoOperationTimeoutException",
    "RobotoOrgCreationRefusedException",
    "RobotoOrgEmailDomainChangeRefusedException",
    "RobotoThreadReadOnlyException",
    "RobotoUnauthorizedException",
    "RobotoUnknownFieldAddressException",
    "RobotoUnknownOperationException",
    "RobotoUnrecognizedErrorException",
]
