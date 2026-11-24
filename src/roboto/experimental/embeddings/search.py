# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

import pydantic

from ...http import PaginatedList
from ...query import ConditionType, QuerySpecification
from ._batching import decode_vector
from .record import EmbeddingLevel

MAX_SESSION_IDS = 1_000
"""Maximum number of session IDs ``EmbeddingRowsRequest.session_ids`` may list.

Only a request with a ``projection`` or a ``sample`` may list more than 100. A ``scope`` names any number of sessions.
"""

MAX_SAMPLE_ROWS = 20_000
"""Maximum number of rows one ``EmbeddingRowsSample`` keeps."""

MAX_COMBINED_SPACES = 12
"""Maximum number of spaces ``EmbeddingRowsProjection.combine_spaces`` or ``EmbeddingRowsDistanceTo.spaces`` lists."""

MAX_SEED_ROWS = 1_000
"""Maximum number of rows one ``EmbeddingRowsDistanceTo.row_keys`` seed names."""


class EmbeddingRowsRowFilter(pydantic.BaseModel):
    """Filter that keeps only the rows whose custom field holds one of ``values``.

    Carried in ``EmbeddingRowsProjection.rows_where``. Building it raises ``pydantic.ValidationError`` for an empty
    ``field`` or ``values``.
    """

    field: str = pydantic.Field(min_length=1)
    """Custom field to test, as ``custom.<name>``.

    A string, enum or boolean custom field of the event at level ``event``, or of the session at level ``session``."""

    values: list[str] = pydantic.Field(min_length=1)
    """Values to keep, as text; a boolean is ``true`` or ``false``."""


class EmbeddingRowsCombinedSpace(pydantic.BaseModel):
    """Space that a projection or a distance combines, with the weight it counts for.

    Carried in ``EmbeddingRowsProjection.combine_spaces`` and ``EmbeddingRowsDistanceTo.spaces``. Building it raises
    ``pydantic.ValidationError`` for an empty ``space_id`` or a ``weight`` that is infinite or NaN.
    """

    space_id: str = pydantic.Field(min_length=1)
    """ID of the space, as ``EmbeddingSpaceRecord.space_id`` describes."""

    weight: float = pydantic.Field(allow_inf_nan=False)
    """Weight of the space, zero or more. A space of weight zero is not read."""


class EmbeddingRowsProjection(pydantic.BaseModel):
    """2-D projection of the rows' vectors onto x and y, fitted to every row the request reads.

    Carried in ``EmbeddingRowsRequest.projection``. Building it raises ``pydantic.ValidationError`` for a ``method``
    other than ``discriminant`` or ``pca``, or an empty ``separate_by``.
    """

    method: typing.Literal["discriminant", "pca"]
    """Method that fits the axes:

    - ``discriminant``: Fisher's linear discriminant, the axes along which the values of ``separate_by`` lie furthest
      apart.
    - ``pca``: the two directions the rows spread along most. It takes no ``separate_by``.
    """

    separate_by: typing.Optional[str] = pydantic.Field(default=None, min_length=1)
    """Custom field whose values are the classes the fit sets apart, as ``custom.<name>``.

    A string, enum or boolean custom field of the event at level ``event``, or of the session at level ``session``.

    Rows with no value are placed but take no part in the fit. Required by ``discriminant``; ``pca`` refuses it.
    """

    rows_where: typing.Optional[EmbeddingRowsRowFilter] = None
    """Filter that keeps only some rows, both in the fit and in the result, or ``None`` to keep every row."""

    combine_spaces: typing.Optional[list[EmbeddingRowsCombinedSpace]] = None
    """Spaces the fit combines, or ``None`` for the request's space alone at weight 1.

    ``None`` fits exactly as a list of that one space at weight 1 does. A list must:

    - include the request's own space;
    - name each space at most once, and at most 12 in all (``MAX_COMBINED_SPACES``);
    - name only spaces that are not maps and that hold the request's level;
    - give at least one space a weight above zero.

    The fit reads each space of weight above zero, keeps the spans all of them hold, and places each span by the
    concatenation of its spaces' unit-length vectors, each scaled by the square root of its weight.
    """


EmbeddingNormalize: typing.TypeAlias = typing.Literal["fleet", "session"]
"""How a search centers vectors before comparing them.

``session`` subtracts each session's own mean vector first, and ``fleet`` uses the vectors as stored."""


class EmbeddingRowsDistanceTo(pydantic.BaseModel):
    """Seed that Roboto measures each returned row's distance to, so the rows need carry no vector.

    Carried in ``EmbeddingRowsRequest.distance_to``. Exactly one of ``row_key``, ``row_keys``, ``event_id`` and
    ``session_id`` names the seed. The distance is measured in one space (``space_id``), or is the weighted mean of the
    distances in several (``spaces``). Building it raises ``pydantic.ValidationError`` when:

    - it names no seed, or more than one;
    - it sets both ``space_id`` and ``spaces``;
    - ``row_keys`` is empty or names more than 1,000 rows (``MAX_SEED_ROWS``), or ``spaces`` is empty or lists more
      than 12 spaces (``MAX_COMBINED_SPACES``).
    """

    row_key: typing.Optional[str] = None
    """One stored row, as ``session_id|start_ns|end_ns|event_id``, such as the point a viewer clicked."""

    row_keys: typing.Optional[list[str]] = pydantic.Field(default=None, min_length=1, max_length=MAX_SEED_ROWS)
    """Several stored rows, each written as ``row_key`` is, such as a selection a viewer brushed.

    In each space, the seed is the mean of the listed rows that the space holds, so every distance is to the
    selection's centroid. Keys a space does not hold are left out of its mean; at least one key must be stored.
    """

    row_level: typing.Optional[EmbeddingLevel] = None
    """Level of the ``row_key`` or ``row_keys`` rows, or ``None`` for the request's level."""

    event_id: typing.Optional[str] = None
    """ID of an event, whose rows across the sessions that embed it are pooled into the seed."""

    session_id: typing.Optional[str] = None
    """ID of a session, whose session-level row is the seed."""

    space_id: typing.Optional[str] = None
    """ID of the space to measure distances in, or ``None`` for the request's own space.

    The space must not be retired or a map, and must hold the request's level. Naming another space lets a map space's
    rows carry distances measured in the space the map was built from.
    """

    spaces: typing.Optional[list[EmbeddingRowsCombinedSpace]] = pydantic.Field(
        default=None, min_length=1, max_length=MAX_COMBINED_SPACES
    )
    """Spaces to measure in, with weights, or ``None`` to measure in one space.

    The distance is the weighted mean of the spaces' distances, ``sum(w * d) / sum(w)``, which is the distance a
    similarity search's ``cosine`` fusion ranks by. Each space is one that is not retired, is not a map, and holds the
    request's level, named once. A space of weight zero is not read, and at least one weight is above zero. A span that
    some space of weight above zero does not hold gets a ``distance`` of ``None``.
    """

    normalize: typing.Optional[EmbeddingNormalize] = None
    """How vectors are centered before measuring, or ``None`` for the default described below.

    ``session`` measures each row's session-centered vector, ``fleet`` the vector as stored.

    ``None`` uses ``session``, except ``fleet`` at level ``session`` or for a ``session_id`` seed, as
    ``EmbeddingSimilarRequest.normalize`` defaults. A ``session_id`` seed is the session's mean, which has no
    session-centered form, so ``session`` is refused for it.
    """

    @pydantic.model_validator(mode="after")
    def _one_seed(self) -> "EmbeddingRowsDistanceTo":
        named = [name for name in ("row_key", "row_keys", "event_id", "session_id") if getattr(self, name) is not None]
        if len(named) != 1:
            raise ValueError("distance_to names exactly one of row_key, row_keys, event_id and session_id")
        if self.space_id is not None and self.spaces is not None:
            raise ValueError("distance_to takes space_id or spaces, not both")
        return self


class EmbeddingRowsSample(pydantic.BaseModel):
    """Stable sample of the rows a request admits: at most ``n`` rows, the same ones on every page and every request.

    Carried in ``EmbeddingRowsRequest.sample``. Building it raises ``pydantic.ValidationError`` for an ``n`` outside 1
    to 20,000 (``MAX_SAMPLE_ROWS``) or an empty ``stratify_by``.
    """

    n: int = pydantic.Field(ge=1, le=MAX_SAMPLE_ROWS)
    """Maximum number of rows to keep, from 1 to 20,000."""

    stratify_by: typing.Optional[str] = pydantic.Field(default=None, min_length=1)
    """Column to stratify by: ``session_id``, or a label column as ``EmbeddingRowsRequest.attributes`` names them.
    ``None`` samples without strata.

    Each value of the column keeps a share of ``n`` proportional to its rows, and at least one row. When there are more
    values than ``n``, the ``n`` values with the most rows keep one row each.
    """


class EmbeddingSessionScope(pydantic.BaseModel):
    """Sessions a request reads, given as a search instead of as IDs.

    Carried in the ``scope`` of ``EmbeddingRowsRequest``, ``EmbeddingSimilarRequest`` and
    ``EmbeddingAnomaliesRequest``. Roboto runs the search in the same request, with the caller's access to each record
    it searches. Building it raises ``pydantic.ValidationError`` for a ``target`` other than ``sessions``, ``devices``
    or ``datasets``, or for a ``sessions_condition`` on a ``sessions`` scope.
    """

    target: typing.Literal["sessions", "devices", "datasets"]
    """Records that ``query`` selects: sessions, or the devices or datasets whose sessions are read."""

    query: QuerySpecification
    """Structured search of ``target``, as ``POST v1/query/submit/structured`` takes it.

    For a ``sessions`` scope it holds every condition, a time range among them; for a ``devices`` or ``datasets``
    scope, the conditions on those records.
    """

    sessions_condition: typing.Optional[ConditionType] = None
    """Condition the sessions of the matched devices or datasets must also meet, or ``None`` for none.

    A time range is one such condition. A ``sessions`` scope takes none, since its ``query`` holds every condition."""

    @pydantic.model_validator(mode="after")
    def _condition_for_owners_only(self) -> "EmbeddingSessionScope":
        if self.target == "sessions" and self.sessions_condition is not None:
            raise ValueError("a sessions scope holds every condition in its query; it takes no sessions_condition")
        return self


class EmbeddingRowsRequest(pydantic.BaseModel):
    """Request body for ``EmbeddingSpace.read_rows``.

    ``EmbeddingSpace.get_rows`` sends it too. Building it raises ``pydantic.ValidationError`` when:

    - it sets both or neither of ``session_ids`` and ``scope``;
    - ``session_ids`` lists more than 1,000 IDs (``MAX_SESSION_IDS``);
    - ``space_id`` is empty, or ``level`` is not ``window``, ``event`` or ``session``.
    """

    space_id: str = pydantic.Field(min_length=1)
    """ID of the space to read, as ``EmbeddingSpaceRecord.space_id`` describes. A map space is read like any other."""

    level: typing.Literal["window", "event", "session"]
    """Level of the rows to read."""

    session_ids: typing.Optional[list[str]] = pydantic.Field(default=None, max_length=MAX_SESSION_IDS)
    """IDs of the sessions whose rows to read: at most 100, or 1,000 with a ``projection`` or a ``sample``.

    Every one must belong to the caller's organization. An empty list reads no rows and only describes the space.
    Exactly one of ``session_ids`` and ``scope`` is set.
    """

    scope: typing.Optional[EmbeddingSessionScope] = None
    """Sessions to read, as a search Roboto runs.

    The search may name any number of sessions, read across as many pages as their rows fill. A ``sample`` that returns
    vectors reads at most 1,000."""

    where: typing.Optional[dict[str, typing.Any]] = None
    """Filter that keeps only the rows it admits, or ``None`` to keep every row.

    The filter is an object whose keys are conditions, all of which a row must meet:

    - List conditions match a row holding any of the values listed: ``session_ids``, ``event_ids`` (the events a row
      lies at least half inside, or an event row's own event), ``event_names``, ``event_tags``, ``session_tags``,
      ``device_ids`` and ``dataset_ids``.
    - Range conditions take ``{"gte": ..., "lte": ...}``, inclusive, with either bound optional: ``start_ns`` and
      ``end_ns`` (the row's own start and end, in nanoseconds since the Unix epoch), ``activity``, and
      ``session_start_ns`` (the session's first timestamp).
    - ``custom_fields`` and ``event_custom_fields`` map the name of a custom field of the session, or of the events the
      row lies inside, to a value or a list of values. The field's status must be
      :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.
    - ``and`` and ``or`` take a list of filters and ``not`` takes one filter, each as the only key of its object. They
      nest at most 4 deep, and a filter holds at most 32 conditions in all.

    For example, ``{"event_names": ["Grasp"], "session_tags": ["outdoor"]}`` keeps the rows inside a Grasp event of an
    outdoor session. A session row lies inside no event, so event conditions are refused at level ``session``.
    """

    start_ns: typing.Optional[int] = None
    """Time a kept row must end at or after, in nanoseconds since the Unix epoch, or ``None`` for no bound."""

    end_ns: typing.Optional[int] = None
    """Time a kept row must start at or before, in nanoseconds since the Unix epoch, or ``None`` for no bound."""

    include_vector: bool = False
    """Whether to return each row's vector, as base64 of its little-endian float32 values.

    A map space's rows always carry theirs, ``[x, y]``."""

    projection: typing.Optional[EmbeddingRowsProjection] = None
    """2-D projection to fit to every row the request reads, or ``None`` for none.

    Each row's returned vector is its ``[x, y]`` on the projection. Only at levels ``event`` and ``session``, and not
    of a map space. When the request reads more rows than one fit may use, the fit is computed from a stable sample of
    them, which ``EmbeddingRowsProjectionFit.fit_sampled`` reports.
    """

    distance_to: typing.Optional[EmbeddingRowsDistanceTo] = None
    """Seed to return each row's ``distance`` to, or ``None`` for no distances."""

    attributes: typing.Optional[list[str]] = None
    """Label columns to return with each row, or ``None`` for none.

    The columns are ``event_name``, ``event_ids``, ``event_names``, ``event_tags``, ``session_tags``, ``device_ids``,
    ``dataset_ids``, ``session_start_ns``, and ``custom.<field>``: a custom field of the event at level ``event``, or
    of the session otherwise, whose status is :py:attr:`~roboto.domain.custom_fields.CustomFieldStatus.Ready`.
    """

    sample: typing.Optional[EmbeddingRowsSample] = None
    """Stable sample to keep of the rows the request admits, or ``None`` to keep every row.

    The rows admitted are those the time range, ``where`` and a projection's ``rows_where`` admit. The first page reads
    every requested session to pick the sample."""

    @pydantic.model_validator(mode="after")
    def _sessions_or_scope(self) -> "EmbeddingRowsRequest":
        if (self.session_ids is None) == (self.scope is None):
            raise ValueError("name the sessions to read with exactly one of session_ids and scope")
        return self


class EmbeddingRowRecord(pydantic.BaseModel):
    """Data record of one embedded span of a session, as ``EmbeddingSpace.get_rows`` yields it.

    ``EmbeddingSpace.read_rows`` returns it in each page's ``items``.
    """

    session_id: str
    """ID of the session the span belongs to."""

    event_id: typing.Optional[str]
    """ID of the event an ``event`` row pools, or ``None`` at the other levels."""

    start_ns: int
    """Start of the span, in nanoseconds since the Unix epoch."""

    end_ns: int
    """End of the span, in nanoseconds since the Unix epoch."""

    activity: typing.Optional[float]
    """How active the span was in the request's space, as ``EmbeddingRow.activity`` describes.

    When ``EmbeddingRowsProjection.combine_spaces`` gives the request's space weight zero, the request reads none of
    that space's rows, so this is the ``activity`` of the first listed space with weight above zero.
    """

    n_samples: typing.Optional[int]
    """Number of samples the span pooled, in the same space as ``activity``."""

    vector: typing.Optional[str] = None
    """Vector of the span, as base64 of its little-endian float32 values, or ``None`` when the row carries none.

    Set when the request asked for it or the space is a map, whose vector is ``[x, y]``. With a projection, the row's
    ``[x, y]`` on it."""

    distance: typing.Optional[float] = None
    """Distance of the row to the ``distance_to`` seed, in the measured space's metric.

    ``None`` when that space holds no row for the span."""

    attributes: typing.Optional[dict[str, typing.Any]] = None
    """Value of each requested label column, by name; a column the row has no value for holds ``None`` or ``[]``."""

    def vector_values(self) -> typing.Optional[list[float]]:
        """Return the row's vector as numbers, decoded from ``vector``, or ``None`` when the row carries none."""
        return None if self.vector is None else decode_vector(self.vector)

    @pydantic.model_serializer(mode="wrap")
    def _leave_out_unrequested(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        # Leave distance and attributes out unless they were set, so a row whose request asked for neither carries
        # neither key. A distance set to None (the measured space holds no row for the span) stays as `null`.
        serialized = handler(self)
        for key in ("distance", "attributes"):
            if serialized.get(key) is None and key not in self.model_fields_set:
                serialized.pop(key, None)
        return serialized


class EmbeddingRowsSpace(pydantic.BaseModel):
    """Space a rows page was read from, so that a reader needs no listing of spaces.

    Carried in ``EmbeddingRowsPage.space``.
    """

    space_id: str
    name: str

    is_map: bool
    """Whether the space is a ``map``, whose every vector is ``[x, y]``, as ``EmbeddingSpaceKind`` describes."""

    dim: typing.Optional[int]
    """Length of the space's vectors, or ``None`` when the request read none of the space's rows.

    The request reads none when it reads no rows at all, or when its ``projection.combine_spaces`` gives the space
    weight zero."""


class EmbeddingRowsCombinedSpaceFit(pydantic.BaseModel):
    """Space that a projection or a distance combined, with its name and weight.

    Carried in ``EmbeddingRowsProjectionFit.combine_spaces`` and ``EmbeddingRowsDistance.spaces``.
    """

    space_id: str
    name: str
    weight: float


class EmbeddingRowsProjectionFit(pydantic.BaseModel):
    """Projection a rows page's vectors are on, as Roboto fitted it.

    Carried in ``EmbeddingRowsPage.projection``.
    """

    method: typing.Literal["discriminant", "pca"]
    separate_by: typing.Optional[str]
    """Custom field whose values the fit sets apart, as the request named it, or ``None`` for ``pca``."""

    classes: list[str]
    """Values of ``separate_by`` the fit sets apart, sorted: those held by two rows or more. Empty for ``pca``."""

    n_fit: int
    """Number of rows the fit was computed from.

    For ``discriminant``, the rows labelled with one of ``classes``; for ``pca``, every row placed. When
    ``fit_sampled`` is true, the sample of those rows."""

    n_rows: int
    """Number of rows placed on the projection, across every page.

    With a ``sample``, the rows the sample was drawn from."""

    fit_sampled: bool = False
    """Whether the fit was computed from a stable sample of ``n_considered`` rows instead of all of them.

    Roboto samples when fitting them all would take longer than one request may. Every row is placed on the sample's
    axes either way."""

    n_considered: typing.Optional[int] = None
    """Number of rows that could take part in the fit.

    Every row placed for ``pca``, every row of one of ``classes`` for ``discriminant``."""

    reduced_to: typing.Optional[int] = None
    """Number of dimensions the fitted vectors were first reduced to, or ``None`` when the fit used them as they are.

    The reduced vectors span the leading directions of the originals, and the axes were fitted in that span. Roboto
    reduces the vectors when they are wider than one fit decomposes in full: combined spaces of more than 1,500
    dimensions in all.
    """

    combine_spaces: typing.Optional[list[EmbeddingRowsCombinedSpaceFit]] = None
    """Spaces the fit combined, as the request's ``combine_spaces`` listed them, or ``None`` when it listed none."""

    n_unaligned: typing.Optional[int] = None
    """Number of rows left out of the fit and the result because some combined space lacks them.

    These are the rows in the time range and ``where`` that some space of weight above zero holds and another lacks.
    ``None`` when the request listed no ``combine_spaces``."""


class EmbeddingRowsCoverage(pydantic.BaseModel):
    """Which of a rows request's sessions hold the rows it reads.

    Carried in ``EmbeddingRowsPage.coverage``. A session that the session conditions of ``where`` rule out is not read,
    so it is in neither list. A page after the first, of a read without a projection, reads only the sessions from the
    one it resumes in; the first page reads every session, so its coverage is the request's.
    """

    sessions_requested: int
    """Number of distinct sessions the request names, in ``session_ids`` or through its ``scope``."""

    sessions_found: list[str]
    """IDs of the sessions read that hold rows of the space at the level, in ID order.

    With a projection that combines spaces, a session must hold rows of every space it combines."""

    sessions_missing: list[str]
    """IDs of the sessions read that hold no such rows, in ID order: the space's producer has not embedded them."""


class EmbeddingRowsDistance(pydantic.BaseModel):
    """What a rows page's ``distance`` values measure.

    Carried in ``EmbeddingRowsPage.distance_to``.
    """

    space_id: str
    """ID of the space measured in; with ``distance_to.spaces``, the first listed with weight above zero."""

    name: str
    """Human-readable name of the space ``space_id`` names."""

    spaces: typing.Optional[list[EmbeddingRowsCombinedSpaceFit]] = None
    """Every space ``distance_to.spaces`` listed, by name and weight, or ``None`` when the request listed none.

    Each row's ``distance`` is the weighted mean of its distances in these spaces."""

    normalize: EmbeddingNormalize
    """How vectors were centered before measuring, as ``EmbeddingRowsDistanceTo.normalize`` describes."""

    metric: str
    """Metric the distances are in: ``cosine`` is ``1 - cosine similarity``, from 0 to 2."""

    seed: str
    """Description of the seed."""


class EmbeddingAttributeColumn(pydantic.BaseModel):
    """Label column an answer's rows carry, with its values' type, so that an empty answer still has a schema.

    Carried in the ``attributes`` of ``EmbeddingRowsPage``, ``EmbeddingSimilarResponse`` and
    ``EmbeddingAnomaliesResponse``.
    """

    name: str
    type: typing.Literal["text", "text_list", "number", "integer", "boolean"]


class EmbeddingRowsSampleReport(pydantic.BaseModel):
    """What a sampled rows request kept.

    Carried in ``EmbeddingRowsPage.sample``.
    """

    rows_in_scope: int
    """Number of rows the request admitted before sampling, across every page."""

    rows_kept: int
    """Number of rows the sample kept."""

    stratify_by: typing.Optional[str]
    """Column the sample was stratified by, as the request named it, or ``None`` when it was not stratified."""

    strata: int
    """Number of distinct values of ``stratify_by`` among the rows in scope; 1 when the sample is not stratified."""


class EmbeddingRowsPage(PaginatedList[EmbeddingRowRecord]):
    """Response body of ``EmbeddingSpace.read_rows``: one page of rows."""

    space: EmbeddingRowsSpace
    """Space the rows were read from."""

    projection: typing.Optional[EmbeddingRowsProjectionFit] = None
    """Projection the rows' vectors are on, or ``None`` when the request asked for none."""

    coverage: typing.Optional[EmbeddingRowsCoverage] = None

    distance_to: typing.Optional[EmbeddingRowsDistance] = None
    """What each row's ``distance`` measures, or ``None`` when the request asked for no distances."""

    attributes: typing.Optional[list[EmbeddingAttributeColumn]] = None
    """Label columns each row's ``attributes`` holds, or ``None`` when the request asked for none."""

    sample: typing.Optional[EmbeddingRowsSampleReport] = None
    """What the sample kept, or ``None`` when the request asked for no sample."""


MAX_SIMILAR_K = 100
"""Maximum number of hits one similarity search returns."""

MAX_RANKED_ANOMALIES = 2_000
"""Maximum number of sessions or events one session-level or event-level anomaly search returns."""

MAX_ANOMALY_SESSIONS = 1_000
"""Maximum number of sessions one anomaly search may name in ``session_ids``."""


class EmbeddingSeed(pydantic.BaseModel):
    """What a similarity search looks for spans like.

    Carried in ``EmbeddingSimilarRequest.seed``. Exactly one of ``row_key``, ``event_id``, ``session_id`` and
    ``vector`` names the seed; ``start_ns`` and ``end_ns``, set together, narrow a ``session_id`` to a span. Building it
    raises ``pydantic.ValidationError`` when it names no seed or more than one, or sets ``start_ns`` or ``end_ns``
    without ``session_id``.
    """

    row_key: typing.Optional[str] = None
    """One stored row, as ``session_id|start_ns|end_ns|event_id``, such as the point a viewer clicked."""

    row_level: typing.Optional[EmbeddingLevel] = None
    """Level of the ``row_key`` row, or ``None`` for ``window``."""

    event_id: typing.Optional[str] = None
    session_id: typing.Optional[str] = None
    start_ns: typing.Optional[int] = None
    """Start of the span of ``session_id`` to look for, in nanoseconds since the Unix epoch."""

    end_ns: typing.Optional[int] = None
    """End of the span of ``session_id`` to look for, in nanoseconds since the Unix epoch."""

    vector: typing.Optional[list[float]] = None
    """Raw vector to look for, which needs a request that names exactly one space."""

    @pydantic.model_validator(mode="after")
    def _one_seed(self) -> "EmbeddingSeed":
        named = [name for name in ("row_key", "event_id", "session_id", "vector") if getattr(self, name) is not None]
        if len(named) != 1:
            raise ValueError("seed names exactly one of row_key, event_id, session_id and vector")
        if (self.start_ns is not None or self.end_ns is not None) and self.session_id is None:
            raise ValueError("seed.start_ns and seed.end_ns narrow a seed.session_id to a span")
        return self


class EmbeddingSimilarRequest(pydantic.BaseModel):
    """Request body for ``EmbeddingSpace.find_similar``.

    It ranks the spans most like a seed across the organization's sessions. Building it raises
    ``pydantic.ValidationError`` when:

    - ``k`` is outside 1 to 100 (``MAX_SIMILAR_K``);
    - ``idle_activity`` is negative;
    - ``level`` or ``fusion`` holds a value other than the ones listed on it.
    """

    seed: EmbeddingSeed
    spaces: typing.Union[typing.Literal["all"], list[str]] = "all"
    """IDs or names of the spaces to search, or ``all`` for every searchable space. A map space is refused."""

    weights: typing.Optional[dict[str, float]] = None
    """Fusion weight of each space, by space ID or name, or ``None`` to weigh every space 1.

    A space this leaves out weighs 1."""

    level: typing.Optional[typing.Literal["matched", "window", "event", "session"]] = None
    """What a hit is, or ``None`` to pick the level from the seed.

    ``matched`` is a run of consecutive windows whose duration matches the seed's, and the other levels are rows of
    that level. ``None`` picks:

    - ``matched`` for an ``event_id`` seed, or a ``session_id`` seed with a span;
    - the row's level for a ``row_key`` seed, except ``matched`` for an event row;
    - ``session`` for a ``session_id`` seed without a span;
    - ``window`` for a ``vector`` seed.
    """

    k: int = pydantic.Field(default=20, ge=1, le=MAX_SIMILAR_K)
    """Maximum number of hits to return, from 1 to 100."""

    where: typing.Optional[dict[str, typing.Any]] = None
    """Filter a hit must satisfy, as ``EmbeddingRowsRequest.where`` describes, or ``None`` for none."""

    scope: typing.Optional[EmbeddingSessionScope] = None
    """Sessions the hits may come from, as a search Roboto runs, or ``None`` for every session.

    A hit must lie in one of them, as if they were listed in ``where.session_ids``; both apply when both are given. At
    most 1,000 sessions."""

    normalize: typing.Optional[EmbeddingNormalize] = None
    """How vectors are centered before comparing them.

    ``session`` subtracts each session's own mean vector first, cancelling a per-session offset such as mounting or
    calibration drift, so that behavior is compared; ``fleet`` compares vectors as stored. ``None`` uses ``session``,
    except ``fleet`` for a ``vector`` seed, a whole-session seed (a ``session_id`` without ``start_ns``) or level
    ``session``. A whole-session seed is the session's mean, which has no session-centered form, so it and level
    ``session`` take only ``fleet``.
    """

    fusion: typing.Literal["cosine", "rank"] = "cosine"
    """How several spaces' distances combine into one order:

    - ``cosine``: the weighted mean of the cosine distances, which the space whose distances spread widest dominates.
    - ``rank``: the weighted mean of each space's percentile rank among this search's candidates, so that a space of
      narrow spread counts as much as the others.
    """

    idle_activity: float = pydantic.Field(default=0.0, ge=0.0)
    """``activity`` at or below which a candidate span is left out; 0 keeps every span.

    A span is left out only when it is at or below this value in every space."""

    exclude_seed_session: bool = True
    """Whether to leave out hits in the seed's own session."""

    attributes: typing.Optional[list[str]] = None
    """Label columns for each hit, as ``EmbeddingRowsRequest.attributes`` names them, or ``None`` for none.

    The columns are read at the hits' level, and a ``matched`` hit is labelled as a window."""


class EmbeddingSpaceRef(pydantic.BaseModel):
    """Space an answer used, by ID and name.

    Carried in ``EmbeddingSimilarResponse.spaces`` and ``EmbeddingAnomaliesResponse.spaces``.
    """

    space_id: str
    name: str


class EmbeddingSpaceDistance(pydantic.BaseModel):
    """Distance of a similarity hit to the seed in one space.

    Carried in ``EmbeddingSimilarHit.per_space``.
    """

    distance: float
    """Cosine distance to the seed in this space."""

    percentile: typing.Optional[float] = None
    """Percentile rank of the hit in this space among the search's candidates, under ``fusion`` ``rank``.

    ``None`` otherwise."""


class EmbeddingSimilarHit(pydantic.BaseModel):
    """Span that a similarity search found, nearest first.

    Carried in ``EmbeddingSimilarResponse.hits``.
    """

    rank: int
    """Position of the hit, 1 for the nearest."""

    row_key: str
    """Key of the hit's row, as ``session_id|start_ns|end_ns|event_id``."""

    session_id: str
    event_id: typing.Optional[str]
    """ID of the event the span lies mostly inside, or ``None`` when it lies outside every event."""

    dataset_id: typing.Optional[str]
    """ID of the dataset holding the span's data, or ``None`` when no single dataset does."""

    start_ns: int
    end_ns: int
    distance: float
    """Weighted mean of the hit's cosine distances in each space."""

    percentile: typing.Optional[float] = None
    """Fused percentile rank the hits are ordered by, under ``fusion`` ``rank``; ``None`` otherwise."""

    member_windows: typing.Optional[int] = None
    """Number of windows pooled into the run, at level ``matched``; ``None`` at the other levels."""

    per_space: dict[str, EmbeddingSpaceDistance]
    """Distance of the hit in each space, by space ID."""

    attributes: typing.Optional[dict[str, typing.Any]] = None


class EmbeddingSimilarSeed(pydantic.BaseModel):
    """Seed a similarity search ranked against, as Roboto resolved it.

    Carried in ``EmbeddingSimilarResponse.seed``.
    """

    description: str
    duration_ns: typing.Optional[int]
    windows: typing.Optional[int]
    """Number of windows each run pools, at level ``matched``; ``None`` at the other levels."""


class EmbeddingSimilarResponse(pydantic.BaseModel):
    """Response body of ``EmbeddingSpace.find_similar``."""

    level: str
    """Level of the hits, as the request named it or as Roboto picked it from the seed."""

    fusion: str
    normalize: str
    """How vectors were centered, as the request named it or as Roboto picked it.

    ``EmbeddingSimilarRequest.normalize`` describes the values and how Roboto picks one."""

    seed: EmbeddingSimilarSeed
    spaces: list[EmbeddingSpaceRef]
    """Spaces fused, by ID and name."""

    influence: dict[str, float]
    """Share of the ordering each space accounts for, by space ID."""

    hits: list[EmbeddingSimilarHit]
    coverage: dict[str, typing.Any]
    """Counts of what the search read.

    The counts are ``sessions_requested``, ``sessions_found``, ``sessions_missing`` (at most 20),
    ``candidates_considered`` (with ``candidates_considered_capped``), and the candidates dropped as incomplete, idle
    or overlapping."""

    truncated: bool
    """Whether ``k`` hits came back and more candidates existed."""

    attributes: typing.Optional[list[EmbeddingAttributeColumn]] = None
    """Label columns each hit's ``attributes`` holds, or ``None`` when the request asked for none."""

    filter_pushdown: typing.Optional[dict[str, typing.Any]] = None
    """Report on how ``where`` was applied, or ``None`` when the request gave none.

    It holds ``in_store``, the fields the filter tests written as an expression such as
    ``or(event_names,not(custom.robot))``, and ``caveats``, notes on how it was applied."""

    approximations: str
    """Note on what the answer approximates.

    Candidates come from each space's approximate nearest-neighbor index, so ``candidates_considered``, ``influence``
    and the percentiles count the retrieved candidates instead of every row ``where`` admits."""


class EmbeddingAnomaliesRequest(pydantic.BaseModel):
    """Request body for ``EmbeddingSpace.find_anomalies``.

    It scores what is unusual: the windows of each session, or sessions or events ranked against each other. Building
    it raises ``pydantic.ValidationError`` when:

    - it sets both ``session_ids`` and ``scope``;
    - ``session_ids`` lists more than 1,000 IDs (``MAX_ANOMALY_SESSIONS``);
    - ``threshold_percentile`` is outside 0 to 100, ``top_n`` is outside 1 to 2,000 (``MAX_RANKED_ANOMALIES``), or
      ``min_gap_s`` or ``idle_activity`` is negative;
    - ``level``, ``reference``, ``normalize``, ``scorer`` or ``fusion`` holds a value other than the ones listed on it.
    """

    session_ids: list[str] = pydantic.Field(default_factory=list, max_length=MAX_ANOMALY_SESSIONS)
    """IDs of sessions, whose role depends on ``level``:

    - ``window``: the sessions to score, from 1 to 100, each scored as it would be alone.
    - ``session``: the sessions to report, or none to report every one.
    - ``event``: the sessions whose events to report.

    Not with ``scope``.
    """

    scope: typing.Optional[EmbeddingSessionScope] = None
    """Sessions to score, as a search Roboto runs, or ``None`` to use ``session_ids``.

    At ``window`` they are the sessions scored, as ``session_ids`` would name them, at most 100. At ``session`` and
    ``event`` they bound the scoring as ``where.session_ids`` would, both applying when both are given, at most 1,000.
    Not with ``session_ids``.
    """

    level: EmbeddingLevel = "window"
    """What is scored: unusual time regions of each session, or sessions or events ranked against each other.

    ``window`` scores the time regions; ``session`` and ``event`` rank the sessions or the events."""

    where: typing.Optional[dict[str, typing.Any]] = None
    """Filter that limits the rows scored, as ``EmbeddingRowsRequest.where`` describes, or ``None`` for none.

    At ``event``, name the events to rank with an event condition, such as ``{"event_names": ["Grasp"]}``.
    """

    spaces: typing.Union[typing.Literal["all"], list[str]] = "all"
    """IDs or names of the spaces to score in, or ``all`` for every searchable space. A map space is refused."""

    reference: typing.Literal["fleet", "session", "cohort"] = "fleet"
    """Population rows are scored against:

    - ``fleet``: at ``window``, the space's reference sample, leaving out the session scored; at ``session``, every
      session the spaces hold; at ``event``, the matching events of other sessions.
    - ``session`` (``window`` and ``event`` only): the session's own other windows, or the matching events of the same
      session.
    - ``cohort`` (``window`` only): every other session's windows that ``where`` admits.
    """

    normalize: EmbeddingNormalize = "fleet"
    """How vectors are centered before scoring, at level ``window`` only.

    ``fleet`` scores vectors as stored, so that a drifting sensor stays visible; ``session`` subtracts each session's
    own mean vector first, leaving what is unusual within a session."""

    scorer: typing.Literal["knn", "mahalanobis"] = "knn"
    """How far a row is from the reference.

    ``knn`` is the distance to its nearest reference rows, and ``mahalanobis`` its Mahalanobis distance from the
    reference's mean."""

    fusion: typing.Literal["max", "mean"] = "max"
    """How several spaces' scores combine.

    ``max`` flags a row unusual in any one space; ``mean`` needs the spaces to agree."""

    threshold_percentile: float = pydantic.Field(default=99.0, ge=0.0, le=100.0)
    """Percentile at or above which an active window is hot, at ``window``.

    Lowering it makes more windows hot, which lengthens and merges regions."""

    top_n: int = pydantic.Field(default=10, ge=1, le=MAX_RANKED_ANOMALIES)
    """Maximum number of findings to return.

    Regions at ``window`` (at most 50), or sessions or events at the other levels (at most 2,000)."""

    min_gap_s: float = pydantic.Field(default=4.0, ge=0.0)
    """Longest gap, in seconds, between two hot windows that still merge into one region, at ``window``.

    0 lets a short quiet stretch end a region."""

    idle_activity: typing.Optional[float] = pydantic.Field(default=None, ge=0.0)
    """``activity`` at or below which a row is left out as idle.

    ``None`` uses the reference's 10th-percentile ``activity`` at ``window``, and leaves out nothing at ``session`` and
    ``event``."""

    attributes: typing.Optional[list[str]] = None
    """Label columns for each scored window or ranked row, or ``None`` for none.

    The columns are named as ``EmbeddingRowsRequest.attributes`` names them."""

    include_windows: bool = False
    """Whether, at ``window``, to give each entry of ``EmbeddingAnomaliesResponse.sessions`` its scored windows too.
    The top-level ``windows`` of a one-session request are returned either way."""

    @pydantic.model_validator(mode="after")
    def _sessions_or_scope(self) -> "EmbeddingAnomaliesRequest":
        if self.scope is not None and self.session_ids:
            raise ValueError("name the sessions to score with session_ids or scope, not both")
        return self


class EmbeddingAnomalyWindow(pydantic.BaseModel):
    """Scored window of a window-level anomaly search.

    Carried in ``EmbeddingAnomaliesResponse.windows`` and ``EmbeddingSessionAnomalies.windows``.
    """

    row_key: str
    """Key of the window's row, as ``session_id|start_ns|end_ns|event_id``."""

    start_ns: int
    end_ns: int
    score: float
    percentile: float
    """Percentile of the window, fused over the spaces: how far past normal the window sits, from 0 to 100."""

    hot: bool
    """Whether the window is ``active`` and its ``percentile`` is at or above the request's ``threshold_percentile``."""

    active: bool
    """Whether the window's ``activity`` is above the request's ``idle_activity`` in at least one space."""

    per_space: dict[str, float]
    """Percentile of the window in each space, by space ID."""

    attributes: typing.Optional[dict[str, typing.Any]] = None


class EmbeddingAnomalyRegion(pydantic.BaseModel):
    """Hot windows of one session merged into one finding.

    Carried in ``EmbeddingAnomaliesResponse.regions`` and ``EmbeddingSessionAnomalies.regions``.
    """

    start_ns: int
    end_ns: int
    duration_ns: int
    score: float
    """Highest score among the region's windows."""

    percentile: float
    """Highest percentile among the region's windows."""

    excess: float
    """Ranking key of the region: the sum over its windows of how far each percentile is above the threshold."""

    peak_space_id: str
    """ID of the space holding the highest percentile in the region's hottest window."""

    peak_at_ns: int
    """Start of the region's hottest window."""

    per_space_hot: dict[str, float]
    """Fraction of the region's windows that each space put at or above the threshold, by space ID."""


class EmbeddingRankedAnomaly(pydantic.BaseModel):
    """Session or event ranked against the others, hottest first.

    Carried in ``EmbeddingAnomaliesResponse.ranked``.
    """

    rank: int
    """Position in the ranking, 1 for the hottest."""

    row_key: str
    session_id: str
    event_id: typing.Optional[str] = None
    dataset_id: typing.Optional[str]
    start_ns: int
    end_ns: int
    score: float
    """How unusual the row is, corrected for how many windows it pooled.

    A row pooled from few windows sits further from the others through noise alone."""

    raw_score: float
    """Distance of the row from the reference by the request's ``scorer``, before that correction."""

    percentile: float
    per_space: dict[str, float]
    """Percentile of the row in each space, by space ID."""

    attributes: typing.Optional[dict[str, typing.Any]] = None


class EmbeddingSessionAnomalies(pydantic.BaseModel):
    """One session's answer in a window-level anomaly search, scored as the session would be alone.

    Carried in ``EmbeddingAnomaliesResponse.sessions``.
    """

    session_id: str
    dataset_id: typing.Optional[str] = None
    error: typing.Optional[str] = None
    """Why the session could not be scored, or ``None`` when it was scored.

    One such reason is that the session holds no window rows in the spaces. A session that could not be scored has no
    regions."""

    windows: typing.Optional[list[EmbeddingAnomalyWindow]] = None
    """Every scored window, in time order, when the request set ``include_windows``; ``None`` otherwise."""

    regions: list[EmbeddingAnomalyRegion] = pydantic.Field(default_factory=list)
    """At most ``top_n`` regions, by ``excess``."""

    reference_sources: typing.Optional[dict[str, str]] = None
    """Population each space was scored against, by space ID.

    The values are those ``EmbeddingAnomaliesResponse.reference_sources`` describes."""

    spaces_without_reference: typing.Optional[list[str]] = None
    """IDs of the spaces left out of the scoring because no population exists to score them against."""

    coverage: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Counts of what was scored for the session.

    ``EmbeddingAnomaliesResponse.coverage`` describes the counts for one session."""

    truncated: bool = False
    """Whether the session returned ``top_n`` regions, so that more may exist."""


class EmbeddingAnomaliesResponse(pydantic.BaseModel):
    """Response body of ``EmbeddingSpace.find_anomalies``."""

    level: str
    reference: str
    normalize: str
    scorer: str
    fusion: str
    spaces: list[EmbeddingSpaceRef]
    """Spaces scored, by ID and name."""

    session_id: typing.Optional[str] = None
    """ID of the session scored, at ``window`` for a one-session request."""

    dataset_id: typing.Optional[str] = None
    windows: typing.Optional[list[EmbeddingAnomalyWindow]] = None
    """Every scored window, in time order, at ``window`` for a one-session request."""

    regions: typing.Optional[list[EmbeddingAnomalyRegion]] = None
    """At most ``top_n`` regions, by ``excess``, at ``window`` for a one-session request."""

    sessions: typing.Optional[list[EmbeddingSessionAnomalies]] = None
    """Each requested session's answer, in the order requested, with ``top_n`` applying to each, at ``window``."""

    reference_sources: typing.Optional[dict[str, str]] = None
    """Population each space was scored against, by space ID, at ``window``: ``fleet``, ``cohort`` or ``session``."""

    spaces_without_reference: typing.Optional[list[str]] = None
    """IDs of the spaces left out of the scoring because no population exists to score them against."""

    ranked: typing.Optional[list[EmbeddingRankedAnomaly]] = None
    """At most ``top_n`` rows, hottest first, at ``session`` and ``event``."""

    coverage: dict[str, typing.Any]
    """Counts of what was scored:

    - At ``window`` for one session: the windows scored, idle and over the threshold.
    - At ``window`` for several sessions: ``sessions_scored`` and ``sessions_not_scored``; each session's own counts
      are in ``sessions``.
    - At ``session`` and ``event``: the rows scored, and ``sessions_missing`` (at most 20).
    """

    truncated: bool
    """Whether the answer may have left findings out.

    At ``window``, a session returned ``top_n`` regions; at ``session`` and ``event``, more rows were scored than the
    ``top_n`` returned."""

    attributes: typing.Optional[list[EmbeddingAttributeColumn]] = None
    """Label columns each scored window's or ranked row's ``attributes`` holds.

    ``None`` when the request asked for none."""

    filter_pushdown: typing.Optional[dict[str, typing.Any]] = None
    """Report on how ``where`` was applied, or ``None`` when the request gave none.

    Its fields are those ``EmbeddingSimilarResponse.filter_pushdown`` describes."""
