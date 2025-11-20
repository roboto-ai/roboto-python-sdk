# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


class RobotoLLMContext(pydantic.BaseModel):
    """Contextual information about what a user is trying to do. May be passed along to Roboto LLM based code paths
    in order to enrich results"""

    dataset_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of datasets that are relevant to the user's query."""

    file_ids: list[str] = pydantic.Field(default_factory=list)
    """IDs of files that are relevant to the user's query."""
