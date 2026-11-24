# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Roboto CLI: a command-line program that works with Roboto resources, such as datasets and actions, from a terminal.

Run ``roboto`` (or ``python -m roboto.cli``) followed by a command group, such as ``roboto datasets``;
``roboto --help`` lists the groups. ``entry`` runs the program, and ``construct_parser`` builds its
``argparse.ArgumentParser`` without running it. ``__version__`` is fixed at ``"0.0.1"`` and is not the SDK's
version: ``roboto --version`` prints ``roboto.version.__version__``.
"""

from .entry import construct_parser, entry

__version__ = "0.0.1"

__all__ = ["__version__", "entry", "construct_parser"]
