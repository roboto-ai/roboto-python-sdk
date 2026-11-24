# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Pydantic helpers that Roboto's models use to validate and build their fields.

The SDK's own code uses them. ``ValidatedAgainst`` names the model a field's value is validated against while the
field keeps the value as sent; ``validate_nonzero_gitpath_specs`` rejects, with ``ValueError``, a list of
gitignore-style path patterns that is empty or holds only empty or whitespace strings; and
``remove_non_noneable_init_args`` drops the ``None`` values that a model's fields do not accept, before the values
reach the model's constructor.
"""

from .field_metadata import ValidatedAgainst
from .validators import (
    remove_non_noneable_init_args,
    validate_nonzero_gitpath_specs,
)

__all__ = [
    "ValidatedAgainst",
    "remove_non_noneable_init_args",
    "validate_nonzero_gitpath_specs",
]
