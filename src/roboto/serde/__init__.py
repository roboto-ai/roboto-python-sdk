# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.


"""
SerDe: Serialization + Deserialization

This module contains utility functions for common serialization and deserialization scenarios used
throughout the Roboto python codebase.
"""

from .arrays import safe_access_array
from .dicts import (
    case_insensitive_get,
    pydantic_jsonable_dict,
    pydantic_jsonable_dict_map,
    pydantic_jsonable_dicts,
    safe_dict_drill,
)
from .paths import (
    exclude_patterns_to_spec,
    git_paths_match,
    git_paths_to_spec,
)

__all__ = [
    "pydantic_jsonable_dict",
    "pydantic_jsonable_dicts",
    "pydantic_jsonable_dict_map",
    "safe_dict_drill",
    "case_insensitive_get",
    "exclude_patterns_to_spec",
    "git_paths_to_spec",
    "git_paths_match",
    "safe_access_array",
]
