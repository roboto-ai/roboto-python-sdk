# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import enum


class ExitCode(enum.IntEnum):
    """
    Defined exit codes used by the action runtime.
    Exception codes are adapted from /usr/include/sysexits.h
    """

    Success = 0

    UsageError = 64
    """
    From /usr/include/sysexits.h:
      > EX_USAGE -- The command was used incorrectly, e.g., with
      >             the wrong number of arguments, a bad flag, a bad
      >             syntax in a parameter, or whatever.
    """

    InternalError = 70
    """
    From /usr/include/sysexits.h:
      > EX_SOFTWARE -- An internal software error has been detected.
      >                This should be limited to non-operating system related
      >                errors as possible.
    """

    ConfigurationError = 78
    """
    From /usr/include/sysexits.h:
      > EX_CONFIG       78      /* configuration error */
    """
