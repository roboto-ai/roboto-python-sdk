# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import contextlib
import email.message
import http
import json
import pathlib
import unittest.mock
import urllib.error
import urllib.response

from roboto.http import HttpClient


class TestHttpClient:
    def test_retries_when_appropriate(self, tmp_path: pathlib.Path):
        # Arrange
        remote_response = tmp_path / "remote_response.json"
        remote_response.write_text(json.dumps({"message": "hello world"}))

        http_client = HttpClient()

        fail_status = http.HTTPStatus.TOO_MANY_REQUESTS
        fail_response = urllib.error.HTTPError(
            "http://any.url",
            fail_status.value,
            fail_status.phrase,
            email.message.Message(),
            None,
        )
        fail_count = 3
        failures = [fail_response] * fail_count

        with contextlib.ExitStack() as stack:
            mock_urlopen = stack.enter_context(
                unittest.mock.patch(
                    "roboto.http.http_client.urllib.request.urlopen",
                    autospec=True,
                )
            )
            responses = [
                # Try
                *failures,
                # Finally succeed
                urllib.response.addinfourl(
                    stack.enter_context(open(remote_response, "rb")),
                    email.message.Message(),
                    "http://any.url",
                    http.HTTPStatus.OK.value,
                ),
            ]
            mock_urlopen.side_effect = responses

            # Act
            http_client.get("http://any.url")

            # Assert
            assert mock_urlopen.call_count == len(responses)
