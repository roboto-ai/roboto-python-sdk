# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import typing

from ....domain import actions, orgs


def validate_parameters(
    action_params: list[actions.ActionParameter],
    provided_params: dict[str, typing.Any],
) -> None:
    """Reject parameter values given for parameters the action does not define.

    Raises:
        ValueError: A key of ``provided_params`` names no parameter in ``action_params``. The message lists every such
            name.
    """
    known_params = set(param.name for param in action_params)
    provided_param_names = set(provided_params.keys())
    unknown_params = provided_param_names - known_params

    if unknown_params:
        raise ValueError(f"The following parameter(s) are not defined in action: {', '.join(sorted(unknown_params))}")


def resolve_organization(org_id: typing.Optional[str], roboto_client) -> str:
    """Return the ID of the organization to invoke the action in.

    Args:
        org_id: ID of the organization the user named with ``--org``. ``None`` fetches the organizations the caller
            belongs to and uses the only one.

    Raises:
        Exception: ``org_id`` is ``None`` and the caller belongs to no organization, or to more than one. The message
            for more than one lists them.
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
