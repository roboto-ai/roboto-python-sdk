# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


class PromptRequest(pydantic.BaseModel):
    """
    A generic request intended for a natural-language powered endpoint which accepts a human-readable prompt.
    """

    prompt: str
    """The prompt to send to the AI model."""
