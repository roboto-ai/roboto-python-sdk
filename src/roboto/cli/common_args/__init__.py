# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Command-line options that several ``roboto`` commands share, such as an action reference and the organization.

Each ``add_*`` function adds options to an ``argparse.ArgumentParser``. Some options convert their value while the
command line is parsed, such as an action reference into :py:class:`~roboto.domain.actions.ActionReference`; for the
others, ``parse_compute_requirements`` and ``parse_container_overrides`` build
:py:class:`~roboto.domain.actions.ComputeRequirements` and :py:class:`~roboto.domain.actions.ContainerParameters`
from the parsed values. ``add_org_arg`` adds ``--org``, which defaults to ``ROBOTO_ORG_ID`` and then, once the
``roboto`` program calls ``apply_profile_org_default`` after parsing, to the config file profile's ``org_id``.
``get_defaulted_org_id`` returns that organization, or the caller's only organization when none is set, and raises
:py:class:`~roboto.exceptions.RobotoNoOrgProvidedException` when the caller belongs to none or to several.
"""

from .actions import (
    ActionParameterArg,
    ActionReferenceParser,
    ActionTimeoutArg,
    add_action_reference_arg,
    add_compute_requirements_args,
    add_container_parameters_args,
    parse_action_reference_string,
    parse_compute_requirements,
    parse_container_overrides,
)
from .orgs import (
    add_org_arg,
    apply_profile_org_default,
    get_defaulted_org_id,
)

__all__ = (
    "ActionParameterArg",
    "ActionReferenceParser",
    "ActionTimeoutArg",
    "add_action_reference_arg",
    "add_compute_requirements_args",
    "add_container_parameters_args",
    "add_org_arg",
    "apply_profile_org_default",
    "get_defaulted_org_id",
    "parse_action_reference_string",
    "parse_compute_requirements",
    "parse_container_overrides",
)
