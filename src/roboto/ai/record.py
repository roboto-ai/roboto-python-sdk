# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


class PromptRequest(pydantic.BaseModel):
    """Request body for ``POST /v1/query/convert/nlp-to-roboql``.

    Roboto's AI writes a RoboQL query from the prompt and returns it as
    :py:class:`~roboto.query.QualifiedRoboqlQuery`.
    """

    prompt: str
    """Natural-language description of what to search for."""


class SetSummaryRequest(pydantic.BaseModel):
    """Request body that replaces the AI summary of a dataset or a session.

    Sent by :py:meth:`~roboto.domain.datasets.Dataset.set_summary` and
    :py:meth:`~roboto.experimental.sessions.Session.set_summary`.
    """

    summary: str
    """Text of the summary, rendered as Markdown.

    It can include ``roboto://`` links to Roboto resources, which the Roboto web app renders as links.
    """
