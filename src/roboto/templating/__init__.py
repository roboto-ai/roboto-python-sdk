# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Generic ``{{name}}`` placeholder substitution shared across the SDK.

The same lightweight templating primitive powers reusable agent definitions
(client-side substitution of caller-supplied values before a thread starts) and
event triggers (server-side substitution of event-derived variables into a
target's request). A :class:`VariableResolver` binds placeholders to a source of
values, so the substitution engine stays agnostic to where those values come from.
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
