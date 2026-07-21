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
    """Whether ``val`` is a ROS2 ``Time`` / ``Duration`` decoded by the shared ``mcap_codec`` decoder.

    The codec surfaces ROS2 ``Time`` / ``Duration`` with the schema's own member names -- a plain
    ``{"sec", "nanosec"}`` dict, no marker type -- so the match is structural. Recognizing it lets
    the accessor remap a legacy ``nsec`` path component (how topics ingested before the move to
    wire-true field names recorded the sub-second leaf) onto the codec's ``nanosec`` key; without
    the remap the nanosecond component is silently dropped. ROS1's ``Time`` is natively
    ``{"sec", "nsec"}`` and JSON time values likewise use ``nsec``, so neither matches here nor
    needs a remap.
    """
    return isinstance(val, dict) and val.keys() == {"sec", "nanosec"}


class AttrGetter(abc.ABC):
    """Abstract base class for reading attributes from a decoded message.

    Decoded MCAP messages are dictionaries -- JSON and the shared ``mcap_codec``
    decoder both materialize to ``dict`` -- so :py:class:`DictAttrGetter` is the
    only implementation. The abstraction is kept so the accessor compiler takes a
    getter rather than hard-coding dict access.
    """

    @staticmethod
    @abc.abstractmethod
    def get_attribute_names(value) -> collections.abc.Sequence[str]:
        """Get the names of all attributes available in the given value.

        Args:
            value: The decoded message value to inspect.

        Returns:
            Sequence of attribute names available in the value.
        """

    @staticmethod
    @abc.abstractmethod
    def get_attribute(value, attribute) -> typing.Any:
        """Get the value of a specific attribute from the given value.

        Args:
            value: The decoded message value to access.
            attribute: Name of the attribute to retrieve.

        Returns:
            The value of the specified attribute.
        """

    @staticmethod
    @abc.abstractmethod
    def has_attribute(value, attribute: str) -> bool:
        """Check if the given value has a specific attribute.

        Args:
            value: The decoded message value to inspect.
            attribute: Name of the attribute to check for.

        Returns:
            True if the value has the specified attribute, False otherwise.
        """

    @staticmethod
    @abc.abstractmethod
    def has_sub_attributes(value) -> bool:
        """Check if the given value has nested attributes that can be accessed.

        Args:
            value: The decoded message value to inspect.

        Returns:
            True if the value has nested attributes, False otherwise.
        """


class DictAttrGetter(AttrGetter):
    """Attribute getter for decoded messages represented as dictionaries.

    Both JSON and the shared ``mcap_codec`` decoder materialize messages and their
    nested structs as plain dicts. The ``isinstance`` guards let a non-dict value --
    a JSON ``null``, scalar, or list message, or a scalar leaf reached mid-walk --
    resolve to "no such attribute" instead of raising, so the accessor compiler
    simply stops descending.
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


# Module-level singleton: the getter carries no per-instance state, so reusing one
# instance avoids allocating a fresh getter on every `to_dict()`.
_DICT_GETTER = DictAttrGetter()


def getter_for(message: typing.Any) -> AttrGetter:
    """The shared attribute getter for a decoded message.

    Every decoder materializes messages as dicts (and the dict getter resolves a
    non-dict JSON payload to no attributes), so one getter serves every message.
    """
    return _DICT_GETTER


Accumulator = dict[str, typing.Any]
"""Output dict the accessors write into. Nested keys materialize as nested dicts."""

Accessor = typing.Callable[[typing.Any, Accumulator], None]
"""Reads one path's value out of a decoded message and writes it into an :py:data:`Accumulator`.

The accessor is compiled once per ``fields`` set and reused for every subsequent
message in the same read pass. Compilation resolves time-field name remapping and
sequence boundaries against a sample message, so per-call work is just attribute
access plus accumulator writes.
"""

PathInSchema = tuple[str, ...]
"""One field's path through a message schema, e.g. ``("header", "stamp", "sec")``."""


class AccessorCache:
    """Holds compiled :py:data:`Accessor` callables for the lifetime of a single read pass.

    The cache lives on the reader rather than at module scope so that two readers
    projecting the same paths against differently-shaped messages (e.g. a time field
    present in one topic and absent in another) cannot pollute each other.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[PathInSchema, ...], list[Accessor]] = {}

    def get_or_compile(
        self,
        fields: "collections.abc.Sequence[FieldSelection]",
        sample: typing.Any,
        getter: AttrGetter,
    ) -> list[Accessor]:
        """Return accessors for these fields, compiling against ``sample`` on first call.

        Compilations that hit an empty sequence in the sample are speculative — the inner
        shape past the empty point can't be observed — and are returned without caching
        so a later message with a non-empty sequence triggers a fresh, complete compile.
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
    """Compile one accessor per field. Does not cache; callers manage caching.

    Returns a tuple of ``(accessors, fully_resolved)``. ``fully_resolved`` is ``False`` if
    any path traversed an empty sequence in ``sample`` and the inner shape past it had to
    be guessed. Callers maintaining a cross-message cache should not cache speculative
    compilations, since the next message may need a different shape.
    """
    accessors: list[Accessor] = []
    fully_resolved = True
    for field in fields:
        accessor, path_fully_resolved = _compile_accessor(field.path_in_schema, sample, getter)
        accessors.append(accessor)
        if not path_fully_resolved:
            fully_resolved = False
    return accessors, fully_resolved


# Resolution shape: the compile step walks the sample once and produces one of
# three variants. Modeled as dataclasses so mypy can narrow on isinstance checks.


@dataclasses.dataclass(frozen=True)
class _NoneResolution:
    """The path cannot be resolved on the sample; the accessor is a no-op."""


@dataclasses.dataclass(frozen=True)
class _SimpleResolution:
    """A straight attribute chain. Field names may have been remapped (ROS time fields)."""

    path: PathInSchema


@dataclasses.dataclass(frozen=True)
class _SequenceResolution:
    """The path crosses a sequence; ``sub_resolution`` is applied per element."""

    pre_path: PathInSchema
    sub_resolution: "Resolution"


Resolution = typing.Union[_NoneResolution, _SimpleResolution, _SequenceResolution]
"""A resolved accessor path: a no-op, a simple attribute chain, or a per-element sequence crossing.

Build one with :py:func:`none_resolution`, :py:func:`simple_resolution`, or
:py:func:`sequence_resolution`, then compile it with :py:func:`build_accessor`.
"""


def none_resolution() -> Resolution:
    """A resolution whose accessor is a no-op (the path is absent on a message)."""
    return _NoneResolution()


def simple_resolution(path: collections.abc.Sequence[str]) -> Resolution:
    """A resolution for a straight attribute chain (no sequence crossing)."""
    return _SimpleResolution(tuple(path))


def sequence_resolution(pre_path: collections.abc.Sequence[str], sub: Resolution) -> Resolution:
    """A resolution that crosses the sequence at ``pre_path``, applying ``sub`` per element."""
    return _SequenceResolution(tuple(pre_path), sub)


def remap_time_fields(
    resolution: Resolution,
    sample: typing.Any,
    getter: AttrGetter,
) -> tuple[Resolution, bool]:
    """Substitute the decoder's runtime time-field name into ``resolution``, observed against ``sample``.

    A legacy topic's message paths address a ROS2 time struct's sub-second leaf as ``nsec``
    (how it was recorded before the move to wire-true field names), but the shared
    ``mcap_codec`` decoder now materializes that value as a ``{"sec", "nanosec"}`` dict. This
    walks ``sample`` along the resolution and rewrites a trailing ``nsec`` past any such time
    value to ``nanosec``, so the built accessor reads the right key.

    Returns ``(remapped, time_resolved)``. ``time_resolved`` is ``False`` only when a
    time-bearing leaf sits past a sequence that is empty in ``sample`` — its element
    cannot be observed, so the runtime names stay a guess and the caller should
    re-resolve against a later, non-empty message. A resolution with no time
    component is returned unchanged with ``True``. Paths that already name the leaf
    ``nanosec`` (ROS2 wire-true), ROS1 ``nsec``, and JSON ``nsec`` values are all no-ops.
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
    # When no element can be observed (the sequence is absent or empty), a sub with
    # a time leaf stays provisional; one without is already fully resolved.
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
    """Returns ``(accessor, fully_resolved)``. ``fully_resolved`` is ``False`` when the path
    crossed an empty sequence and the inner shape past it had to be guessed."""
    resolution, fully_resolved = _resolve_path(list(path_components), sample, getter)
    return build_accessor(resolution), fully_resolved


def _resolve_path(
    path: list[str],
    sample: typing.Any,
    getter: AttrGetter,
) -> tuple[Resolution, bool]:
    """Walk ``sample`` along ``path``, classifying each step and remapping the time-field name.

    Returns ``(resolution, fully_resolved)``. ``fully_resolved`` is ``False`` if the walk
    crossed a sequence that was empty in ``sample`` and the inner shape past it had to be
    guessed as a simple chain — the caller should not cache the compiled accessor in that
    case, because a later message with a non-empty sequence may require a different shape.

    Mutates ``path`` in place to substitute the ``mcap_codec`` dict's ``nanosec`` for a legacy
    message-path name ``nsec`` when navigating through a time value. The substituted path is what
    the runtime accessor uses for attribute access.
    """
    current = sample

    for i, attr in enumerate(path):
        is_leaf = i == len(path) - 1

        if not getter.has_attribute(current, attr):
            # An intermediate is missing → the path is unresolvable. A missing leaf is
            # handled by the runtime accessor (it materializes parents and skips the write),
            # so emit a simple accessor and let it run.
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
                # Empty sequence on this sample: we can't observe the inner shape past
                # this point, so guess a simple chain. Mark the resolution as speculative
                # so the cache doesn't pin this guess against future non-empty messages.
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
    """Compile a resolution into an :py:data:`Accessor` that reads its path into an accumulator.

    The resolution carries the (possibly time-remapped) structure; this only
    selects the matching runtime walk. It does not sample, so a caller that built
    the resolution from a schema can compile without a message in hand.
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
    """Descend (creating dicts) to ``pre_parent`` under ``accumulator``, then fill
    a list-valued cell at ``list_attr`` by running ``sub_accessor`` over each item
    of ``seq``. Reuses an existing list at that key so successive paths merge into
    the same per-element dicts; otherwise backs the cell with a fresh
    index-growable list."""
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
