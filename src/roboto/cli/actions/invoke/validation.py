# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Validation utilities.

This module handles validating parameters, organizations, and other
invocation prerequisites.
"""

import typing

from ....domain import actions, orgs


def validate_parameters(
    action_params: list[actions.ActionParameter],
    provided_params: dict[str, typing.Any],
) -> None:
    """Validate that provided parameters are defined in action.

    Args:
        action_params: Parameters defined in action
        provided_params: Parameters provided by user

    Raises:
        ValueError: If unknown parameters are provided
    """
    known_params = set(param.name for param in action_params)
    provided_param_names = set(provided_params.keys())
    unknown_params = provided_param_names - known_params

    if unknown_params:
        raise ValueError(f"The following parameter(s) are not defined in action: {', '.join(sorted(unknown_params))}")


def resolve_organization(org_id: typing.Optional[str], roboto_client) -> str:
    """Resolve organization ID from arguments or user membership.

    Args:
        org_id: Optional organization ID from command-line
        roboto_client: Roboto client for API calls

    Returns:
        Resolved organization ID

    Raises:
        Exception: If org cannot be determined
    """
    if org_id is not None:
        return org_id

    member_orgs = orgs.Org.for_self(roboto_client=roboto_client)

    if not member_orgs:
        raise Exception(
            "It appears you are not a member of a Roboto organization. "
            "Please create an organization by logging into the web application "
            "(https://app.roboto.ai/) or try specifying the --org argument."
        )

    if len(member_orgs) == 1:
        return member_orgs[0].org_id

    formatted_org_list = "".join(f"  - {org.name} ({org.org_id})\n" for org in member_orgs)
    raise Exception(
        f"You belong to multiple Roboto organizations:\n{formatted_org_list}Please specify the --org argument."
    )
