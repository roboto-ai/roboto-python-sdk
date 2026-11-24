# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum


class ExitCode(enum.IntEnum):
    """Exit code an action's process ends with: whether it succeeded and, if not, why.

    Every code but ``Success`` takes its value and meaning from the ``sysexits.h`` convention of Unix systems. An
    action exits with one through ``sys.exit``, as in ``sys.exit(ExitCode.DataError)``, and any code but ``Success``
    fails the invocation. :py:class:`~roboto.action_runtime.PrepareEnvException` carries one.
    """

    Success = 0
    """The action succeeded."""

    UsageError = 64
    """The action was invoked incorrectly, such as with a missing or malformed parameter (``EX_USAGE``)."""

    DataError = 65
    """The input data was invalid, such as a file in the wrong format, corrupted, or empty (``EX_DATAERR``).

    Use it for a problem with the data the action was given, not with the action or its environment. Roboto's
    ingestion actions exit with it when they ran correctly but could not ingest the input file.
    """

    InternalError = 70
    """The action, or Roboto's setup for it, failed for a reason other than input or configuration (``EX_SOFTWARE``)."""

    ConfigurationError = 78
    """The action's configuration is invalid, such as a required environment variable that is unset (``EX_CONFIG``)."""
