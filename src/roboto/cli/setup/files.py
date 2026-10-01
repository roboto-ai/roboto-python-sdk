# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import errno
import os
import pathlib
import tempfile
import urllib.request

from ...http.tls import https_ssl_context
from ..config import USER_AGENT

DOWNLOAD_TIMEOUT_SECONDS = 60


def download_file(url: str) -> bytes:
    """Return the contents of the file at ``url``.

    Raises:
        OSError: The server couldn't be reached, went ``DOWNLOAD_TIMEOUT_SECONDS`` without answering, or answered with
            an error status.
    """
    # Astral's download site, which serves the uv installer, answers Python's default user agent with 403.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS, context=https_ssl_context()) as response:  # noqa: S310
        return response.read()


def write_file_atomically(path: pathlib.Path, contents: str) -> None:
    """Replace the contents of ``path`` so that the file holds either the old contents or the new, never a mix.

    That holds for a program reading the file during the write and for the file left behind if the machine crashes.
    When ``path`` is a symlink, the file it points to is written and the link is kept. An existing file keeps its
    permissions; a new file gets the permissions the user's umask gives any file they create.

    Args:
        path: The file to write. Missing parent directories are created.
        contents: The text to write, encoded as UTF-8.

    Raises:
        OSError: ``path`` is a symlink that can't be followed, such as one in a loop, or a directory or the file
            couldn't be created or written. The file is left as it was.
    """
    # On every supported Python version, realpath leaves a symlink it can't follow in its result, and writing there
    # would replace the link with a regular file. (Path.resolve raises RuntimeError on a loop before Python 3.13.)
    target = pathlib.Path(os.path.realpath(path))
    if target.is_symlink():
        raise OSError(errno.ELOOP, os.strerror(errno.ELOOP), str(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        mode = target.stat().st_mode & 0o777
    else:
        # Python can read the umask only by setting it, so set it and put it back.
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask

    # The new contents go to a temporary file in the same directory, then a rename swaps it in for the target in one
    # step. Any exception, including Ctrl-C, deletes the temporary file and is re-raised with the target untouched.
    fd, temp_name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contents)
            f.flush()
            os.fsync(f.fileno())
        # mkstemp creates the file readable only by its owner.
        os.chmod(temp_name, mode)
        os.replace(temp_name, target)
    except BaseException:
        pathlib.Path(temp_name).unlink(missing_ok=True)
        raise
