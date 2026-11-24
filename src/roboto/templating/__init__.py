# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Substitution of ``{{name}}`` placeholders, such as those in an agent's request template or a trigger's target.

To expand the placeholders in a value, use :py:func:`~roboto.templating.substitute` with a
:py:class:`~roboto.templating.VariableResolver`, such as :py:class:`~roboto.templating.MappingResolver`; to find
them, use :py:func:`~roboto.templating.collect_placeholders`.
"""

from .substitution import (
    PLACEHOLDER_RE,
    VARIABLE_NAME_RE,
    MappingResolver,
    VariableResolver,
    collect_placeholders,
    substitute,
)

__all__ = [
    "MappingResolver",
    "PLACEHOLDER_RE",
    "VARIABLE_NAME_RE",
    "VariableResolver",
    "collect_placeholders",
    "substitute",
]
