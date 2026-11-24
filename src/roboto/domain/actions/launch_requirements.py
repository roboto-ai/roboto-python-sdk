# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import typing

import pydantic

from ...compat import StrEnum


class InputKind(StrEnum):
    """Kind of input an action can be invoked over."""

    Dataset = "dataset"
    """Datasets (:py:class:`~roboto.domain.datasets.Dataset`).

    An invocation names a dataset as its data source, by ``data_source_id``; it chooses files, sessions and topics
    with selectors instead.
    """

    Files = "files"
    """Files (:py:class:`~roboto.domain.files.File`)."""

    Sessions = "sessions"
    """Sessions (:py:class:`~roboto.experimental.sessions.Session`)."""

    Topics = "topics"
    """Topics (:py:class:`~roboto.domain.topics.Topic`)."""


class EgressPosture(StrEnum):
    """Whether an invocation can reach the public internet.

    Roboto's own API, object storage, and container registry stay reachable either way.
    """

    DenyAll = "deny_all"
    """No access to the public internet."""

    Open = "open"
    """Access to the public internet."""


class OutputChannel(StrEnum):
    """Where an invocation collects its action's outputs.

    Every compute environment can collect into the invocation's artifacts; only some can upload into a dataset.
    """

    Dataset = "dataset"
    """Upload of the outputs into a dataset."""

    Artifacts = "artifacts"
    """Storage of the outputs as artifacts of the invocation."""

    NoneCollected = "none"
    """No collection of outputs."""


class InputRequirement(pydantic.BaseModel):
    """Kinds of input an action's code can read, and whether an invocation must supply one.

    Carried in ``LaunchRequirements.inputs``.

    Constructing a requirement with ``required=True`` and an empty ``kinds`` raises ``pydantic.ValidationError``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    kinds: frozenset[InputKind]
    """Kinds of input the action's code can read.

    An empty set declares that the action takes no inputs. To declare nothing about inputs, leave
    ``LaunchRequirements.inputs`` unset instead.
    """

    required: bool = True
    """Whether an invocation must supply at least one input of a kind in ``kinds``. Defaults to ``True``."""

    @pydantic.model_validator(mode="after")
    def _required_needs_something_to_require(self) -> InputRequirement:
        if self.required and not self.kinds:
            raise ValueError(
                "an input requirement cannot require an input and accept no kind of input; "
                "set required=False to declare an action that takes no inputs"
            )
        return self


class LaunchRequirements(pydantic.BaseModel):
    """Requirements that a version of an action declares its code needs for an invocation to work.

    Roboto checks every invocation against ``inputs``: one that supplies an input of a kind the version does not
    accept, or supplies none when one is required, raises ``RobotoInvalidRequestException``. Roboto checks the other
    requirements only for a version whose code is sent with each invocation or that runs on a compute environment
    other than the default. For such a version, an invocation that contradicts a declared requirement, or that runs
    on a compute environment that cannot meet one, raises ``RobotoInvalidRequestException``. Other versions run
    without those checks.

    Every field except ``requires_gpu`` defaults to ``None``, which declares nothing; it never means "off". A
    declaration that sets only some fields declares only those.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    inputs: typing.Optional[InputRequirement] = None
    """Kinds of input the code can read, and whether an invocation must supply one."""

    staged_inputs: typing.Optional[bool] = None
    """Whether the code needs its input files downloaded to local disk before it starts.

    ``True`` if it does; ``False`` if it reads them through the SDK instead. Only files are downloaded; the code reads
    sessions and topics through the SDK either way.
    """

    output: typing.Optional[OutputChannel] = None
    """Where the code's outputs must be collected."""

    payload: typing.Optional[bool] = None
    """Whether the code is sent with each invocation (``True``) or built into a container image (``False``)."""

    egress: typing.Optional[EgressPosture] = None
    """Network access the code needs.

    ``EgressPosture.Open`` when it reaches the public internet, ``EgressPosture.DenyAll`` when it must not.
    """

    requires_gpu: bool = False
    """Whether the code needs a GPU. ``False`` declares nothing, as ``None`` does for the other fields."""
