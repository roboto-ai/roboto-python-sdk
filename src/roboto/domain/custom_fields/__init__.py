# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Custom fields: typed fields an organization defines for one entity type, such as datasets, to search and sort by.

Set a field's value on an entity with that entity's methods, such as
:py:meth:`~roboto.domain.datasets.Dataset.set_custom_field`. Use :py:class:`~roboto.domain.custom_fields.CustomField`
to create, find, update, and delete custom fields.
"""

from .custom_field import CustomField
from .operations import CreateCustomFieldRequest, ListCustomFieldsRequest, UpdateCustomFieldRequest
from .record import (
    CUSTOM_FIELD_NAME_PATTERN,
    CustomFieldOptions,
    CustomFieldRecord,
    CustomFieldStatus,
    CustomFieldType,
    EnumFieldOptions,
    TargetEntityType,
)

__all__ = [
    "CUSTOM_FIELD_NAME_PATTERN",
    "CustomField",
    "CustomFieldOptions",
    "CustomFieldRecord",
    "CustomFieldStatus",
    "CustomFieldType",
    "CreateCustomFieldRequest",
    "EnumFieldOptions",
    "ListCustomFieldsRequest",
    "TargetEntityType",
    "UpdateCustomFieldRequest",
]
