# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


class AuthZTupleRecord(pydantic.BaseModel):
    """Deprecated. Data record of an access tuple, as the Roboto API returns it on API versions before 2026-11-19.

    Use :py:class:`~roboto.auth.AccessGrant` instead, the form the access routes of datasets, collections and Views
    take and return from API version 2026-11-19. A tuple gives a principal, such as a user, one relation to one
    resource, such as ``viewer`` on a collection. :py:meth:`~roboto.domain.collections.Collection.get_access`
    returns these records, and :py:meth:`~roboto.domain.collections.Collection.edit_access` sends them to add and
    remove tuples.
    """

    user: str
    """Principal that holds the relation, as ``<type>:<id>``, such as ``user:<user_id>`` or ``group:<group_id>``."""

    relation: str
    """Relation the principal holds to the resource, such as ``viewer`` or ``editor``."""

    obj: str
    """Resource the relation is to, as ``<type>:<id>``, such as ``collection:<collection_id>``."""


class EditAccessRequest(pydantic.BaseModel):
    """Deprecated. Request body for :py:meth:`~roboto.domain.collections.Collection.edit_access`.

    Use :py:class:`~roboto.auth.EditRecordAccessRequest` instead, which the access routes of datasets, collections
    and Views take from API version 2026-11-19. They take this request only on API versions before 2026-11-19.
    """

    add: list[AuthZTupleRecord] = pydantic.Field(default_factory=list)
    """Tuples to add. Defaults to none."""

    remove: list[AuthZTupleRecord] = pydantic.Field(default_factory=list)
    """Tuples to remove. Defaults to none."""


class GetAccessResponse(pydantic.BaseModel):
    """Deprecated. Response body of :py:meth:`~roboto.domain.collections.Collection.get_access`.

    Use :py:class:`~roboto.auth.RecordAccessResponse` instead, which the access routes of datasets, collections and
    Views return from API version 2026-11-19. They return this response only on API versions before 2026-11-19.
    :py:meth:`~roboto.domain.collections.Collection.edit_access` returns it too, holding the tuples after the edit.
    """

    relations: list[AuthZTupleRecord]
    """Tuples on the resource.

    They name its owner, a View's author, a dataset's collections, an ``associated_group`` tuple for each group with
    access across the resource's organization (the organization's own group unless the resource is restricted), and
    the resource's grants. Access that follows from a tuple, such as the access each member of a group has, is not
    listed separately.
    """

    group_permissions: dict[str, list[str]] = pydantic.Field(default_factory=dict)
    """Unused. Roboto always returns an empty dictionary."""
