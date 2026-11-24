# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import functools
import os
import re
import ssl
import sys

import truststore

_LINUX_CA_FILE_CANDIDATES = (
    # Alpine, Arch, Fedora 34-43, OpenWRT, RHEL 9-10, BSD
    "/etc/ssl/cert.pem",
    # Fedora 44+, RHEL 11+
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    # Fedora <= 34, RHEL <= 9, CentOS <= 9
    "/etc/pki/tls/cert.pem",
    # Debian, Ubuntu (requires ca-certificates)
    "/etc/ssl/certs/ca-certificates.crt",
    # SUSE
    "/etc/ssl/ca-bundle.pem",
)
"""Paths where Linux distributions keep the system CA bundle, in the order they are tried.

``_linux_system_roots_context`` tries them when OpenSSL's own default paths hold no certificates. The list, and when
it is tried, are copied from ``truststore`` 0.10."""

_HASHED_CERT_FILENAME = re.compile(r"^[0-9a-fA-F]{8}\.[0-9]$")
"""Regular expression a certificate's file name in an OpenSSL CA directory matches: a subject hash and a number."""


@functools.cache
def https_ssl_context() -> ssl.SSLContext:
    """Return the TLS settings for HTTPS requests to the Roboto API, reads of files by URL, and the CLI's downloads.

    Requests made through ``boto3``, such as S3 transfers, use ``botocore``'s certificate settings instead.

    Certificates are checked against the operating system's trusted roots, so a root an administrator installed there
    is trusted. Windows and macOS check them with their own certificate APIs; Linux reads the system CA bundle. On
    Windows this also finds the roots Windows downloads only when first needed. A new Windows machine starts with few
    roots, and Python's built-in check (the ``ssl`` module's default context) sees only the roots already there.

    On Linux the system CA bundle is read once, on the first call, not for each connection, so a root installed after
    the first call is trusted by the next process, not by this one.

    When ``SSL_CERT_FILE`` or ``SSL_CERT_DIR`` is set, Python's built-in check runs instead and trusts the certificates
    at those paths, since the Windows and macOS checks ignore both variables. The variables are read on the first
    call, and every later call returns the same context.

    Returns:
        A client context that verifies the server's certificate and host name.
    """
    if os.environ.get("SSL_CERT_FILE") or os.environ.get("SSL_CERT_DIR"):
        return ssl.create_default_context()
    if sys.platform.startswith("linux"):
        # truststore reads the system CA bundle for every connection while holding a lock, which limits a process to
        # about ten new connections per second however many threads it runs.
        return _linux_system_roots_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def _linux_system_roots_context() -> ssl.SSLContext:
    """Build a client context that checks certificates and host names as ``truststore`` does on Linux.

    The trusted roots are loaded once, into this context, rather than for each connection. OpenSSL's default paths
    are used when they hold certificates. A Python built against an OpenSSL whose default paths do not exist on this
    distribution, such as a relocatable build, falls back to the first system bundle found among
    ``_LINUX_CA_FILE_CANDIDATES``.
    """
    # truststore builds this same context. ssl.create_default_context() would also set VERIFY_X509_STRICT on
    # Python 3.13 and later, which rejects some certificates that truststore accepts.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    defaults = ssl.get_default_verify_paths()
    if defaults.cafile or (
        defaults.capath is not None
        and os.path.isdir(defaults.capath)
        and any(_HASHED_CERT_FILENAME.match(name) for name in os.listdir(defaults.capath))
    ):
        context.set_default_verify_paths()
    else:
        for cafile in _LINUX_CA_FILE_CANDIDATES:
            if os.path.isfile(cafile):
                context.load_verify_locations(cafile=cafile)
                break
    return context
