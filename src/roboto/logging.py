# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import logging

LOGGER_NAME = "roboto"


def default_logger():
    return logging.getLogger(LOGGER_NAME)


def maybe_pluralize(word: str, count: int) -> str:
    return word if count == 1 else f"{word}s"
