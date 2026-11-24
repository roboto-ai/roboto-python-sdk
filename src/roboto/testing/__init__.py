# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Test doubles that stand in for Roboto in unit tests of code that uses the SDK.

To test code that calls SDK methods, use :py:class:`~roboto.testing.StubRobotoClient`; to test code that calls an
:py:class:`~roboto.http.HttpClient` directly, use :py:class:`~roboto.testing.FakeHttpResponseFactory`. Pass a
``StubRobotoClient`` as the ``roboto_client`` of those methods: it returns the responses you register for the requests
you expect, and raises ``AssertionError`` on any other request. A ``FakeHttpResponseFactory`` builds the responses a
mock of that client returns.
"""

from .fake_http_response_factory import FakeHttpResponseFactory
from .stub_roboto_client import StubRobotoClient

__all__ = ["FakeHttpResponseFactory", "StubRobotoClient"]
