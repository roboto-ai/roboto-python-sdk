# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import email.message
import http
import http.client
import unittest.mock
import urllib.error
import urllib.request

import pytest

from roboto.http.http_client import (
    HttpRequest,
    is_expected_to_be_transient,
)


class TestIsExpectedToBeTransient:
    @pytest.mark.parametrize(
        ["idempotent", "expectation"],
        [
            (True, True),
            (False, False),
        ],
    )
    def test_remote_disconnected(self, idempotent: bool, expectation: bool):
        # Arrange
        request = unittest.mock.create_autospec(HttpRequest, instance=True)
        request.idempotent = idempotent
        predicate = is_expected_to_be_transient(request)
        exc = http.client.RemoteDisconnected("line 2")

        # Act
        result = predicate(exc)

        # Assert
        assert result is expectation

    @pytest.mark.parametrize(
        ["status", "expectation"],
        [
            (http.HTTPStatus.OK, False),
            (http.HTTPStatus.CREATED, False),
            (http.HTTPStatus.ACCEPTED, False),
            (http.HTTPStatus.NO_CONTENT, False),
            (http.HTTPStatus.RESET_CONTENT, False),
            (http.HTTPStatus.PARTIAL_CONTENT, False),
            (http.HTTPStatus.MULTIPLE_CHOICES, False),
            (http.HTTPStatus.MOVED_PERMANENTLY, False),
            (http.HTTPStatus.FOUND, False),
            (http.HTTPStatus.SEE_OTHER, False),
            (http.HTTPStatus.NOT_MODIFIED, False),
            (http.HTTPStatus.USE_PROXY, False),
            (http.HTTPStatus.TEMPORARY_REDIRECT, False),
            (http.HTTPStatus.BAD_REQUEST, False),
            (http.HTTPStatus.UNAUTHORIZED, False),
            (http.HTTPStatus.PAYMENT_REQUIRED, False),
            (http.HTTPStatus.FORBIDDEN, False),
            (http.HTTPStatus.NOT_FOUND, False),
            (http.HTTPStatus.METHOD_NOT_ALLOWED, False),
            (http.HTTPStatus.NOT_ACCEPTABLE, False),
            (http.HTTPStatus.PROXY_AUTHENTICATION_REQUIRED, False),
            (http.HTTPStatus.REQUEST_TIMEOUT, True),
            (http.HTTPStatus.CONFLICT, False),
            (http.HTTPStatus.GONE, False),
            (http.HTTPStatus.LENGTH_REQUIRED, False),
            (http.HTTPStatus.PRECONDITION_FAILED, False),
            (http.HTTPStatus.REQUEST_ENTITY_TOO_LARGE, False),
            (http.HTTPStatus.REQUEST_URI_TOO_LONG, False),
            (http.HTTPStatus.UNSUPPORTED_MEDIA_TYPE, False),
            (http.HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, False),
            (http.HTTPStatus.EXPECTATION_FAILED, False),
            (http.HTTPStatus.TOO_MANY_REQUESTS, True),
            (http.HTTPStatus.INTERNAL_SERVER_ERROR, True),
            (http.HTTPStatus.NOT_IMPLEMENTED, False),
            (http.HTTPStatus.BAD_GATEWAY, True),
            (http.HTTPStatus.SERVICE_UNAVAILABLE, True),
            (http.HTTPStatus.GATEWAY_TIMEOUT, True),
            (http.HTTPStatus.HTTP_VERSION_NOT_SUPPORTED, False),
        ],
    )
    def test_http_error_idempotent_request(
        self, status: http.HTTPStatus, expectation: bool
    ):
        # Arrange
        request = unittest.mock.create_autospec(HttpRequest, instance=True)
        request.idempotent = True
        predicate = is_expected_to_be_transient(request)
        headers = email.message.Message()
        exc = urllib.error.HTTPError("url", status.value, status.phrase, headers, None)

        # Act
        result = predicate(exc)

        # Assert
        assert result == expectation

    @pytest.mark.parametrize(
        ["status", "expectation"],
        [
            (http.HTTPStatus.OK, False),
            (http.HTTPStatus.CREATED, False),
            (http.HTTPStatus.ACCEPTED, False),
            (http.HTTPStatus.NO_CONTENT, False),
            (http.HTTPStatus.RESET_CONTENT, False),
            (http.HTTPStatus.PARTIAL_CONTENT, False),
            (http.HTTPStatus.MULTIPLE_CHOICES, False),
            (http.HTTPStatus.MOVED_PERMANENTLY, False),
            (http.HTTPStatus.FOUND, False),
            (http.HTTPStatus.SEE_OTHER, False),
            (http.HTTPStatus.NOT_MODIFIED, False),
            (http.HTTPStatus.USE_PROXY, False),
            (http.HTTPStatus.TEMPORARY_REDIRECT, False),
            (http.HTTPStatus.BAD_REQUEST, False),
            (http.HTTPStatus.UNAUTHORIZED, False),
            (http.HTTPStatus.PAYMENT_REQUIRED, False),
            (http.HTTPStatus.FORBIDDEN, False),
            (http.HTTPStatus.NOT_FOUND, False),
            (http.HTTPStatus.METHOD_NOT_ALLOWED, False),
            (http.HTTPStatus.NOT_ACCEPTABLE, False),
            (http.HTTPStatus.PROXY_AUTHENTICATION_REQUIRED, False),
            (http.HTTPStatus.REQUEST_TIMEOUT, False),
            (http.HTTPStatus.CONFLICT, False),
            (http.HTTPStatus.GONE, False),
            (http.HTTPStatus.LENGTH_REQUIRED, False),
            (http.HTTPStatus.PRECONDITION_FAILED, False),
            (http.HTTPStatus.REQUEST_ENTITY_TOO_LARGE, False),
            (http.HTTPStatus.REQUEST_URI_TOO_LONG, False),
            (http.HTTPStatus.UNSUPPORTED_MEDIA_TYPE, False),
            (http.HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE, False),
            (http.HTTPStatus.EXPECTATION_FAILED, False),
            (http.HTTPStatus.TOO_MANY_REQUESTS, True),
            (http.HTTPStatus.INTERNAL_SERVER_ERROR, False),
            (http.HTTPStatus.NOT_IMPLEMENTED, False),
            (http.HTTPStatus.BAD_GATEWAY, True),
            (http.HTTPStatus.SERVICE_UNAVAILABLE, True),
            (http.HTTPStatus.GATEWAY_TIMEOUT, False),
            (http.HTTPStatus.HTTP_VERSION_NOT_SUPPORTED, False),
        ],
    )
    def test_http_error_non_idempotent_request(
        self, status: http.HTTPStatus, expectation: bool
    ):
        # Arrange
        request = unittest.mock.create_autospec(HttpRequest, instance=True)
        request.idempotent = False
        predicate = is_expected_to_be_transient(request)
        headers = email.message.Message()
        exc = urllib.error.HTTPError("url", status.value, status.phrase, headers, None)

        # Act
        result = predicate(exc)

        # Assert
        assert result == expectation

    def test_http_error_invalid_status_code(self):
        # Arrange
        request = unittest.mock.create_autospec(HttpRequest, instance=True)
        predicate = is_expected_to_be_transient(request)
        headers = email.message.Message()
        exc = urllib.error.HTTPError("url", 999, "Invalid Status Code", headers, None)

        # Act
        result = predicate(exc)

        # Assert
        assert result is False

    @pytest.mark.parametrize(
        ["error_message", "idempotent", "expectation"],
        [
            ("Connection reset by peer", True, True),
            ("Connection reset by peer", False, False),
            ("Temporary failure in name resolution", True, True),
            ("Temporary failure in name resolution", False, True),
        ],
    )
    def test_url_error_transient(
        self, error_message: str, idempotent: bool, expectation: bool
    ):
        # Arrange
        request = unittest.mock.create_autospec(HttpRequest, instance=True)
        request.idempotent = idempotent
        predicate = is_expected_to_be_transient(request)
        exc = urllib.error.URLError(error_message)

        # Act
        result = predicate(exc)

        # Assert
        assert result is expectation
