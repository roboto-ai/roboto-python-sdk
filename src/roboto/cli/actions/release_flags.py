# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import typing

from ...domain import actions
from ...domain.actions.action_config import CPU_UNITS_PER_VCPU
from ..common_args import parse_container_overrides
from ..terminal import print_error_and_exit
from ..validation import pydantic_validation_handler


def overlay_release_flags(args: argparse.Namespace, base: dict[str, typing.Any]) -> actions.CreateReleaseRequest:
    """Return the release ``base`` describes with the command line's release flags laid over it.

    ``base`` holds :py:class:`~roboto.domain.actions.CreateReleaseRequest` fields, from a config file, the
    action's latest release, or the defaults of a new action. A flag replaces what ``base`` says; container
    flags are merged into its Fargate configuration. Exits with an error, before anything is sent, for a
    release that runs nothing or that sets container flags on a substrate that runs no container.

    Args:
        args: The parsed command line of ``roboto actions create`` or ``roboto actions update``.
        base: The release before the flags.
    """
    release = dict(base)

    base_substrate = actions.Substrate(release["substrate"])
    substrate = actions.Substrate(args.substrate) if args.substrate is not None else base_substrate
    if substrate is not base_substrate:
        release["substrate_config"] = None
    release["substrate"] = substrate

    if args.image is not None or args.payload is not None:
        release["executable"] = {
            "image_ref": args.image,
            "payload": args.payload.read_bytes() if args.payload is not None else None,
        }
    if not release.get("executable"):
        print_error_and_exit("A release must run something: pass --image or --payload.")

    if args.timeout is not None:
        release["timeout_s_default"] = args.timeout * 60

    shape = dict(release.get("shape") or {})
    if args.vcpu is not None:
        shape["vcpu"] = args.vcpu / CPU_UNITS_PER_VCPU
    if args.memory is not None:
        shape["memory_mib"] = args.memory
    if args.storage is not None:
        shape["storage_gib"] = args.storage
    release["shape"] = shape

    replaced = {parameter.name for parameter in getattr(args, "parameter", None) or []}
    replaced |= {parameter.name for parameter in getattr(args, "put_parameters", None) or []}
    replaced |= set(getattr(args, "remove_parameters", None) or [])
    release["parameters"] = [
        *(
            parameter
            for parameter in (actions.ActionParameter.model_validate(p) for p in release.get("parameters") or [])
            if parameter.name not in replaced
        ),
        *(getattr(args, "parameter", None) or []),
        *(getattr(args, "put_parameters", None) or []),
    ]

    if substrate is actions.Substrate.Fargate:
        current = actions.ContainerParameters.model_validate(release.get("substrate_config") or {})
        container = parse_container_overrides(args, defaults=current) or current
        release["substrate_config"] = actions.FargateSubstrateConfig(
            entry_point=container.entry_point,
            command=container.command,
            workdir=container.workdir,
            env_vars=container.env_vars or {},
        )
    elif parse_container_overrides(args) is None:
        release["substrate_config"] = release.get("substrate_config") or None
    else:
        print_error_and_exit(
            f"--entrypoint, --command, --workdir and --env configure a container, which the '{substrate}' "
            "substrate does not run."
        )

    if args.grant:
        release["grants"] = args.grant
    if args.egress is not None:
        release["egress"] = args.egress
    if args.requires_downloaded_inputs is not None:
        release["requires_downloaded_inputs"] = args.requires_downloaded_inputs == "true"
    if args.release_version is not None:
        release["version"] = args.release_version

    with pydantic_validation_handler("Action release"):
        return actions.CreateReleaseRequest.model_validate(release)
