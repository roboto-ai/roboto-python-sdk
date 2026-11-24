# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import re
import typing

import pydantic
import pydantic_core

from ...domain.metrics.record import DayOfWeek

_STAGE_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
_CONTROL_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

_Number = typing.Union[pydantic.StrictInt, pydantic.StrictFloat]


class _DefinitionPart(pydantic.BaseModel):
    """Base class of each JSON object in a board definition.

    Keys a model does not declare are kept as given, null values included. A declared key whose value is ``None``
    is left out when the model is serialized, because the Roboto web app reads an optional key that is present
    and null as an error.
    """

    model_config = pydantic.ConfigDict(extra="allow")

    @pydantic.model_serializer(mode="wrap")
    def _omit_declared_keys_when_none(self, handler: pydantic.SerializerFunctionWrapHandler) -> dict[str, typing.Any]:
        declared_keys = type(self).model_fields
        return {key: value for key, value in handler(self).items() if not (value is None and key in declared_keys)}


class BoardPanelBinding(_DefinitionPart):
    """Result of one stage, under the name a panel draws it by.

    Building it raises ``pydantic.ValidationError`` when ``name`` or ``stage`` is empty.
    """

    name: str = pydantic.Field(min_length=1)
    """Name the panel knows the result by. A chart's specification refers to the result by this name."""

    stage: str = pydantic.Field(min_length=1)
    """ID of the stage whose result the panel draws, its ``BoardStage.id``."""


class BoardPanel(_DefinitionPart):
    """A panel: a chart, a table or a map on the board's canvas.

    Only the keys every panel carries are checked. Everything else a panel holds, such as its ``title``, its
    ``placement`` on the canvas and a chart's ``spec``, is kept as given and is not checked. Building it raises
    ``pydantic.ValidationError`` when ``bindings``, ``id`` or ``kind`` is empty.
    """

    bindings: list[BoardPanelBinding] = pydantic.Field(min_length=1)
    """Stage results the panel draws, at least one."""

    id: str = pydantic.Field(min_length=1)
    """ID that identifies the panel within the board."""

    kind: str = pydantic.Field(min_length=1)
    """Kind of panel, such as ``chart``, ``table`` or ``map``."""


class BoardStageBody(_DefinitionPart):
    """Body of a stage, which says what the stage does, for a kind of stage this module has no model of.

    Each kind of stage has its own keys, which are kept as given and are not checked. A ``value-control``,
    ``field-control`` or ``control-filter`` body is read as ``BoardValueControlBody``, ``BoardFieldControlBody`` or
    ``BoardControlFilterBody`` instead. Building it raises ``pydantic.ValidationError`` when ``kind`` is empty.
    """

    kind: str = pydantic.Field(min_length=1)
    """Kind of stage, such as ``entity.query`` or ``sql``."""


class BoardControlOption(_DefinitionPart):
    """Choice a value control lists, with the label the control shows for it."""

    label: str
    """Text the control shows for the choice."""

    value: dict[str, typing.Any]
    """Value of the choice as a tagged JSON object, such as ``{"type": "string", "value": "north"}``."""


class BoardStaticControlDomain(_DefinitionPart):
    """Choices of a value control, listed in the definition.

    Building it raises ``pydantic.ValidationError`` when ``kind`` is not ``static``.
    """

    kind: typing.Literal["static"]
    """Kind of source, always ``static``: the choices are listed in ``options``."""

    options: list[BoardControlOption]
    """Choices the control lists, in order."""


class BoardColumnControlDomain(_DefinitionPart):
    """Choices of a value control, taken from the distinct values of a column in a stage's result.

    The control names the stage that holds the column as its one input. Building it raises
    ``pydantic.ValidationError`` when ``kind`` is not ``column`` or ``column`` is empty.
    """

    kind: typing.Literal["column"]
    """Kind of source, always ``column``."""

    column: str = pydantic.Field(min_length=1)
    """Column of the input stage's result whose distinct values the control lists."""


class BoardEntityFieldControlDomain(_DefinitionPart):
    """Choices of a value control, taken from the values a field holds on one kind of resource.

    Building it raises ``pydantic.ValidationError`` when ``kind`` is not ``entity-field``, or ``field`` or ``target``
    is empty.
    """

    kind: typing.Literal["entity-field"]
    """Kind of source, always ``entity-field``."""

    field: str = pydantic.Field(min_length=1)
    """Field whose values the control lists, such as ``name``, or ``custom.<field_name>`` for a custom field."""

    target: str = pydantic.Field(min_length=1)
    """Kind of resource that holds the field, such as ``sessions`` or ``devices``."""


BoardValueControlDomain = typing.Annotated[
    typing.Union[BoardStaticControlDomain, BoardColumnControlDomain, BoardEntityFieldControlDomain],
    pydantic.Field(discriminator="kind"),
]
"""Source of a value control's choices, chosen by ``kind``.

One of ``BoardStaticControlDomain``, ``BoardColumnControlDomain`` or ``BoardEntityFieldControlDomain``."""


class BoardValueControlBody(_DefinitionPart):
    """Body of a value control: a control above the canvas in which a viewer chooses one or several values.

    The stage's result is the chosen values. A ``control-filter`` stage that reads it keeps the rows of its data stage
    that match the choice, and SQL text, stage expressions, chart specifications and panel titles read the choice as
    ``$name``, where ``name`` is the stage's ``BoardStage.name``. The stage reads no input, except the one stage whose
    column a ``BoardColumnControlDomain`` lists. Building it raises ``pydantic.ValidationError`` when ``kind`` is not
    ``value-control``, when ``default`` is a list and ``multi`` is not true, or when ``default`` is one value and
    ``multi`` is true.
    """

    kind: typing.Literal["value-control"]
    """Kind of stage, always ``value-control``."""

    default: typing.Union[dict[str, typing.Any], list[dict[str, typing.Any]], None] = None
    """Value the control holds at first and after a reset: one tagged JSON object, or a list when ``multi`` is true.

    The control holds it when the board opens and the board's URL has no ``control.<name>`` key for the control, and
    after the control is reset to its default from the control bar or by the ``reset`` operation of a ``control``
    interaction. ``None`` sets no default."""

    domain: typing.Optional[BoardValueControlDomain] = None
    """Source of the control's choices. ``None`` lets the viewer type the value."""

    label: typing.Optional[str] = None
    """Caption of the control.

    When ``None`` or blank, the caption is the display name of the field the control takes its choices from (a custom
    field's display name, a catalog field's display name such as "Device ID" for ``device_id``, or a metadata path as
    written), or else the stage's ``BoardStage.name``."""

    multi: typing.Optional[bool] = None
    """Whether the viewer may choose several values. ``None`` means false."""

    required: typing.Optional[bool] = None
    """Whether the stages and panels that read the control wait for a value.

    ``None`` means false, and a control that is not required and has no value filters nothing."""

    valueType: dict[str, typing.Any]
    """Type of the values the control holds, as a JSON object with a ``type``, such as ``{"type": "string"}``."""

    @pydantic.model_validator(mode="after")
    def validate_default_matches_multi(self) -> "BoardValueControlBody":
        """Reject a default that is a list when the control holds one value, or one value when it holds several."""
        if self.default is not None and isinstance(self.default, list) != bool(self.multi):
            raise ValueError("A multiple-value default is a list; a single-value default is one tagged value")
        return self


class BoardTopicFieldPath(_DefinitionPart):
    """Topic field named by its path, which a field control on a topic may use for its options and its default.

    Unlike a dotted name, a path can name a field whose path component holds a dot. Building it raises
    ``pydantic.ValidationError`` when ``path`` or one of its components is empty.
    """

    path: list[typing.Annotated[str, pydantic.Field(min_length=1)]] = pydantic.Field(min_length=1)
    """Path components of the field from the message root, such as ``["linear_acceleration", "z"]``.

    A component may hold a dot, so ``["gps.fix"]`` and ``["gps", "fix"]`` are two fields."""


_FieldValue = typing.Union[typing.Annotated[str, pydantic.Field(min_length=1)], BoardTopicFieldPath]


class BoardFieldControlOption(_DefinitionPart):
    """Field a field control lists, with the label the control shows for it.

    Building it raises ``pydantic.ValidationError`` when ``value`` is an empty string.
    """

    label: str
    """Text the control shows for the field."""

    value: _FieldValue
    """Field the option offers, named in the form the control's kind of field takes.

    On a control with a ``BoardFieldControlBody.target``, its name: ``name``, or ``custom.<field_name>`` for a custom
    field. On a control with a ``BoardFieldControlBody.topic``, its path (``BoardTopicFieldPath``) or its dotted name,
    such as ``linear_acceleration.z``, which the board splits at every dot."""


class BoardFieldControlBody(_DefinitionPart):
    """Body of a field control: a control above the canvas in which a viewer picks the field a chart or query reads.

    The fields it offers belong to exactly one kind of resource (``target``) or one topic (``topic``). The stage
    reads no input. Building it raises ``pydantic.ValidationError`` when:

    - ``kind`` is not ``field-control``.
    - Both or neither of ``target`` and ``topic`` are set.
    - ``options``, ``target`` or ``topic`` is empty.
    - A control with a ``target`` names a field in ``default`` or ``options`` by a ``BoardTopicFieldPath``.
    """

    kind: typing.Literal["field-control"]
    """Kind of stage, always ``field-control``."""

    default: typing.Optional[_FieldValue] = None
    """Field the control holds at first and after a reset, in the same forms as ``BoardFieldControlOption.value``.

    The control holds it when the board opens and the board's URL carries no value for the control, and after the
    control is reset to its default from the control bar. When a topic control does not offer the path that a dotted
    default names, the control holds the one field it offers whose path, joined by dots, equals the default, if
    exactly one does."""

    label: typing.Optional[str] = None
    """Caption of the control."""

    options: typing.Optional[list[BoardFieldControlOption]] = pydantic.Field(default=None, min_length=1)
    """Fields the control lists, when it lists fewer than its kind of resource or topic has."""

    target: typing.Optional[str] = pydantic.Field(default=None, min_length=1)
    """Kind of resource whose fields the control offers, such as ``sessions``."""

    topic: typing.Optional[str] = pydantic.Field(default=None, min_length=1)
    """Name of the topic whose fields the control offers."""

    @pydantic.model_validator(mode="after")
    def validate_target_or_topic(self) -> "BoardFieldControlBody":
        """Reject a field control that declares both or neither of a target and a topic."""
        if (self.target is None) == (self.topic is None):
            raise ValueError("A field control declares exactly one of target and topic")
        return self

    @pydantic.model_validator(mode="after")
    def validate_target_fields_are_named_as_text(self) -> "BoardFieldControlBody":
        """Reject a field path as the default or an option of a control on a target, whose fields are named as text."""
        if self.target is None:
            return self
        values = [self.default, *(option.value for option in self.options or [])]
        if any(isinstance(value, BoardTopicFieldPath) for value in values):
            raise ValueError(
                'A field control on a "target" names its fields as text, such as "name" or "custom.<field_name>"; a'
                ' field path ({"path": [...]}) names only a topic field'
            )
        return self


class BoardControlFilterBody(_DefinitionPart):
    """Body of a control-filter: a stage that keeps the rows of a data stage that match a value control's choice.

    The stage's ``BoardStage.inputs`` name the data stage and then the value control. A control that is not required
    and has no value filters nothing. Building it raises ``pydantic.ValidationError`` when ``kind`` is not
    ``control-filter``, ``column`` is empty, or ``columnHolds`` is neither ``value`` nor ``entity-id``.
    """

    kind: typing.Literal["control-filter"]
    """Kind of stage, always ``control-filter``."""

    column: str = pydantic.Field(min_length=1)
    """Column of the data stage's result that the filter compares with the chosen values."""

    columnHolds: typing.Optional[typing.Literal["value", "entity-id"]] = None
    """Kind of value the column holds: ``value`` or ``entity-id``.

    ``value`` is a value of the control's type, which matches when it is a chosen value. ``entity-id`` is the ID of a
    resource of the kind the control's ``entity-field`` source names, which matches when that resource's field holds a
    chosen value. ``None`` means ``value``."""


_CONTROL_BODY_KINDS = ("value-control", "field-control")

_BODY_MODELS_BY_KIND: dict[str, type[_DefinitionPart]] = {
    "value-control": BoardValueControlBody,
    "field-control": BoardFieldControlBody,
    "control-filter": BoardControlFilterBody,
}
"""Model of each kind of stage body this module checks beyond its ``kind``."""


class BoardStage(_DefinitionPart):
    """A stage: one step that provides a board's data, or a control above the canvas.

    A stage queries Roboto, transforms other stages' results, holds the value a viewer chooses in a control, or
    filters a stage's rows by such a control. Building it raises ``pydantic.ValidationError`` when:

    - ``id`` or ``name`` does not take the form its field describes.
    - The model of the body's ``kind`` rejects ``body``.
    - A control-filter does not name exactly two ``inputs``.
    - A value control whose choices come from a column does not name exactly one input, or another control names one.
    """

    body: typing.Union[BoardValueControlBody, BoardFieldControlBody, BoardControlFilterBody, BoardStageBody]
    """Body of the stage, which says what the stage does, read as the model of its ``kind``."""

    id: str = pydantic.Field(pattern=_STAGE_IDENTIFIER_PATTERN)
    """ID of the stage, by which panels and other stages refer to it.

    ``BoardDefinition`` rejects a board in which two stages share an ID. Starts with a letter or digit, and holds only
    letters, digits, underscores and hyphens."""

    inputs: typing.Optional[list[str]] = None
    """IDs of the stages this stage reads, in order. ``None`` reads none."""

    name: str = pydantic.Field(pattern=_STAGE_IDENTIFIER_PATTERN)
    """Name the stage's result goes by, such as a table name in another stage's SQL.

    Starts with a letter or digit, and holds only letters, digits, underscores and hyphens. A control's name is also
    what a ``$name`` reference names, so it starts with a letter and holds only letters, digits and underscores."""

    @pydantic.field_validator("body", mode="before")
    @classmethod
    def read_body_as_its_kind(cls, body: typing.Any) -> typing.Any:
        """Build a body as the model of its ``kind``, so a mistake in it is reported at the key it was made in."""
        if not isinstance(body, dict):
            return body
        kind = body.get("kind")
        model = _BODY_MODELS_BY_KIND.get(kind, BoardStageBody) if isinstance(kind, str) else BoardStageBody
        return model.model_validate(body)

    @pydantic.model_validator(mode="after")
    def validate_control_name_and_inputs(self) -> "BoardStage":
        """Reject a control name a ``$name`` reference cannot hold, and wrong inputs on a control or control-filter."""
        errors: list[pydantic_core.InitErrorDetails] = []
        kind = self.body.kind
        if kind in _CONTROL_BODY_KINDS and not _CONTROL_NAME_PATTERN.match(self.name):
            errors.append(
                _stage_error(
                    ("name",),
                    self.name,
                    "control_name",
                    "A control's name starts with a letter and holds only letters, digits and underscores, "
                    "since a reference reads its value as $name",
                )
            )
        input_count = len(self.inputs or [])
        if isinstance(self.body, BoardControlFilterBody) and input_count != 2:
            errors.append(
                _stage_error(
                    ("inputs",),
                    self.inputs,
                    "control_filter_inputs",
                    "A control-filter names two inputs: the stage whose rows it filters, then the value control",
                )
            )
        reads_column = isinstance(self.body, BoardValueControlBody) and isinstance(
            self.body.domain, BoardColumnControlDomain
        )
        if kind in _CONTROL_BODY_KINDS and input_count != (1 if reads_column else 0):
            errors.append(
                _stage_error(
                    ("inputs",),
                    self.inputs,
                    "control_inputs",
                    "A control whose choices are a column's values names the one stage holding the column in its "
                    "inputs; any other control takes no input",
                )
            )
        if errors:
            raise pydantic_core.ValidationError.from_exception_data(type(self).__name__, errors)
        return self


class BoardSection(_DefinitionPart):
    """A section: a titled region of the canvas.

    A panel joins a section by naming the section in its own placement. Building it raises
    ``pydantic.ValidationError`` when ``id`` or ``title`` is empty, or a position or size is not a number.
    """

    height: _Number
    """Height of the region, in canvas units."""

    id: str = pydantic.Field(min_length=1)
    """ID that identifies the section within the board."""

    title: str = pydantic.Field(min_length=1)
    """Title shown on the region."""

    width: _Number
    """Width of the region, in canvas units."""

    x: _Number
    """Horizontal position of the region's left edge, in canvas units."""

    y: _Number
    """Vertical position of the region's top edge, in canvas units."""


class BoardSelection(_DefinitionPart):
    """A selection: a named set of values that panels publish to and filter by.

    Building it raises ``pydantic.ValidationError`` when ``name`` is empty.
    """

    keys: list[dict[str, typing.Any]]
    """Values the selection carries, each a JSON object with a ``key`` and a ``valueType``. May be empty."""

    name: str = pydantic.Field(min_length=1)
    """Name panels refer to the selection by."""


class BoardCalendar(_DefinitionPart):
    """Calendar of a board: the time zone the board reads its times in, and the day its weeks start on.

    The Roboto web app shows every time on the board in this zone, and divides time into days, weeks and other
    calendar periods in it, with weeks beginning on ``week_start``: for a chart's time units and weekly groups, for
    the rows a click on one of those periods selects, and for the periods of a metric aggregate. The bounds of a
    custom ``time_range``, each a date (``"2026-09-06"``) or a date and time written without a zone or offset
    (``"2026-09-06T14:00"``), are read in this zone too. Building it raises ``pydantic.ValidationError`` when it has
    a key other than ``time_zone`` and ``week_start``, or ``week_start`` is not a day's lowercase name, such as
    ``"monday"``.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    time_zone: str = "UTC"
    """Name of the zone in the IANA time zone database, in its letter case, such as ``"America/Los_Angeles"``.

    This model does not check the name. The Roboto web app reports the definition as invalid when the name is not in
    the database, is an offset such as ``"+05:30"``, is written in another letter case such as
    ``"america/los_angeles"``, or is ``CET``, ``EET``, ``MET`` or ``WET``, which Roboto reads as fixed offsets without
    daylight saving time when it aggregates metrics; name such a zone by area and location instead, such as
    ``"Europe/Paris"`` for ``CET``."""

    week_start: DayOfWeek = DayOfWeek.Monday
    """Day the board's weeks start on."""


class BoardDefinition(_DefinitionPart):
    """A board definition: panels arranged on a canvas, and the stages that provide their data.

    This model checks a definition's outline as it is built. Roboto refuses a definition whose top level this model
    refuses, with the entries of ``panels`` and ``stages`` set aside, and stores the panels and stages in it as given;
    the Roboto web app decides what a definition means when it opens the board. Building the model raises
    ``pydantic.ValidationError`` when any of these checks fails:

    - the top-level keys, the calendar's members, and the keys every panel, stage, section and selection carries;
    - the members of a control or control-filter stage, and how many inputs it names;
    - that no two stages share an ID;
    - that each stage a panel or another stage names is declared;
    - that a control-filter reads a data stage (a stage that is not a control), then a value control.

    It does not check what lies deeper, such as a stage's query or a chart's specification, nor whether the calendar's
    time zone is one the web app accepts, so the web app can still report a definition this model accepts, or a panel
    or stage in it, as invalid.

    At the top level and in the calendar, a key the models do not declare is refused, as the web app refuses it.
    Elsewhere below the top level, such a key is kept as given. An optional key left as ``None`` is omitted when the
    model is serialized.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    calendar: typing.Optional[BoardCalendar] = None
    """Calendar of the board: the time zone it reads its times in, and the day its weeks start on.

    ``None`` reads times in UTC and starts weeks on Monday."""

    panels: list[BoardPanel]
    """Panels on the canvas. May be empty."""

    schema_version: typing.Literal[1] = 1
    """Version of the definition's schema, always ``1``."""

    sections: typing.Optional[list[BoardSection]] = None
    """Titled regions of the canvas. ``None`` declares none."""

    selections: typing.Optional[list[BoardSelection]] = None
    """Named selections that panels publish to and filter by. ``None`` declares none."""

    stages: typing.Optional[list[BoardStage]] = None
    """Stages that provide the panels' data, and the controls above the canvas. ``None`` declares none."""

    time_range: typing.Union[str, dict[str, typing.Any]]
    """Time range the board opens with: a preset, or a JSON object describing a custom or relative range.

    A preset is a string such as ``"90d"``."""

    title: typing.Optional[str] = None
    """Title of the board. Roboto keeps the board's name equal to a title that is a non-empty string."""

    @pydantic.model_validator(mode="after")
    def validate_stage_ids_and_references(self) -> "BoardDefinition":
        """Reject a reused stage ID, a reference to an undeclared stage, and a control-filter reading the wrong stages.

        A control-filter input that names no stage, or an ID several stages share, is reported only as an undeclared
        or a reused stage ID.
        """
        stages = self.stages or []
        stage_ids = [stage.id for stage in stages]
        kinds_by_unique_id = {stage.id: stage.body.kind for stage in stages if stage_ids.count(stage.id) == 1}
        # BoardStage refuses a control-filter that does not name exactly two inputs.
        control_filter_inputs = [
            (stage_index, typing.cast(list[str], stage.inputs))
            for stage_index, stage in enumerate(stages)
            if isinstance(stage.body, BoardControlFilterBody)
        ]
        errors = (
            [
                _stage_error(
                    ("stages", stage_index, "id"),
                    stage_id,
                    "duplicate_stage_id",
                    "Another stage already has the id '{stage_id}'; give each stage a unique id",
                    {"stage_id": stage_id},
                )
                for stage_index, stage_id in enumerate(stage_ids)
                if stage_ids.index(stage_id) != stage_index
            ]
            + [
                _undeclared_stage_error(("panels", panel_index, "bindings", binding_index, "stage"), binding.stage)
                for panel_index, panel in enumerate(self.panels)
                for binding_index, binding in enumerate(panel.bindings)
                if binding.stage not in stage_ids
            ]
            + [
                _undeclared_stage_error(("stages", stage_index, "inputs", input_index), input_stage_id)
                for stage_index, stage in enumerate(stages)
                for input_index, input_stage_id in enumerate(stage.inputs or [])
                if input_stage_id not in stage_ids
            ]
            + [
                _stage_error(
                    ("stages", stage_index, "inputs", 0),
                    filtered_id,
                    "control_filter_first_input",
                    "A control-filter reads a data stage and then a value control; "
                    "its first input '{stage_id}' is a control",
                    {"stage_id": filtered_id},
                )
                for stage_index, (filtered_id, _) in control_filter_inputs
                if kinds_by_unique_id.get(filtered_id) in _CONTROL_BODY_KINDS
            ]
            + [
                _stage_error(
                    ("stages", stage_index, "inputs", 1),
                    control_id,
                    "control_filter_second_input",
                    "A control-filter reads a data stage and then a value control; "
                    "its second input '{stage_id}' is a stage of kind '{kind}'",
                    {"stage_id": control_id, "kind": kinds_by_unique_id[control_id]},
                )
                for stage_index, (_, control_id) in control_filter_inputs
                if kinds_by_unique_id.get(control_id) not in (None, "value-control")
            ]
        )
        if errors:
            raise pydantic_core.ValidationError.from_exception_data(type(self).__name__, errors)
        return self


def check_definition_top_level(definition: dict[str, typing.Any]) -> None:
    """Reject a board definition whose top level ``BoardDefinition`` refuses.

    The definition is checked as ``BoardDefinition`` checks it, except for the entries of ``panels`` and ``stages``,
    which are not checked. It is refused for an unknown top-level key, a missing ``time_range`` or ``panels``, a
    ``panels`` that is not a list, a ``stages``, ``sections`` or ``selections`` that is neither a list nor null, a
    ``title`` that is neither a string nor null, a ``time_range`` that is neither a string nor an object, a
    ``schema_version`` other than 1, a ``calendar`` that is neither an object nor null or has a member other than
    ``time_zone`` and ``week_start``, a ``week_start`` that is not a day's name, or a malformed section or selection.
    The Roboto web app reads each panel and stage on its own: it shows a panel or stage that fails beside the rest of
    the board and saves it as written, so a person can repair a board one panel or stage at a time. A mistake at the
    top level leaves the web app nothing to show.

    Raises:
        pydantic.ValidationError: ``BoardDefinition`` refuses the definition's top level.
    """
    BoardDefinition.model_validate(
        {**definition, **{key: [] for key in ("panels", "stages") if isinstance(definition.get(key), list)}}
    )


def _stage_error(
    location: tuple[typing.Union[str, int], ...],
    given: typing.Any,
    error_type: str,
    message: str,
    context: typing.Optional[dict[str, typing.Any]] = None,
) -> pydantic_core.InitErrorDetails:
    return pydantic_core.InitErrorDetails(
        type=pydantic_core.PydanticCustomError(error_type, message, context),
        loc=location,
        input=given,
    )


def _undeclared_stage_error(
    location: tuple[typing.Union[str, int], ...], stage_id: str
) -> pydantic_core.InitErrorDetails:
    return _stage_error(
        location,
        stage_id,
        "undeclared_stage",
        "No stage with the id '{stage_id}' is declared in the definition's stages",
        {"stage_id": stage_id},
    )
