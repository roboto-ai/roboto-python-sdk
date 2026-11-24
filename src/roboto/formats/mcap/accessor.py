# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import abc
import collections.abc
import dataclasses
import typing

from ...collection_utils import defaultlist

if typing.TYPE_CHECKING:
    from ..fields import FieldSelection


def is_codec_time_value(val: typing.Any) -> bool:
    """Return whether ``val`` is a ROS 2 ``Time`` or ``Duration`` value, as the SDK's ROS decoder returns it.

    :py:meth:`~roboto.formats.mcap.decoded_message.DecodedMessage.to_dict` recognizes these values through it, so most
    code never calls it. The decoder returns such a value as a dictionary with exactly the keys ``sec`` and ``nanosec``
    and nothing else marking it as a time, so the check compares keys. Some topics' message paths name the sub-second
    field ``nsec``; recognizing the value lets the SDK read ``nanosec`` for such a path, which would otherwise read
    nothing. ROS 1 ``Time`` values and JSON time values use the key ``nsec``, so they do not match and need no renaming.

    Args:
        val: Decoded value to test.
    """
    return isinstance(val, dict) and val.keys() == {"sec", "nanosec"}


class AttrGetter(abc.ABC):
    """Attribute reader for decoded MCAP messages, which accessors use to walk a message along a field's path.

    The SDK's own code uses it; to read selected fields from an MCAP file, use
    :py:class:`~roboto.formats.mcap.McapReader` instead. Every decoder the SDK uses returns messages as dictionaries,
    so ``DictAttrGetter`` is the only implementation.
    """

    @staticmethod
    @abc.abstractmethod
    def get_attribute_names(value) -> collections.abc.Sequence[str]:
        """Return the names of the attributes ``value`` holds.

        Args:
            value: Decoded message, or a value within one.
        """

    @staticmethod
    @abc.abstractmethod
    def get_attribute(value, attribute) -> typing.Any:
        """Return the value of ``attribute`` in ``value``.

        Call it only after ``has_attribute`` returns ``True`` for the same arguments.

        Args:
            value: Decoded message, or a value within one.
            attribute: Name of the attribute to read.
        """

    @staticmethod
    @abc.abstractmethod
    def has_attribute(value, attribute: str) -> bool:
        """Return whether ``value`` holds ``attribute``.

        Returns ``False``, rather than raising, when ``value`` cannot hold attributes, such as a JSON ``null``, a
        scalar, or a list, so a walk along a path stops there.

        Args:
            value: Decoded message, or a value within one.
            attribute: Name of the attribute to look for.
        """

    @staticmethod
    @abc.abstractmethod
    def has_sub_attributes(value) -> bool:
        """Return whether ``value`` can hold attributes, so a walk along a path can continue into it.

        Args:
            value: Decoded message, or a value within one.
        """


class DictAttrGetter(AttrGetter):
    """Attribute reader that reads decoded messages held as dictionaries.

    The JSON, msgpack and ROS decoders return messages, and the structures nested in them, as dictionaries. Any value
    that is not a dictionary has no attributes.
    """

    @staticmethod
    def get_attribute_names(value):
        return value.keys()

    @staticmethod
    def get_attribute(value, attribute):
        return value[attribute]

    @staticmethod
    def has_attribute(value, attribute: str) -> bool:
        return isinstance(value, dict) and attribute in value

    @staticmethod
    def has_sub_attributes(value):
        return isinstance(value, dict)


# The getter holds no state, so getter_for returns this one instance rather than building one per to_dict() call.
_DICT_GETTER = DictAttrGetter()


def getter_for(message: typing.Any) -> AttrGetter:
    """Return the attribute reader for ``message``.

    :py:meth:`~roboto.formats.mcap.decoded_message.DecodedMessage.to_dict` finds each message's attribute reader through
    it, so most code never calls it. Every decoder returns messages as dictionaries, and ``DictAttrGetter`` treats any
    other value as having no attributes, so this returns the same ``DictAttrGetter`` for every message.

    Args:
        message: Decoded message to read.
    """
    return _DICT_GETTER


Accumulator = dict[str, typing.Any]
"""Dictionary that accessors write selected fields into, nested the way the message is."""

Accessor = typing.Callable[[typing.Any, Accumulator], None]
"""Function that copies one field's value from a decoded message into an ``Accumulator``, and returns ``None``.

``compile_accessors`` builds one per field from a sample message. Building it finds, from the sample, where the
field's path crosses a sequence and which ``nsec`` components to read as ``nanosec``, so a call does only dictionary
lookups and writes. A message that lacks the field leaves it unwritten.
"""

PathInSchema = tuple[str, ...]
"""Path of one field through a message's schema, such as ``("header", "stamp", "sec")``."""


class AccessorCache:
    """Cache of the accessors compiled for one read of an MCAP file, keyed by the paths of the fields they read.

    Each :py:class:`~roboto.formats.mcap.McapReader` holds one and passes it to every
    :py:class:`~roboto.formats.mcap.decoded_message.DecodedMessage` it returns, so accessors are compiled once per read
    rather than once per message. Each reader has its own cache because accessors compiled against one topic's
    messages can be wrong for another topic with the same paths, such as when a time field is present in one and
    absent in the other.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[PathInSchema, ...], list[Accessor]] = {}

    def get_or_compile(
        self,
        fields: "collections.abc.Sequence[FieldSelection]",
        sample: typing.Any,
        getter: AttrGetter,
    ) -> list[Accessor]:
        """Return the accessors for ``fields``, compiling them against ``sample`` when the cache has none.

        Accessors compiled against a sample in which a path crosses an empty sequence are returned but not cached:
        the sample shows nothing past the empty sequence, so a later message whose sequence has elements compiles
        them again.

        Args:
            fields: Fields to read. The accessors come back in the same order.
            sample: Decoded message to compile against.
            getter: Attribute reader for ``sample``.
        """
        key = tuple(tuple(field.path_in_schema) for field in fields)
        accessors = self._cache.get(key)
        if accessors is not None:
            return accessors
        accessors, fully_resolved = compile_accessors(fields, sample, getter)
        if fully_resolved:
            self._cache[key] = accessors
        return accessors


def compile_accessors(
    fields: "collections.abc.Sequence[FieldSelection]",
    sample: typing.Any,
    getter: AttrGetter,
) -> tuple[list[Accessor], bool]:
    """Build one accessor per field, compiled against ``sample``, without caching them.

    :py:meth:`~roboto.formats.mcap.decoded_message.DecodedMessage.to_dict` builds a message's accessors through it,
    directly or through ``AccessorCache.get_or_compile``, which caches them, so most code never calls it.

    Args:
        fields: Fields to read.
        sample: Decoded message to compile against.
        getter: Attribute reader for ``sample``.

    Returns:
        ``(accessors, fully_resolved)``: one accessor per field, in the order of ``fields``, and whether ``sample``
        showed every path in full. ``fully_resolved`` is ``False`` when a path crosses a sequence that is empty in
        ``sample``; the accessor then reads the rest of that path as a chain of dictionary keys, which a later message
        may not match, so do not reuse those accessors for later messages.
    """
    accessors: list[Accessor] = []
    fully_resolved = True
    for field in fields:
        accessor, path_fully_resolved = _compile_accessor(field.path_in_schema, sample, getter)
        accessors.append(accessor)
        if not path_fully_resolved:
            fully_resolved = False
    return accessors, fully_resolved


@dataclasses.dataclass(frozen=True)
class _NoneResolution:
    """Resolution of a path the sample lacks partway along; its accessor writes nothing."""


@dataclasses.dataclass(frozen=True)
class _SimpleResolution:
    """Resolution of a path that crosses no sequence, read as a chain of dictionary keys.

    ``path`` may name ``nanosec`` where the field's path named ``nsec``.
    """

    path: PathInSchema


@dataclasses.dataclass(frozen=True)
class _SequenceResolution:
    """Resolution of a path that crosses a sequence at ``pre_path``, with ``sub_resolution`` applied to each element."""

    pre_path: PathInSchema
    sub_resolution: "Resolution"


Resolution = typing.Union[_NoneResolution, _SimpleResolution, _SequenceResolution]
"""Compiled form of one field's path: one that writes nothing, a chain of dictionary keys, or a sequence crossing.

A sequence crossing applies a further resolution to each element of the sequence. Build one with
``none_resolution``, ``simple_resolution`` or ``sequence_resolution``, and turn it into an accessor with
``build_accessor``.
"""


def none_resolution() -> Resolution:
    """Build a resolution whose accessor writes nothing, for a path the message lacks."""
    return _NoneResolution()


def simple_resolution(path: collections.abc.Sequence[str]) -> Resolution:
    """Build a resolution that reads ``path`` as a chain of dictionary keys, crossing no sequence.

    Args:
        path: Keys from the top of the message to the field.
    """
    return _SimpleResolution(tuple(path))


def sequence_resolution(pre_path: collections.abc.Sequence[str], sub: Resolution) -> Resolution:
    """Build a resolution that crosses the sequence at ``pre_path`` and applies ``sub`` to each element.

    Args:
        pre_path: Keys from the top of the message to the sequence.
        sub: Resolution of the rest of the path, from each element of the sequence.
    """
    return _SequenceResolution(tuple(pre_path), sub)


def remap_time_fields(
    resolution: Resolution,
    sample: typing.Any,
    getter: AttrGetter,
) -> tuple[Resolution, bool]:
    """Return ``resolution`` with ``nsec`` renamed to ``nanosec`` past each ROS 2 time value on its path in ``sample``.

    Some topics' message paths name the sub-second field of a ROS 2 ``Time`` or ``Duration`` value ``nsec``, but the
    SDK's ROS decoder returns it under ``nanosec``. This walks ``sample`` along ``resolution`` and renames every
    ``nsec`` component that follows such a value, so the accessor ``build_accessor`` builds from the result reads the
    key the message has. Paths that already name the field ``nanosec`` are returned unchanged, as are ROS 1 and JSON
    time values, which use ``nsec``.

    Args:
        resolution: Resolution to rename components in.
        sample: Decoded message to walk.
        getter: Attribute reader for ``sample``.

    Returns:
        ``(remapped, time_resolved)``: ``resolution`` with those components renamed, and whether ``sample`` showed
        which components to rename. ``time_resolved`` is ``False`` when the path past a sequence has a ``sec`` or
        ``nsec`` component and the sequence is missing, empty or not a sequence in ``sample``: no element shows
        whether to rename, so check the resolution again against a later message. It is ``True`` otherwise,
        including for a resolution with no time component.
    """
    if isinstance(resolution, _NoneResolution):
        return resolution, True
    if isinstance(resolution, _SimpleResolution):
        return _SimpleResolution(tuple(_remap_simple_path(list(resolution.path), sample, getter))), True
    return _remap_sequence(resolution, sample, getter)


def _remap_simple_path(path: list[str], sample: typing.Any, getter: AttrGetter) -> list[str]:
    current = sample
    for index, attr in enumerate(path):
        if not getter.has_attribute(current, attr):
            return path
        if index == len(path) - 1:
            return path
        value = getter.get_attribute(current, attr)
        if is_codec_time_value(value):
            for j in range(index + 1, len(path)):
                if path[j] == "nsec":
                    path[j] = "nanosec"
        elif not getter.has_sub_attributes(value):
            return path
        current = value
    return path


def _remap_sequence(
    resolution: "_SequenceResolution",
    sample: typing.Any,
    getter: AttrGetter,
) -> tuple[Resolution, bool]:
    # With no element to look at (the sequence is missing, empty or not a sequence), a sub-path that has a sec or
    # nsec component stays unresolved; any other sub-path needs no renaming.
    element = sample
    for attr in resolution.pre_path:
        if not getter.has_attribute(element, attr):
            return resolution, not _resolution_has_time(resolution.sub_resolution)
        element = getter.get_attribute(element, attr)
    if not isinstance(element, collections.abc.Sequence) or isinstance(element, (str, bytes)) or len(element) == 0:
        return resolution, not _resolution_has_time(resolution.sub_resolution)
    sub_remapped, sub_resolved = remap_time_fields(resolution.sub_resolution, element[0], getter)
    return _SequenceResolution(resolution.pre_path, sub_remapped), sub_resolved


def _resolution_has_time(resolution: Resolution) -> bool:
    if isinstance(resolution, _SimpleResolution):
        return any(component in ("sec", "nsec") for component in resolution.path)
    if isinstance(resolution, _SequenceResolution):
        return _resolution_has_time(resolution.sub_resolution)
    return False


def _compile_accessor(
    path_components: collections.abc.Sequence[str],
    sample: typing.Any,
    getter: AttrGetter,
) -> tuple[Accessor, bool]:
    """Build the accessor for one path, and whether ``sample`` showed it in full, as ``compile_accessors`` does."""
    resolution, fully_resolved = _resolve_path(list(path_components), sample, getter)
    return build_accessor(resolution), fully_resolved


def _resolve_path(
    path: list[str],
    sample: typing.Any,
    getter: AttrGetter,
) -> tuple[Resolution, bool]:
    """Walk ``sample`` along ``path`` and return the path's resolution, and whether ``sample`` showed it in full.

    Renames ``nsec`` to ``nanosec`` in ``path`` itself, in place, past each ROS 2 time value the walk reaches. At a
    sequence, the walk continues into its first element only. At an empty sequence, it reads the rest of the path as a
    chain of dictionary keys and returns ``False``.
    """
    current = sample

    for i, attr in enumerate(path):
        is_leaf = i == len(path) - 1

        if not getter.has_attribute(current, attr):
            # A missing leaf still yields a chain-of-keys accessor, which creates the enclosing dictionaries and skips
            # the field. A missing intermediate key leaves nothing to read.
            if is_leaf:
                break
            return _NoneResolution(), True

        value = getter.get_attribute(current, attr)

        if is_leaf:
            break

        if is_codec_time_value(value):
            for j in range(i + 1, len(path)):
                if path[j] == "nsec":
                    path[j] = "nanosec"
        elif isinstance(value, collections.abc.Sequence) and not isinstance(value, (str, bytes)):
            pre_path = tuple(path[: i + 1])
            sub_path = list(path[i + 1 :])
            sub_resolution: Resolution
            if len(value) > 0:
                sub_resolution, sub_fully_resolved = _resolve_path(sub_path, value[0], getter)
            else:
                sub_resolution = _SimpleResolution(tuple(sub_path))
                sub_fully_resolved = False
            return _SequenceResolution(pre_path, sub_resolution), sub_fully_resolved

        if not getter.has_sub_attributes(value):
            return _NoneResolution(), True

        current = value

    return _SimpleResolution(tuple(path)), True


def build_accessor(
    resolution: Resolution,
) -> Accessor:
    """Build the accessor that reads the path ``resolution`` describes.

    It reads no message, so a resolution built from a schema can be turned into an accessor before any message is read.
    The accessor writes the field into the accumulator as
    :py:meth:`~roboto.formats.mcap.decoded_message.DecodedMessage.to_dict` describes.

    Args:
        resolution: Resolution to build from, such as one ``remap_time_fields`` returns.
    """
    if isinstance(resolution, _NoneResolution):
        return _noop_accessor
    if isinstance(resolution, _SimpleResolution):
        return _build_dict_simple_accessor(resolution.path)
    return _build_sequence_accessor(resolution.pre_path, resolution.sub_resolution)


def _noop_accessor(obj: typing.Any, accumulator: Accumulator) -> None:
    return None


def _build_dict_simple_accessor(path: PathInSchema) -> Accessor:
    if not path:
        return _noop_accessor

    parent_path = path[:-1]
    leaf = path[-1]

    def accessor(obj: typing.Any, accumulator: Accumulator) -> None:
        cur_obj = obj
        cur_acc = accumulator
        for component in parent_path:
            if not isinstance(cur_obj, dict) or component not in cur_obj:
                return
            sub = cur_acc.get(component)
            if sub is None:
                sub = {}
                cur_acc[component] = sub
            cur_acc = sub
            cur_obj = cur_obj[component]
        if isinstance(cur_obj, dict) and leaf in cur_obj:
            cur_acc[leaf] = cur_obj[leaf]

    return accessor


def _fill_list_into(
    accumulator: Accumulator,
    pre_parent: PathInSchema,
    list_attr: str,
    seq: typing.Iterable[typing.Any],
    sub_accessor: Accessor,
) -> None:
    """Write ``sub_accessor``'s output for each item of ``seq`` into the list at ``list_attr`` under ``pre_parent``.

    Creates the dictionaries along ``pre_parent`` as needed. A list already at ``list_attr`` is reused, so accessors
    for several fields within one sequence write into the same dictionary for each element.
    """
    cur_acc = accumulator
    for component in pre_parent:
        sub = cur_acc.get(component)
        if sub is None:
            sub = {}
            cur_acc[component] = sub
        cur_acc = sub
    existing = cur_acc.get(list_attr)
    list_accum = existing if isinstance(existing, list) else defaultlist[dict](factory=dict)
    for idx, item in enumerate(seq):
        sub_accessor(item, list_accum[idx])
    cur_acc[list_attr] = list_accum


def _build_sequence_accessor(
    pre_path: PathInSchema,
    sub_resolution: Resolution,
) -> Accessor:
    sub_accessor = build_accessor(sub_resolution)
    pre_parent = pre_path[:-1]
    list_attr = pre_path[-1]

    def dict_sequence_accessor(obj: typing.Any, accumulator: Accumulator) -> None:
        cur_obj = obj
        for component in pre_path:
            if not isinstance(cur_obj, dict) or component not in cur_obj:
                return
            cur_obj = cur_obj[component]
        if not isinstance(cur_obj, collections.abc.Sequence):
            return
        _fill_list_into(accumulator, pre_parent, list_attr, cur_obj, sub_accessor)

    return dict_sequence_accessor
