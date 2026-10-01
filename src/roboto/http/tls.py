# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import functools
import os
import ssl

import truststore


@functools.cache
def https_ssl_context() -> ssl.SSLContext:
    """TLS settings for HTTPS requests to the Roboto API, reads of files by URL, and the CLI's downloads.

    Requests made through boto3, such as S3 transfers, use botocore's certificate settings instead.

    Certificates are checked against the operating system's trusted roots, so a root an administrator installed there
    is trusted. Windows and macOS check them with their own certificate APIs; Linux reads the system CA bundle. On
    Windows this also finds the roots Windows downloads only when first needed. A new Windows machine starts with few
    roots, and Python's built-in check (the ``ssl`` module's default context) sees only the roots already there.

    When ``SSL_CERT_FILE`` or ``SSL_CERT_DIR`` is set, Python's built-in check runs instead and trusts the certificates
    at those paths, since the Windows and macOS checks ignore both variables. The variables are read on the first
    call, and every later call returns the same context.

    Returns:
        A client context that verifies the server's certificate and host name.
    """
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
