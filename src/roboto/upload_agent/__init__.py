# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Upload agent: a command-line program that uploads directories on a local machine to Roboto as datasets.

Run ``roboto-agent configure`` (or ``python -m roboto.upload_agent configure``) once to choose the directories the
agent scans, then ``roboto-agent run`` to upload each directory under them that contains an upload config file
(``.roboto_upload.json`` by default) to a dataset of its own. The agent writes ``.roboto_upload_complete.json`` into
each directory it finishes and skips that directory on later runs. This package exports nothing: to upload from
Python, import :py:class:`~roboto.upload_agent.agent.UploadAgent` from ``roboto.upload_agent.agent`` and pass it an
:py:class:`~roboto.upload_agent.files.UploadAgentConfig` from ``roboto.upload_agent.files``.
"""
