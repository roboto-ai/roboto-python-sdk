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
    """One JSON object of a board definition.

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
    """One stage's result, under the name a panel draws it by."""

    name: str = pydantic.Field(min_length=1)
    """The name the panel knows the result by. A chart's specification refers to the result by this name."""

    stage: str = pydantic.Field(min_length=1)
    """The :py:attr:`~BoardStage.id` of the stage whose result the panel draws."""


class BoardPanel(_DefinitionPart):
    """A panel on the board's canvas: a chart, a table, or a map.

    Only the keys every panel carries are checked. Everything else a panel holds, such as its ``title``, its
    ``placement`` on the canvas and a chart's ``spec``, is kept as given and is not checked.
    """

    bindings: list[BoardPanelBinding] = pydantic.Field(min_length=1)
    """The stage results the panel draws. A panel has at least one."""

    id: str = pydantic.Field(min_length=1)
    """Identifies the panel within the board."""

    kind: str = pydantic.Field(min_length=1)
    """What the panel draws, for example ``chart``, ``table`` or ``map``."""


class BoardStageBody(_DefinitionPart):
    """What a stage does, for a kind of stage this module has no model of.

    Each kind of stage has its own keys, which are kept as given and are not checked. A control or a control-filter
    is read as :py:class:`BoardValueControlBody`, :py:class:`BoardFieldControlBody` or
    :py:class:`BoardControlFilterBody` instead.
    """

    kind: str = pydantic.Field(min_length=1)
    """The kind of stage, for example ``entity.query`` or ``sql``."""


class BoardControlOption(_DefinitionPart):
    """One choice a value control lists, and the label the control shows for it."""

    label: str
    """The text the control shows for the choice."""

    value: dict[str, typing.Any]
    """The value as a tagged JSON object, for example ``{"type": "string", "value": "north"}``."""


class BoardStaticControlDomain(_DefinitionPart):
    """A value control's choices listed in the definition."""

    kind: typing.Literal["static"]
    """Marks the choices as listed here."""

    options: list[BoardControlOption]
    """The choices the control lists, in order."""


class BoardColumnControlDomain(_DefinitionPart):
    """A value control's choices taken from the distinct values of a column in the result of the one stage the
    control reads."""

    kind: typing.Literal["column"]
    """Marks the choices as a column's values."""

    column: str = pydantic.Field(min_length=1)
    """The column of the input stage's result whose distinct values the control lists."""


class BoardEntityFieldControlDomain(_DefinitionPart):
    """A value control's choices taken from the values a field holds on one kind of entity."""

    kind: typing.Literal["entity-field"]
    """Marks the choices as an entity field's values."""

    field: str = pydantic.Field(min_length=1)
    """The field, for example ``name``, or ``custom.<field_name>`` for a custom field."""

    target: str = pydantic.Field(min_length=1)
    """The kind of entity, for example ``sessions`` or ``devices``."""


BoardValueControlDomain = typing.Annotated[
    typing.Union[BoardStaticControlDomain, BoardColumnControlDomain, BoardEntityFieldControlDomain],
    pydantic.Field(discriminator="kind"),
]
"""Where a value control's choices come from."""


class BoardValueControlBody(_DefinitionPart):
    """A control above the canvas in which a viewer chooses one or several values of a type.

    The stage's result is the chosen values. A ``control-filter`` stage that reads it keeps the rows of its data stage
    that match the choice, and SQL text, stage expressions, chart specifications and panel titles read the choice as
    ``$name``, where ``name`` is the stage's :py:attr:`~BoardStage.name`. The stage reads no input, except the one
    stage whose column a :py:class:`BoardColumnControlDomain` lists.
    """

    kind: typing.Literal["value-control"]
    """Marks the stage as a value control."""

    default: typing.Union[dict[str, typing.Any], list[dict[str, typing.Any]], None] = None
    """The value the control holds when the board opens and the board's URL has no ``control.<name>`` key for the
    control, and after the control is reset to its default from the control bar or by the ``reset`` operation of a
    ``control`` interaction: one tagged JSON object, or a list of them when :py:attr:`multi` is true."""

    domain: typing.Optional[BoardValueControlDomain] = None
    """Where the control's choices come from. Absent, the viewer types the value."""

    label: typing.Optional[str] = None
    """The control's caption. Absent or blank, the caption is the display name of the entity field the control takes
    its choices from (a custom field's display name, a catalog field's display name such as "Device ID" for
    ``device_id``, or a metadata path as written), or else the stage's :py:attr:`~BoardStage.name`."""

    multi: typing.Optional[bool] = None
    """Whether the viewer may choose several values. False when absent."""

    required: typing.Optional[bool] = None
    """Whether the stages and panels that read the control wait for a value. False when absent, and a control that
    is not required and has no value filters nothing."""

    valueType: dict[str, typing.Any]
    """The type of the values the control holds, as a JSON object with a ``type``, for example
    ``{"type": "string"}``."""

    @pydantic.model_validator(mode="after")
    def validate_default_matches_multi(self) -> "BoardValueControlBody":
        """Reject a default that is a list when the control holds one value, or one value when it holds several."""
        if self.default is not None and isinstance(self.default, list) != bool(self.multi):
            raise ValueError("A multiple-value default is a list; a single-value default is one tagged value")
        return self


class BoardFieldControlOption(_DefinitionPart):
    """One field a field control lists, and the label the control shows for it."""

    label: str
    """The text the control shows for the field."""

    value: str = pydantic.Field(min_length=1)
    """The field, for example ``name``, ``custom.<field_name>`` or a dotted topic field path."""


class BoardFieldControlBody(_DefinitionPart):
    """A control above the canvas in which a viewer chooses which field a chart or query reads.

    The fields it offers belong to exactly one kind of entity (:py:attr:`target`) or one topic (:py:attr:`topic`).
    The stage reads no input.
    """

    kind: typing.Literal["field-control"]
    """Marks the stage as a field control."""

    default: typing.Optional[str] = pydantic.Field(default=None, min_length=1)
    """The field the control holds when the board opens and the board's URL has no ``control.<name>`` key for the
    control, and after the control is reset to its default from the control bar."""

    label: typing.Optional[str] = None
    """The control's caption."""

    options: typing.Optional[list[BoardFieldControlOption]] = pydantic.Field(default=None, min_length=1)
    """The fields the control lists, when it lists fewer than its entity or topic has."""

    target: typing.Optional[str] = pydantic.Field(default=None, min_length=1)
    """The kind of entity whose fields the control offers, for example ``sessions``."""

    topic: typing.Optional[str] = pydantic.Field(default=None, min_length=1)
    """The name of the topic whose fields the control offers."""

    @pydantic.model_validator(mode="after")
    def validate_target_or_topic(self) -> "BoardFieldControlBody":
        """Reject a field control that declares both or neither of a target and a topic."""
        if (self.target is None) == (self.topic is None):
            raise ValueError("A field control declares exactly one of target and topic")
        return self


class BoardControlFilterBody(_DefinitionPart):
    """Keeps the rows of the stage's first input that match the values chosen in the value control it reads second.

    The stage's :py:attr:`~BoardStage.inputs` name the data stage and then the value control. A control that is not
    required and has no value filters nothing.
    """

    kind: typing.Literal["control-filter"]
    """Marks the stage as a control-filter."""

    column: str = pydantic.Field(min_length=1)
    """The column of the data stage's result that the filter compares with the chosen values."""

    columnHolds: typing.Optional[typing.Literal["value", "entity-id"]] = None
    """What the column holds: ``value``, a value of the control's type, which matches when it is a chosen value; or
    ``entity-id``, the id of an entity of the control's ``entity-field`` domain, which matches when that entity's
    field holds a chosen value. ``value`` when absent."""


_CONTROL_BODY_KINDS = ("value-control", "field-control")

_BODY_MODELS_BY_KIND: dict[str, type[_DefinitionPart]] = {
    "value-control": BoardValueControlBody,
    "field-control": BoardFieldControlBody,
    "control-filter": BoardControlFilterBody,
}
"""The model of each kind of stage body this module checks beyond its ``kind``."""


class BoardStage(_DefinitionPart):
    """One stage of the board's data: a query of the platform, a transformation of other stages' results, a control
    above the canvas whose result is the value a viewer chooses, or a filter of a stage's rows by such a control."""

    body: typing.Union[BoardValueControlBody, BoardFieldControlBody, BoardControlFilterBody, BoardStageBody]
    """What the stage does."""

    id: str = pydantic.Field(pattern=_STAGE_IDENTIFIER_PATTERN)
    """Identifies the stage within the board, so no two stages of a board share an id. Panels and other stages refer
    to the stage by it. Starts with a letter or digit, and holds only letters, digits, underscores and hyphens."""

    inputs: typing.Optional[list[str]] = None
    """The :py:attr:`id` of each stage this stage reads."""

    name: str = pydantic.Field(pattern=_STAGE_IDENTIFIER_PATTERN)
    """The name the stage's result goes by, for example as a table in another stage's SQL. Starts with a letter
    or digit, and holds only letters, digits, underscores and hyphens. A control's name is also what a ``$name``
    reference names, so it starts with a letter and holds only letters, digits and underscores."""

    @pydantic.field_validator("body", mode="before")
    @classmethod
    def read_body_as_its_kind(cls, body: typing.Any) -> typing.Any:
        """Read a body as the model of its kind, so a mistake in it is reported at the key it was made in."""
        if not isinstance(body, dict):
            return body
        kind = body.get("kind")
        model = _BODY_MODELS_BY_KIND.get(kind, BoardStageBody) if isinstance(kind, str) else BoardStageBody
        return model.model_validate(body)

    @pydantic.model_validator(mode="after")
    def validate_control_name_and_inputs(self) -> "BoardStage":
        """Reject a control name a ``$name`` reference cannot hold, and a control or control-filter with wrong inputs.

        A control reads no input, except a value control whose choices are a column's values, which reads the one
        stage holding the column. A control-filter reads a data stage and then a value control.
        """
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
    """A titled region of the canvas. A panel joins a section by naming the section in its own placement."""

    height: _Number
    """Height of the region, in canvas units."""

    id: str = pydantic.Field(min_length=1)
    """Identifies the section within the board."""

    title: str = pydantic.Field(min_length=1)
    """The title shown on the region."""

    width: _Number
    """Width of the region, in canvas units."""

    x: _Number
    """Horizontal position of the region's left edge, in canvas units."""

    y: _Number
    """Vertical position of the region's top edge, in canvas units."""


class BoardSelection(_DefinitionPart):
    """A named selection that panels publish to and filter by."""

    keys: list[dict[str, typing.Any]]
    """The values a selection carries, each a JSON object with a ``key`` and a ``valueType``. May be empty."""

    name: str = pydantic.Field(min_length=1)
    """The name panels refer to the selection by."""


class BoardCalendar(_DefinitionPart):
    """The time zone a board reads its times in, and the day its weeks start on.

    The Roboto web app shows every time on the board in this zone, and divides time into days, weeks and other
    calendar periods in it, with weeks beginning on :py:attr:`week_start`: for a chart's time units and weekly groups,
    for the rows a click on one of those periods selects, and for the periods of a metric aggregate. The bounds of a
    custom ``time_range``, each a date (``"2026-09-06"``) or a date and time written without a zone or offset
    (``"2026-09-06T14:00"``), are read in this zone too.
    """

    model_config = pydantic.ConfigDict(extra="forbid")

    time_zone: str = "UTC"
    """The zone's name in the IANA time zone database, in the database's letter case, such as
    ``"America/Los_Angeles"``. This model does not check the name. The web app reports the definition as invalid when
    the name is not in the database, is an offset such as ``"+05:30"``, is written in another letter case such as
    ``"america/los_angeles"``, or is ``CET``, ``EET``, ``MET`` or ``WET``, which Roboto reads as fixed offsets without
    daylight saving time when it aggregates metrics; name such a zone by area and location instead, such as
    ``"Europe/Paris"`` for ``CET``."""

    week_start: DayOfWeek = DayOfWeek.Monday
    """The day the board's weeks start on."""


class BoardDefinition(_DefinitionPart):
    """A board definition whose outline is checked as the model is built.

    The platform refuses a definition whose top level this model refuses, with the entries of ``panels`` and
    ``stages`` set aside, and stores the panels and stages in it as given; the web app decides what a definition means
    when it opens the board. This model checks a definition's outline:

    - the top-level keys, the calendar's members, and the keys every panel, stage, section and selection carries;
    - the members of a control or control-filter stage, and how many inputs it names;
    - that no two stages share an id;
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
    """The time zone the board reads its times in, and the day its weeks start on. Without one, the board reads its
    times in UTC and its weeks start on Monday."""

    panels: list[BoardPanel]
    """The panels on the canvas. May be empty."""

    schema_version: typing.Literal[1] = 1
    """Version of the definition's schema."""

    sections: typing.Optional[list[BoardSection]] = None
    """Titled regions of the canvas."""

    selections: typing.Optional[list[BoardSelection]] = None
    """Named selections that panels publish to and filter by."""

    stages: typing.Optional[list[BoardStage]] = None
    """The stages that provide the panels' data, and the controls above the canvas."""

    time_range: typing.Union[str, dict[str, typing.Any]]
    """The time range the board opens with: a preset such as ``"90d"``, or a JSON object describing a custom or
    relative range."""

    title: typing.Optional[str] = None
    """The board's title. The platform keeps a board's name equal to a title that is a non-empty string."""

    @pydantic.model_validator(mode="after")
    def validate_stage_ids_and_references(self) -> "BoardDefinition":
        """Reject a reused stage id, a reference to an undeclared stage, and a control-filter reading the wrong stages.

        A control-filter reads a data stage, then a value control. A control-filter input that names no stage, or an
        id several stages share, is reported only as an undeclared or a reused stage id.
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
    """Refuse a board definition whose top level :py:class:`BoardDefinition` refuses.

    The definition is checked as :py:class:`BoardDefinition` checks it, except for the entries of ``panels`` and
    ``stages``, which are not checked. It is refused for an unknown top-level key, a missing ``time_range`` or
    ``panels``, a ``panels`` that is not a list, a ``stages``, ``sections`` or ``selections`` that is neither a list
    nor null, a ``title`` that is neither a string nor null, a ``time_range`` that is neither a string nor an
    object, a ``schema_version`` other than 1, a ``calendar`` that is neither an object nor null or has a member
    other than ``time_zone`` and ``week_start``, a ``week_start`` that is not a day's name, or a malformed section
    or selection. The web app reads each panel and stage on its own: it shows a panel or stage that fails beside the
    rest of the board and saves it as written, so a person can repair a board one panel or stage at a time. A
    mistake at the top level leaves the web app nothing to show.

    Args:
        definition: The board definition as a JSON object.

    Raises:
        pydantic.ValidationError: :py:class:`BoardDefinition` refuses the definition's top level.
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
