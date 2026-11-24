# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import copy
import typing

import pydantic

from .warnings import experimental

StrSequence = typing.Union[list[str], tuple[str, ...], set[str]]
"""Strings given as a list, tuple, or set."""


class TaglessMetadataChangeset(pydantic.BaseModel):
    """Changes to the metadata of a resource that has no tags, such as a topic's message path.

    Pass one to :py:meth:`~roboto.domain.topics.Topic.update_message_path`.
    """

    put_fields: typing.Optional[dict[str, typing.Any]] = None
    """Metadata fields to set, keyed by name, each replacing any current value.

    A key in dot notation, such as ``"calibration.gain"``, names a nested field.
    """

    remove_fields: typing.Optional[StrSequence] = None
    """Keys of metadata fields to remove, in the same dot notation. A key the metadata lacks is ignored."""

    replace_all: bool = False
    """Whether the changeset replaces all metadata with ``put_fields``, ignoring ``remove_fields``.

    ``from_replacement_metadata`` sets it.
    """

    class Builder:
        """Builder that collects metadata fields to put and to remove into a ``TaglessMetadataChangeset``."""

        __put_fields: dict[str, typing.Any]
        __remove_fields: list[str]

        def __init__(self) -> None:
            self.__put_fields = dict()
            self.__remove_fields = []

        def put_field(self, key: str, value: typing.Any) -> "TaglessMetadataChangeset.Builder":
            """Add a metadata field to put.

            Returns:
                This builder, so that calls can be chained.
            """
            self.__put_fields[key] = value
            return self

        def remove_field(self, key: str) -> "TaglessMetadataChangeset.Builder":
            """Add the key of a metadata field to remove.

            Returns:
                This builder, so that calls can be chained.
            """
            self.__remove_fields.append(key)
            return self

        def build(self) -> "TaglessMetadataChangeset":
            """Return a changeset of the changes this builder collected."""
            changeset: collections.abc.Mapping = {
                "put_fields": self.__put_fields,
                "remove_fields": self.__remove_fields,
            }
            return TaglessMetadataChangeset(**{k: v for k, v in changeset.items() if v})

    @classmethod
    def from_replacement_metadata(cls, metadata: dict[str, typing.Any]) -> "TaglessMetadataChangeset":
        """Build a changeset that replaces all of a resource's metadata with ``metadata``.

        Args:
            metadata: Metadata the resource has after the update.
        """

        return cls(put_fields=metadata, replace_all=True)

    def apply_field_updates(self, existing_metadata: dict[str, typing.Any]) -> dict[str, typing.Any]:
        """Return the metadata that results from applying this changeset to ``existing_metadata``.

        Behaves as ``MetadataChangeset.apply_field_updates`` does.

        Args:
            existing_metadata: Current metadata of the resource. Not modified.

        Returns:
            A new dictionary of the updated metadata, or ``put_fields`` itself when ``replace_all`` is set.

        Raises:
            IndexError: A key in ``put_fields`` indexes past the end of a list before its last part.
            ValueError: A part of a key that reaches a list is not an integer.
        """
        if self.replace_all:
            return self.put_fields or {}

        updated_metadata = copy.deepcopy(existing_metadata)
        if self.put_fields:
            for key, value in self.put_fields.items():
                self.__set_nested(updated_metadata, key, value)
        if self.remove_fields:
            for key in self.remove_fields:
                self.__del_nested(updated_metadata, key)
        return updated_metadata

    def has_changes(self) -> bool:
        """Return whether the changeset has fields to put or remove, or replaces the metadata."""

        return self.replace_all or any([len(self.put_fields or {}), len(self.remove_fields or [])])

    def __set_nested(self, obj: dict[str, typing.Any], key: str, value: typing.Any) -> None:
        keys = key.split(".")
        subobj = obj
        for key in keys[:-1]:
            if isinstance(subobj, collections.abc.MutableSequence):
                key = int(key)
                if key >= len(subobj):
                    raise IndexError(f"Index {key} out of range for {subobj}")
                subobj = subobj[key]
            else:
                subobj = subobj.setdefault(key, {})

        if isinstance(subobj, collections.abc.MutableMapping):
            subobj[keys[-1]] = value
        elif isinstance(subobj, collections.abc.MutableSequence):
            subobj.insert(int(keys[-1]), value)

    def __del_nested(self, obj: dict[str, typing.Any], key: str) -> None:
        def __key_in_collection(key: typing.Union[str, int], collection: collections.abc.Collection) -> bool:
            if isinstance(collection, collections.abc.MutableSequence):
                key = int(key)
                return key < len(collection)
            else:
                return key in collection

        def __del_from_collection(key: typing.Union[str, int], collection: collections.abc.Collection) -> None:
            if not __key_in_collection(key, collection):
                return

            if isinstance(collection, collections.abc.MutableMapping):
                del collection[key]
            elif isinstance(collection, collections.abc.MutableSequence):
                collection.pop(int(key))

        keys = key.split(".")
        # Each entry is (collection, its key in its parent, its parent); the root entry has no key or parent.
        path: list[
            tuple[
                typing.Union[collections.abc.MutableMapping, collections.abc.MutableMapping],
                typing.Optional[typing.Union[str, int]],
                typing.Optional[typing.Union[collections.abc.MutableMapping, collections.abc.MutableMapping]],
            ]
        ] = [(obj, None, None)]
        for key in keys[:-1]:
            sub_obj, _, _ = path[-1]
            if isinstance(sub_obj, collections.abc.MutableSequence):
                key = int(key)

            if not __key_in_collection(key, sub_obj):
                return

            path.append((sub_obj[key], key, sub_obj))

        __del_from_collection(keys[-1], path[-1][0])

        # Remove each collection the removal left empty, innermost first.
        for _, key_path, parent_obj in reversed(path):
            if key_path is None or parent_obj is None:
                return

            if isinstance(parent_obj, collections.abc.MutableSequence):
                key_path = int(key_path)

            if not __key_in_collection(key_path, parent_obj):
                return

            if not len(parent_obj[key_path]):
                __del_from_collection(key_path, parent_obj)


class MetadataChangeset(pydantic.BaseModel):
    """Changes to a resource's tags and metadata.

    Pass one to an update method such as :py:meth:`~roboto.domain.datasets.Dataset.update`. Keys in ``put_fields``
    and ``remove_fields`` may name a nested field in dot notation, such as ``"calibration.gain"``, except on
    datasets, files and sessions, which apply each key as one top-level key.
    """

    put_tags: typing.Optional[StrSequence] = None
    """Tags to add. A tag the resource already has is not added again."""

    remove_tags: typing.Optional[StrSequence] = None
    """Tags to remove. A tag the resource does not have is ignored."""

    put_fields: typing.Optional[dict[str, typing.Any]] = None
    """Metadata fields to set, keyed by name, each replacing any current value."""

    remove_fields: typing.Optional[StrSequence] = None
    """Keys of metadata fields to remove. A key the metadata lacks is ignored."""

    replace_all: bool = False
    """Whether the changeset replaces the resource's tags and metadata with ``put_tags`` and ``put_fields``.

    When set, ``remove_tags`` and ``remove_fields`` are ignored. Datasets and files ignore ``replace_all`` itself and
    apply the rest of the changeset. ``from_metadata`` sets it.
    """

    class Builder:
        """Builder that collects tags and metadata fields to put and to remove into a ``MetadataChangeset``."""

        __put_tags: list[str]
        __remove_tags: list[str]
        __put_fields: dict[str, typing.Any]
        __remove_fields: list[str]

        def __init__(self) -> None:
            self.__put_tags = []
            self.__remove_tags = []
            self.__put_fields = dict()
            self.__remove_fields = []

        def put_tag(self, tag: str) -> "MetadataChangeset.Builder":
            """Add a tag to put.

            Returns:
                This builder, so that calls can be chained.
            """
            self.__put_tags.append(tag)
            return self

        def remove_tag(self, tag: str) -> "MetadataChangeset.Builder":
            """Add a tag to remove.

            Returns:
                This builder, so that calls can be chained.
            """
            self.__remove_tags.append(tag)
            return self

        def put_field(self, key: str, value: typing.Any) -> "MetadataChangeset.Builder":
            """Add a metadata field to put.

            Returns:
                This builder, so that calls can be chained.
            """
            self.__put_fields[key] = value
            return self

        def remove_field(self, key: str) -> "MetadataChangeset.Builder":
            """Add the key of a metadata field to remove.

            Returns:
                This builder, so that calls can be chained.
            """
            self.__remove_fields.append(key)
            return self

        def build(self) -> "MetadataChangeset":
            """Return a changeset of the changes this builder collected."""
            changeset: collections.abc.Mapping = {
                "put_tags": self.__put_tags,
                "remove_tags": self.__remove_tags,
                "put_fields": self.__put_fields,
                "remove_fields": self.__remove_fields,
            }
            return MetadataChangeset(**{k: v for k, v in changeset.items() if v})

    @classmethod
    def from_metadata(cls, metadata: typing.Mapping[str, typing.Any]) -> "MetadataChangeset":
        """Build a changeset that replaces a resource's metadata with ``metadata`` and removes all of its tags.

        On datasets and files, which ignore ``replace_all``, it merges ``metadata`` into the existing metadata instead
        and keeps the tags.

        Args:
            metadata: Metadata the resource has after the update.
        """
        return cls(put_fields=dict(metadata), replace_all=True)

    def apply_field_updates(self, existing_metadata: dict[str, typing.Any]) -> dict[str, typing.Any]:
        """Return the metadata that results from applying this changeset to ``existing_metadata``.

        Sets each field in ``put_fields``, then removes each key in ``remove_fields``, so a key in both ends up
        removed. Each part of a dotted key names a key in a nested dictionary, which is created when missing, or an
        index when the value reached so far is a list; setting a value at a list index inserts it there. Removing a
        key also removes each dictionary or list the removal leaves empty, and removing a key the metadata lacks
        changes nothing.

        Args:
            existing_metadata: Current metadata of the resource. Not modified.

        Returns:
            A new dictionary of the updated metadata, or ``put_fields`` itself when ``replace_all`` is set.

        Raises:
            IndexError: A key in ``put_fields`` indexes past the end of a list before its last part.
            ValueError: A part of a key that reaches a list is not an integer.
        """
        if self.replace_all:
            return self.put_fields or {}

        updated_metadata = copy.deepcopy(existing_metadata)
        if self.put_fields:
            for key, value in self.put_fields.items():
                self.__set_nested(updated_metadata, key, value)
        if self.remove_fields:
            for key in self.remove_fields:
                self.__del_nested(updated_metadata, key)
        return updated_metadata

    def apply_tag_updates(self, existing_tags: list[str]) -> StrSequence:
        """Return the tags that result from applying this changeset to ``existing_tags``.

        Appends each tag in ``put_tags`` that the list lacks, then removes each tag in ``remove_tags``, so a tag in
        both ends up removed. When ``replace_all`` is set, returns ``put_tags`` itself, or an empty list.

        Args:
            existing_tags: Current tags of the resource. Not modified.
        """
        if self.replace_all:
            return self.put_tags or []

        updated_tags = existing_tags.copy()
        if self.put_tags:
            for tag in self.put_tags:
                if tag not in updated_tags:
                    updated_tags.append(tag)
        if self.remove_tags:
            updated_tags = [tag for tag in updated_tags if tag not in self.remove_tags]

        return updated_tags

    @staticmethod
    def __combine_strseq_field(
        first: typing.Optional[StrSequence], second: typing.Optional[StrSequence]
    ) -> typing.Optional[StrSequence]:
        combined = list(set(first or []) | set(second or []))
        return None if len(combined) == 0 else combined

    @staticmethod
    def __combine_dict_field(
        first: typing.Optional[dict[str, typing.Any]],
        second: typing.Optional[dict[str, typing.Any]],
    ) -> typing.Optional[dict[str, typing.Any]]:
        combined: dict[str, typing.Any] = dict()
        combined.update(first or {})
        combined.update(second or {})
        return None if len(combined) == 0 else combined

    def combine(self, other: "MetadataChangeset") -> "MetadataChangeset":
        """Return a changeset that holds the changes of both this changeset and ``other``.

        Each tag and key appears once in the result, in no fixed order. When both changesets put the same field,
        ``other``'s value wins. The result never replaces tags or metadata, even when either changeset does: its
        ``replace_all`` is ``False``.

        Args:
            other: Changeset to merge with this one.
        """
        return MetadataChangeset(
            put_tags=self.__combine_strseq_field(self.put_tags, other.put_tags),
            remove_tags=self.__combine_strseq_field(self.remove_tags, other.remove_tags),
            remove_fields=self.__combine_strseq_field(self.remove_fields, other.remove_fields),
            put_fields=self.__combine_dict_field(self.put_fields, other.put_fields),
        )

    def is_empty(self) -> bool:
        """Return whether the changeset has no tags or fields to put or remove, and does not replace them."""
        return not self.replace_all and not any(
            [
                self.put_tags,
                self.remove_tags,
                self.put_fields,
                self.remove_fields,
            ]
        )

    def __set_nested(self, obj: dict[str, typing.Any], key: str, value: typing.Any) -> None:
        keys = key.split(".")
        subobj = obj
        for key in keys[:-1]:
            if isinstance(subobj, collections.abc.MutableSequence):
                key = int(key)
                if key >= len(subobj):
                    raise IndexError(f"Index {key} out of range for {subobj}")
                subobj = subobj[key]
            else:
                subobj = subobj.setdefault(key, {})

        if isinstance(subobj, collections.abc.MutableMapping):
            subobj[keys[-1]] = value
        elif isinstance(subobj, collections.abc.MutableSequence):
            subobj.insert(int(keys[-1]), value)

    def __del_nested(self, obj: dict[str, typing.Any], key: str) -> None:
        def __key_in_collection(key: typing.Union[str, int], collection: collections.abc.Collection) -> bool:
            if isinstance(collection, collections.abc.MutableSequence):
                key = int(key)
                return key < len(collection)
            else:
                return key in collection

        def __del_from_collection(key: typing.Union[str, int], collection: collections.abc.Collection) -> None:
            if not __key_in_collection(key, collection):
                return

            if isinstance(collection, collections.abc.MutableMapping):
                del collection[key]
            elif isinstance(collection, collections.abc.MutableSequence):
                collection.pop(int(key))

        keys = key.split(".")
        # Each entry is (collection, its key in its parent, its parent); the root entry has no key or parent.
        path: list[
            tuple[
                typing.Union[collections.abc.MutableMapping, collections.abc.MutableMapping],
                typing.Optional[typing.Union[str, int]],
                typing.Optional[typing.Union[collections.abc.MutableMapping, collections.abc.MutableMapping]],
            ]
        ] = [(obj, None, None)]
        for key in keys[:-1]:
            sub_obj, _, _ = path[-1]
            if isinstance(sub_obj, collections.abc.MutableSequence):
                key = int(key)

            if not __key_in_collection(key, sub_obj):
                return

            path.append((sub_obj[key], key, sub_obj))

        __del_from_collection(keys[-1], path[-1][0])

        # Remove each collection the removal left empty, innermost first.
        for _, key_path, parent_obj in reversed(path):
            if key_path is None or parent_obj is None:
                return

            if isinstance(parent_obj, collections.abc.MutableSequence):
                key_path = int(key_path)

            if not __key_in_collection(key_path, parent_obj):
                return

            if not len(parent_obj[key_path]):
                __del_from_collection(key_path, parent_obj)


@experimental
class CustomFieldChangeset(pydantic.BaseModel):
    """Changes to a resource's custom field values.

    Pass one to an update method such as :py:meth:`~roboto.domain.datasets.Dataset.update`. Each field it names must
    be a custom field the organization defines for that kind of resource, in the
    :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready` state, and each value must match the field's
    declared type. Fields the changeset does not name keep their values, and a cleared field reads back as ``None``.
    Building a changeset that both sets and clears the same field raises ``pydantic.ValidationError``.
    """

    set_fields: typing.Optional[dict[str, typing.Any]] = None
    """Custom field values to set, keyed by field name, each replacing any current value.

    Each value's Python type must match the field's :py:class:`~roboto.domain.custom_fields.CustomFieldType`.
    """

    clear_fields: typing.Optional[StrSequence] = None
    """Names of custom fields to clear."""

    @pydantic.model_validator(mode="after")
    def _reject_overlap(self) -> "CustomFieldChangeset":
        if self.set_fields and self.clear_fields:
            overlap = set(self.set_fields) & set(self.clear_fields)
            if overlap:
                names = ", ".join(sorted(overlap))
                raise ValueError(f"CustomFieldChangeset cannot both set and clear the same field(s): {names}")
        return self

    class Builder:
        """Builder that collects custom fields to set and to clear into a ``CustomFieldChangeset``."""

        __set_fields: dict[str, typing.Any]
        __clear_fields: list[str]

        def __init__(self) -> None:
            self.__set_fields = dict()
            self.__clear_fields = []

        def set_field(self, name: str, value: typing.Any) -> "CustomFieldChangeset.Builder":
            """Add a custom field value to set.

            Returns:
                This builder, so that calls can be chained.
            """
            self.__set_fields[name] = value
            return self

        def clear_field(self, name: str) -> "CustomFieldChangeset.Builder":
            """Add the name of a custom field to clear.

            Returns:
                This builder, so that calls can be chained.
            """
            self.__clear_fields.append(name)
            return self

        def build(self) -> "CustomFieldChangeset":
            """Return a changeset of the changes this builder collected.

            Raises:
                pydantic.ValidationError: The builder both sets and clears the same field.
            """
            payload: collections.abc.Mapping = {
                "set_fields": self.__set_fields,
                "clear_fields": self.__clear_fields,
            }
            return CustomFieldChangeset(**{k: v for k, v in payload.items() if v})

    def apply_field_updates(self, existing: dict[str, typing.Any]) -> dict[str, typing.Any]:
        """Return a copy of ``existing`` with ``set_fields`` set and each field in ``clear_fields`` set to ``None``.

        Args:
            existing: Custom field values keyed by field name. Not modified.
        """
        updated = dict(existing)
        for name, value in (self.set_fields or {}).items():
            updated[name] = value
        for name in self.clear_fields or []:
            updated[name] = None
        return updated

    def combine(self, other: "CustomFieldChangeset") -> "CustomFieldChangeset":
        """Return a changeset with the effect of applying this changeset and then ``other``.

        Where the two set or clear the same field, ``other``'s change wins.

        Args:
            other: Changeset to apply after this one.
        """
        set_combined: dict[str, typing.Any] = {}
        set_combined.update(self.set_fields or {})
        set_combined.update(other.set_fields or {})

        clear_combined = set(self.clear_fields or []) | set(other.clear_fields or [])

        for name in (other.set_fields or {}).keys():
            clear_combined.discard(name)
        for name in other.clear_fields or []:
            set_combined.pop(name, None)

        return CustomFieldChangeset(
            set_fields=set_combined or None,
            clear_fields=sorted(clear_combined) or None,
        )

    def is_empty(self) -> bool:
        """Return whether the changeset sets and clears no fields."""
        return not (self.set_fields or self.clear_fields)


class UpdateCondition(pydantic.BaseModel):
    """Condition on a resource's current value that an update must meet to succeed.

    The update succeeds only when the current value of ``key`` compares to ``value`` as ``comparator`` requires.
    Building one with a ``comparator`` other than ``"eq"`` or ``"ne"`` raises ``pydantic.ValidationError``. No SDK
    method or Roboto route uses this model.
    """

    key: str
    """Name of the resource's field to compare."""

    value: typing.Any = None
    """Value to compare the field's current value with."""

    comparator: typing.Literal["eq", "ne"]
    """How the two values must compare: ``"eq"`` requires them to be equal, ``"ne"`` requires them to differ."""
