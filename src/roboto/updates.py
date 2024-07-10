# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import copy
import typing

import pydantic

StrSequence = typing.Union[list[str], tuple[str, ...], set[str]]


class TaglessMetadataChangeset(pydantic.BaseModel):
    # Add each field in this dict if it doesn't exist, else overwrite the existing value
    # Expands dot notation to nested objects
    put_fields: typing.Optional[dict[str, typing.Any]] = None
    # Remove each field in this sequence if it exists
    # Expands dot notation to nested objects
    remove_fields: typing.Optional[StrSequence] = None

    class Builder:
        __put_fields: dict[str, typing.Any]
        __remove_fields: list[str]

        def __init__(self) -> None:
            self.__put_fields = dict()
            self.__remove_fields = []

        def put_field(
            self, key: str, value: typing.Any
        ) -> "TaglessMetadataChangeset.Builder":
            self.__put_fields[key] = value
            return self

        def remove_field(self, key: str) -> "TaglessMetadataChangeset.Builder":
            self.__remove_fields.append(key)
            return self

        def build(self) -> "TaglessMetadataChangeset":
            changeset: collections.abc.Mapping = {
                "put_fields": self.__put_fields,
                "remove_fields": self.__remove_fields,
            }
            return TaglessMetadataChangeset(**{k: v for k, v in changeset.items() if v})

    def apply_field_updates(
        self, existing_metadata: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        updated_metadata = copy.deepcopy(existing_metadata)
        if self.put_fields:
            for key, value in self.put_fields.items():
                self.__set_nested(updated_metadata, key, value)
        if self.remove_fields:
            for key in self.remove_fields:
                self.__del_nested(updated_metadata, key)
        return updated_metadata

    def __set_nested(
        self, obj: dict[str, typing.Any], key: str, value: typing.Any
    ) -> None:
        """
        Set nested path to value using dot notation
        """
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
        """
        Delete a value from nested path using dot notation
        """

        def __key_in_collection(
            key: typing.Union[str, int], collection: collections.abc.Collection
        ) -> bool:
            if isinstance(collection, collections.abc.MutableSequence):
                key = int(key)
                return key < len(collection)
            else:
                return key in collection

        def __del_from_collection(
            key: typing.Union[str, int], collection: collections.abc.Collection
        ) -> None:
            if not __key_in_collection(key, collection):
                return

            if isinstance(collection, collections.abc.MutableMapping):
                del collection[key]
            elif isinstance(collection, collections.abc.MutableSequence):
                collection.pop(int(key))

        keys = key.split(".")
        path: list[
            tuple[
                # subobj
                typing.Union[
                    collections.abc.MutableMapping, collections.abc.MutableMapping
                ],
                # key
                typing.Optional[typing.Union[str, int]],
                # parent_obj
                typing.Optional[
                    typing.Union[
                        collections.abc.MutableMapping, collections.abc.MutableMapping
                    ]
                ],
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

        # remove any now empty collections, working backwards
        for _, key_path, parent_obj in reversed(path):
            if key_path is None or parent_obj is None:
                # root object
                return

            if isinstance(parent_obj, collections.abc.MutableSequence):
                key_path = int(key_path)

            if not __key_in_collection(key_path, parent_obj):
                return

            if not len(parent_obj[key_path]):
                __del_from_collection(key_path, parent_obj)


# TODO https://roboto.atlassian.net/browse/ROBO-903, change this to a mixin model to handle tags and/or metadata
class MetadataChangeset(pydantic.BaseModel):
    # Add each tag in this sequence if it doesn't exist
    put_tags: typing.Optional[StrSequence] = None
    # Remove each tag in this sequence if it exists
    remove_tags: typing.Optional[StrSequence] = None
    # Add each field in this dict if it doesn't exist, else overwrite the existing value
    # Expands dot notation to nested objects
    put_fields: typing.Optional[dict[str, typing.Any]] = None
    # Remove each field in this sequence if it exists
    # Expands dot notation to nested objects
    remove_fields: typing.Optional[StrSequence] = None

    class Builder:
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
            self.__put_tags.append(tag)
            return self

        def remove_tag(self, tag: str) -> "MetadataChangeset.Builder":
            self.__remove_tags.append(tag)
            return self

        def put_field(self, key: str, value: typing.Any) -> "MetadataChangeset.Builder":
            self.__put_fields[key] = value
            return self

        def remove_field(self, key: str) -> "MetadataChangeset.Builder":
            self.__remove_fields.append(key)
            return self

        def build(self) -> "MetadataChangeset":
            changeset: collections.abc.Mapping = {
                "put_tags": self.__put_tags,
                "remove_tags": self.__remove_tags,
                "put_fields": self.__put_fields,
                "remove_fields": self.__remove_fields,
            }
            return MetadataChangeset(**{k: v for k, v in changeset.items() if v})

    def apply_field_updates(
        self, existing_metadata: dict[str, typing.Any]
    ) -> dict[str, typing.Any]:
        updated_metadata = copy.deepcopy(existing_metadata)
        if self.put_fields:
            for key, value in self.put_fields.items():
                self.__set_nested(updated_metadata, key, value)
        if self.remove_fields:
            for key in self.remove_fields:
                self.__del_nested(updated_metadata, key)
        return updated_metadata

    def apply_tag_updates(self, existing_tags: list[str]) -> StrSequence:
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
        return MetadataChangeset(
            put_tags=self.__combine_strseq_field(self.put_tags, other.put_tags),
            remove_tags=self.__combine_strseq_field(
                self.remove_tags, other.remove_tags
            ),
            remove_fields=self.__combine_strseq_field(
                self.remove_fields, other.remove_fields
            ),
            put_fields=self.__combine_dict_field(self.put_fields, other.put_fields),
        )

    def is_empty(self) -> bool:
        return not any(
            [
                self.put_tags,
                self.remove_tags,
                self.put_fields,
                self.remove_fields,
            ]
        )

    def __set_nested(
        self, obj: dict[str, typing.Any], key: str, value: typing.Any
    ) -> None:
        """
        Set nested path to value using dot notation
        """
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
        """
        Delete a value from nested path using dot notation
        """

        def __key_in_collection(
            key: typing.Union[str, int], collection: collections.abc.Collection
        ) -> bool:
            if isinstance(collection, collections.abc.MutableSequence):
                key = int(key)
                return key < len(collection)
            else:
                return key in collection

        def __del_from_collection(
            key: typing.Union[str, int], collection: collections.abc.Collection
        ) -> None:
            if not __key_in_collection(key, collection):
                return

            if isinstance(collection, collections.abc.MutableMapping):
                del collection[key]
            elif isinstance(collection, collections.abc.MutableSequence):
                collection.pop(int(key))

        keys = key.split(".")
        path: list[
            tuple[
                # subobj
                typing.Union[
                    collections.abc.MutableMapping, collections.abc.MutableMapping
                ],
                # key
                typing.Optional[typing.Union[str, int]],
                # parent_obj
                typing.Optional[
                    typing.Union[
                        collections.abc.MutableMapping, collections.abc.MutableMapping
                    ]
                ],
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

        # remove any now empty collections, working backwards
        for _, key_path, parent_obj in reversed(path):
            if key_path is None or parent_obj is None:
                # root object
                return

            if isinstance(parent_obj, collections.abc.MutableSequence):
                key_path = int(key_path)

            if not __key_in_collection(key_path, parent_obj):
                return

            if not len(parent_obj[key_path]):
                __del_from_collection(key_path, parent_obj)


class UpdateCondition(pydantic.BaseModel):
    """
    A condition to be applied to an update operation, succeeding only if the condition evaluates to True at update-time.

    `value` is compared to the resource's current value of `key` using `comparator`.

    This is a severely constrainted subset of the conditions supported by DynamoDB. See:
    https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.OperatorsAndFunctions.html
    """

    key: str
    value: typing.Any = None
    # Comparators are tied to convenience methods exposed on boto3.dynamodb.conditions.Attr. See:
    # https://github.com/boto/boto3/blob/5ad1a624111ed25efc81f425113fa51150516bb4/boto3/dynamodb/conditions.py#L246
    comparator: typing.Literal["eq", "ne"]
