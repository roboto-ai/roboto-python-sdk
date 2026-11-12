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
    """A kind of thing an action can be invoked over.

    Only kinds the platform can actually deliver. A declaration is a promise the platform keeps, so
    naming a kind nothing resolves would let an author declare it, let a form offer it, and fail at
    launch. Widening this enum later is backward compatible: a stored declaration names the members
    it named.
    """

    Dataset = "dataset"
    """The invocation's data source. Expressed on the wire as ``data_source_id`` rather than as a
    selector, unlike the three below."""

    Files = "files"
    Sessions = "sessions"
    Topics = "topics"


class EgressPosture(StrEnum):
    """Whether an invocation can reach the public internet.

    Roboto's own API, object storage, and container registry stay reachable either way.
    """

    DenyAll = "deny_all"
    """No route to the public internet."""

    Open = "open"
    """The public internet, through a NAT gateway."""


class OutputChannel(StrEnum):
    """Where an action's collected outputs can go.

    An enum rather than "uploads: yes/no", because the two destinations are different capabilities:
    writing into a dataset touches data a person owns and needs a sidecar that can upload on a
    credential user code never holds, while the invocation-scoped artifact store is available everywhere.
    """

    Dataset = "dataset"
    Artifacts = "artifacts"
    NoneCollected = "none"
    """Collects nothing. A declaration, not an absence — see :py:class:`LaunchRequirements`."""


class InputRequirement(pydantic.BaseModel):
    """What an action can be invoked over."""

    model_config = pydantic.ConfigDict(frozen=True)

    kinds: frozenset[InputKind]
    """The kinds this code can read. A launch selecting anything else is refused.

    Empty is a declaration rather than an absence: this action takes no inputs, and a launch
    supplying any is refused. "No opinion" is :py:attr:`LaunchRequirements.inputs` being unset.
    """

    required: bool = True
    """Whether a launch must supply at least one input of an accepted kind.

    Defaults true because listing what you consume implies something to consume. Meaningless
    alongside an empty ``kinds``, and that pairing is refused when the release is created.
    """

    @pydantic.model_validator(mode="after")
    def _required_needs_something_to_require(self) -> InputRequirement:
        if self.required and not self.kinds:
            raise ValueError(
                "an input requirement cannot require an input and accept no kind of input; "
                "set required=False to declare an action that takes no inputs"
            )
        return self


class LaunchRequirements(pydantic.BaseModel):
    """What an invocation of an action version needs in order to work.

    Declared by the author, enforced by the platform: a launch contradicting one of these is
    refused, at release creation and at submit alike, and a version-selection surface filters the
    choices it offers down to what will run. Correcting a declaration is an ordinary new release.

    **Every field is optional, and unset means the author said nothing** — never "off". An action
    whose author declared nothing is unprotected, which is the deliberate cost of letting a
    declaration be partial. This is the same convention ``LaunchDefaults`` uses on the compute side.

    The fields are *requirements*, not a list of substrates: each one is checked against what a
    substrate offers, and the set of substrates that can run the action falls out of the
    intersection rather than being maintained by hand.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    inputs: typing.Optional[InputRequirement] = None

    staged_inputs: typing.Optional[bool] = None
    """Whether the code needs its input files on local disk before it starts, as opposed to reading
    them through the SDK. Only file-bearing inputs are ever staged — sessions and topics are
    resolved to references and read live — so staging alongside a kind set carrying no file-bearing
    kind is refused when the release is created."""

    output: typing.Optional[OutputChannel] = None

    payload: typing.Optional[bool] = None
    """Whether the code ships per-run rather than baked into a container image."""

    egress: typing.Optional[EgressPosture] = None
    """The network access the code needs: ``open`` when it reaches the public internet, ``deny_all``
    when it must not. An invocation with the other posture is refused, and so is an invocation sent to a substrate
    that cannot provide this one on this deployment."""

    requires_gpu: bool = False
    """Whether the code needs a GPU.

    A plain boolean rather than the tri-state the fields above use, because here unspecified and
    false say the same thing: "I did not say I need a GPU" and "I do not need one" are one claim.
    """
