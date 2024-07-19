# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import collections.abc
import enum
import json
import shlex
import typing

from ...domain import actions
from ...sentinels import NotSetType, null
from ..command import KeyValuePairsAction
from ..validation import (
    pydantic_validation_handler,
)


class ActionReferenceParser(argparse.Action):
    """Parse an action reference string into its org (if given) and action name components."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: typing.Union[str, collections.abc.Sequence[str], None],
        option_string: typing.Optional[str] = None,
    ):
        if not isinstance(values, str):
            raise ValueError("ActionReference must be a string")

        org_name_parts = values.split("/", maxsplit=1)
        name_part = org_name_parts[-1]
        name_digest_parts = name_part.split("@", maxsplit=1)

        parse_result = dict()

        if len(org_name_parts) == 2:
            # Org is explicit: Action belongs to the org specified in the reference
            # Example: "some-org/an-action"
            action_owner = org_name_parts[0]
            parse_result["owner"] = action_owner

        if len(name_digest_parts) == 2:
            action_name, action_digest = name_digest_parts
            parse_result["name"] = action_name
            parse_result["digest"] = action_digest
        elif len(name_digest_parts) == 1:
            action_name = name_digest_parts[0]
            parse_result["name"] = action_name

        setattr(
            namespace, self.dest, actions.ActionReference.model_validate(parse_result)
        )


def add_action_reference_arg(
    parser: argparse.ArgumentParser,
    positional: bool = True,
    required: bool = True,
    arg_help: str = "Partially or fully qualified reference to Action on which to operate.",
    arg_name="action",
) -> None:
    arg = arg_name if positional else f"--{arg_name}"
    kwargs: dict[str, typing.Any] = {
        "metavar": "<action_name> | <action_name>@<digest> | <org>/<action_name> | <org>/<action_name>@<digest>",  # noqa: E501
        "action": ActionReferenceParser,
        "help": arg_help,
    }
    if not positional and required:
        kwargs["required"] = True

    parser.add_argument(
        arg,
        **kwargs,
    )


class ActionParameterArg(argparse.Action):
    """Parse an action parameter string an ActionParameter value object."""

    METAVAR: typing.ClassVar[str] = (
        "'name=<name>|required=<true|false>|default=<value>|description=<description>'"  # noqa: E501
    )

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: typing.Union[str, collections.abc.Sequence[str], None],
        option_string: typing.Optional[str] = None,
    ):
        if not values:
            return

        parameters = []
        for parameter_str in values:
            parts = parameter_str.split("|")
            parse_result = {}
            for part in parts:
                trimmed = part.strip()
                if not trimmed:
                    continue

                parts = trimmed.split("=", maxsplit=1)
                if not len(parts) == 2:
                    raise argparse.ArgumentError(
                        self,
                        f"Unable to parse action parameter '{parameter_str}'. "
                        f"Parameter '{part}' is not parsable as a <key>=<value> pair.",
                    )

                key = parts[0].strip()
                value = parts[1].strip()
                parsed_value: typing.Any = value
                if key == "required":
                    parsed_value = parsed_value.lower() == "true"
                else:
                    try:
                        parsed_value = json.loads(parsed_value)
                    except Exception:
                        pass
                parse_result[key] = parsed_value

            with pydantic_validation_handler("Action parameter"):
                action_parameter = actions.ActionParameter.model_validate(parse_result)

            parameters.append(action_parameter)

        existing_parameters = getattr(namespace, self.dest, None)
        if not existing_parameters:
            existing_parameters = []
        setattr(namespace, self.dest, [*existing_parameters, *parameters])


class ActionTimeoutArg(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: typing.Union[str, collections.abc.Sequence[str], NotSetType, None],
        option_string: typing.Optional[str] = None,
    ):
        if values is None or isinstance(values, NotSetType):
            setattr(namespace, self.dest, values)
            return

        if not isinstance(values, str):
            raise argparse.ArgumentError(self, "Can only specify one timeout value.")

        timeout: typing.Optional[int] = None
        try:
            timeout = int(values)
        except ValueError:
            raise argparse.ArgumentError(
                self,
                f"Invalid value for timeout: '{values}'. Timeout must be parseable as an integer.",
            )
        if timeout <= 0:
            raise argparse.ArgumentError(
                self,
                f"Invalid value for timeout: {timeout}. Timeout must be greater than 0.",
            )

        setattr(namespace, self.dest, timeout)


class DockerInstructionForm(enum.Enum):
    """The form of a CMD instruction."""

    Exec = "exec"
    Shell = "shell"


def parse_compute_requirements(
    args: argparse.Namespace,
    defaults: typing.Optional[actions.ComputeRequirements] = None,
) -> typing.Optional[actions.ComputeRequirements]:
    if args.vcpu is None and args.memory is None and args.storage is None:
        return None

    defaults = defaults if defaults else actions.ComputeRequirements()

    with pydantic_validation_handler("compute requirements"):
        kwargs = {
            key: value
            for key, value in [
                ("vCPU", args.vcpu if args.vcpu else defaults.vCPU),
                ("memory", args.memory if args.memory else defaults.memory),
                ("storage", args.storage if args.storage else defaults.storage),
            ]
            if value is not None
        }
        if not kwargs:
            return None
        return actions.ComputeRequirements.model_validate(kwargs)


def add_compute_requirements_args(parser: argparse.ArgumentParser) -> None:
    resource_requirements_group = parser.add_argument_group(
        "Resource requirements",
        "Specify required compute resources.",
    )
    resource_requirements_group.add_argument(
        "--vcpu",
        required=False,
        type=int,
        choices=[256, 512, 1024, 2048, 4096, 8192, 16384],
        help="CPU units to dedicate to action invocation. Defaults to 512 (0.5vCPU).",
    )

    resource_requirements_group.add_argument(
        "--memory",
        required=False,
        type=int,
        help=(
            "Memory (in MiB) to dedicate to action invocation. Defaults to 1024 (1 GiB). "
            "Supported values range from 512 (0.5 GiB) to 122880 (120 GiB). "
            "Supported values are tied to selected vCPU resources. See documentation for more information."
        ),
    )

    resource_requirements_group.add_argument(
        "--storage",
        required=False,
        type=int,
        help=(
            "Ephemeral storage (in GiB) to dedicate to action invocation. Defaults to 21 GiB. "
            "Supported values range from 21 to 200, inclusive."
        ),
    )

    # Placeholder
    resource_requirements_group.add_argument(
        "--gpu",
        required=False,
        default=False,
        action="store_true",
        help=(
            "This is a placeholder; it currently does nothing. "
            "In the future, setting this option will invoke the action in a GPU-enabled compute environment."
        ),
    )


def parse_container_overrides(
    args: argparse.Namespace,
    defaults: typing.Optional[actions.ContainerParameters] = None,
) -> typing.Optional[actions.ContainerParameters]:
    if (
        args.entry_point is None
        and args.command is None
        and args.workdir is None
        and args.env is None
    ):
        return None

    defaults = defaults if defaults else actions.ContainerParameters()

    with pydantic_validation_handler("container parameters"):
        entry_point: typing.Union[list[str], object] = defaults.entry_point
        if args.entry_point is null:
            entry_point = null
        elif args.entry_point is not None:
            entry_point = [args.entry_point]

        command: typing.Union[list[str], object] = defaults.command
        if args.command is null:
            command = null
        elif args.command is not None:
            command_form = DockerInstructionForm(args.command_form)
            command = []
            if command_form == DockerInstructionForm.Exec and len(args.command):
                lexxer = shlex.shlex(args.command, posix=True, punctuation_chars=True)
                lexxer.whitespace_split = True
                command = list(lexxer)
            else:
                command = [args.command]

        kwargs = {
            key: value
            for key, value in [
                ("entry_point", entry_point),
                ("command", command),
                ("workdir", args.workdir if args.workdir else defaults.workdir),
                ("env_vars", args.env if args.env else defaults.env_vars),
            ]
            if value is not None
        }
        if not kwargs:
            return None
        return actions.ContainerParameters.model_validate(
            {key: value if value is not null else None for key, value in kwargs.items()}
        )


def add_container_parameters_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group(
        "Container parameters",
        "Specify parameters to pass to the action's Docker container at runtime.",
    )

    group.add_argument(
        "--entrypoint",
        required=False,
        type=lambda s: s if s != "null" else null,
        dest="entry_point",
        help=(
            "Container ENTRYPOINT override."
            ' Supports passing empty string ("") as an override, which unsets the ENTRYPOINT specified in the docker image.'  # noqa: E501
            " If updating or invoking action which has existing ENTRYPOINT override, specify ``null`` to remove the override."  # noqa: E501
            " Refer to docker documentation for more: "
            "https://docs.docker.com/engine/reference/builder/#entrypoint"
            " and https://docs.docker.com/engine/reference/run/#entrypoint-default-command-to-execute-at-runtime"
        ),
    )

    group.add_argument(
        "--command",
        required=False,
        type=lambda s: s if s != "null" else null,
        dest="command",
        help=(
            "Container CMD override."
            " If updating or invoking action which has existing CMD override, specify ``null`` to remove the override."
            " Refer to docker documentation for more: "
            "https://docs.docker.com/engine/reference/builder/#cmd and"
            " https://docs.docker.com/engine/reference/run/#cmd-default-command-or-options"
        ),
    )

    group.add_argument(
        "--command-form",
        required=False,
        choices=[form.value for form in DockerInstructionForm],
        default=DockerInstructionForm.Exec.value,
        dest="command_form",
        help=(
            "In ``exec`` form, the provided ``--command`` str is split into a list of strings"
            ' (e.g., ``--command "-c \'print(123)\'"`` is parsed as ``["-c", "print(123)"]``).'
            " In ``shell`` form, the provided ``--command`` str is not split"
            " (e.g., ``--command \"python -c 'print(123)'\"`` is parsed as ``[\"python -c 'print(123)'\"]``)."
        ),
    )

    group.add_argument(
        "--workdir",
        required=False,
        type=lambda s: s if s != "null" else null,
        dest="workdir",
        help=(
            "If updating, specify ``null`` to clear existing workdir."
            " Refer to docker documentation for more: https://docs.docker.com/engine/reference/run/#workdir"
        ),
    )

    group.add_argument(
        "--env",
        required=False,
        metavar="KEY=VALUE",
        nargs="*",
        action=KeyValuePairsAction,
        help=(
            "Zero or more ``<key>=<value>`` formatted pairs to set as container ENV vars. "
            "Do not use ENV vars for secrets (such as API keys). "
            "See documentation: https://docs.docker.com/engine/reference/run/#env-environment-variables"
        ),
    )
