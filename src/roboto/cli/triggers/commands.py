# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto triggers`` command set: subscribe to platform events or a schedule,
filter with a condition, and dispatch one or more targets."""

import argparse
import datetime
import json
import typing

import pydantic

from ...domain.platform_events import (
    DEFAULT_PLATFORM_EVENT_CATALOG,
    OncePer,
    PlatformEventType,
)
from ...domain.triggers import (
    Trigger,
    TriggerDryRunGateStatus,
    TriggerTargetSpec,
)
from ...query import (
    Condition,
    ConditionGroup,
    ConditionType,
)
from ..command import (
    JsonFileOrStrType,
    RobotoCommand,
    RobotoCommandSet,
)
from ..common_args import add_org_arg
from ..context import CLIContext

NAME_PARAM_HELP = "The unique name used to reference a trigger."


def _parse_condition(condition_json: typing.Optional[dict], parser: argparse.ArgumentParser) -> ConditionType | None:
    if condition_json is None:
        return None
    if "operator" in condition_json:
        return ConditionGroup.model_validate(condition_json)
    if "comparator" in condition_json:
        return Condition.model_validate(condition_json)
    parser.error("Provided '--condition-json' could not be parsed as a Condition or a ConditionGroup.")


_TARGETS_ADAPTER = pydantic.TypeAdapter(list[TriggerTargetSpec])


def _parse_targets(targets_json: typing.Any, parser: argparse.ArgumentParser) -> list[TriggerTargetSpec]:
    if isinstance(targets_json, dict):
        targets_json = [targets_json]
    if not isinstance(targets_json, list):
        parser.error("Provided '--targets-json' must be a JSON object or a JSON list of target specs.")
    try:
        return _TARGETS_ADAPTER.validate_python(targets_json)
    except pydantic.ValidationError as exc:
        parser.error(f"Provided '--targets-json' is not a valid list of target specs: {exc}")


def create(args, context: CLIContext, parser: argparse.ArgumentParser):
    if args.schedule is None and (not args.on or args.once_per is None):
        parser.error("Provide either '--schedule', or '--on' together with '--once-per'.")
    if args.schedule is not None and (args.on or args.once_per is not None):
        parser.error("'--schedule' cannot be combined with '--on' or '--once-per'.")
    trigger = Trigger.create(
        name=args.name,
        events=[PlatformEventType(event) for event in args.on] if args.on else None,
        once_per=OncePer(args.once_per) if args.once_per is not None else None,
        schedule=args.schedule,
        targets=_parse_targets(args.targets_json, parser),
        condition=_parse_condition(args.condition_json, parser),
        enabled=not args.disabled,
        caller_org_id=args.org,
        roboto_client=context.roboto_client,
    )
    print(json.dumps(trigger.to_dict(), indent=2))


def create_setup_parser(parser):
    parser.add_argument("--name", type=str, required=True, help=NAME_PARAM_HELP)
    parser.add_argument(
        "--on",
        nargs="+",
        action="extend",
        choices=sorted(member.value for member in DEFAULT_PLATFORM_EVENT_CATALOG.subscribable_types()),
        help="One or more platform event types the trigger subscribes to (with '--once-per').",
    )
    parser.add_argument(
        "--once-per",
        choices=[member.value for member in OncePer],
        help="What the trigger fires at most once per: the occurrence, or an entity the event names.",
    )
    parser.add_argument(
        "--schedule",
        type=str,
        help="A five-field cron expression (UTC) to fire on instead of events, e.g. '0 9 * * 1'.",
    )
    parser.add_argument(
        "--targets-json",
        required=True,
        type=JsonFileOrStrType,
        help=(
            "Inline JSON or a path to a JSON file with the trigger's target spec(s): one object or a list, "
            'each discriminated on "type" (invoke_action | start_agent | send_slack_message). Example: '
            '\'[{"type": "start_agent", "target_id": "analyze", "agent_id": "ag_123"}]\'.'
        ),
    )
    parser.add_argument(
        "--condition-json",
        type=JsonFileOrStrType,
        help="Inline JSON or a path to a JSON file with a Condition/ConditionGroup over the event namespace.",
    )
    parser.add_argument("--disabled", action="store_true", help="Create the trigger disabled.")
    add_org_arg(parser=parser)


def update(args, context: CLIContext, parser: argparse.ArgumentParser):
    if args.schedule is not None and (args.on or args.once_per is not None):
        parser.error("'--schedule' cannot be combined with '--on' or '--once-per'.")
    trigger = Trigger.from_name(name=args.name, owner_org_id=args.org, roboto_client=context.roboto_client)
    updates: dict[str, typing.Any] = {}
    if args.on:
        updates["events"] = [PlatformEventType(event) for event in args.on]
    if args.once_per is not None:
        updates["once_per"] = OncePer(args.once_per)
    if args.schedule is not None:
        updates["schedule"] = args.schedule
    if args.targets_json is not None:
        updates["targets"] = _parse_targets(args.targets_json, parser)
    if args.clear_condition:
        updates["condition"] = None
    elif args.condition_json is not None:
        updates["condition"] = _parse_condition(args.condition_json, parser)
    if not updates:
        parser.error("Provide at least one field to update.")
    trigger.update(**updates)
    print(json.dumps(trigger.to_dict(), indent=2))


def update_setup_parser(parser):
    parser.add_argument("name", type=str, help=NAME_PARAM_HELP)
    parser.add_argument(
        "--on",
        nargs="+",
        action="extend",
        choices=sorted(member.value for member in DEFAULT_PLATFORM_EVENT_CATALOG.subscribable_types()),
        help="Replace the subscribed event types. Keeps the current '--once-per' unless that is given too.",
    )
    parser.add_argument(
        "--once-per",
        choices=[member.value for member in OncePer],
        help="Replace what the trigger fires once per, keeping the current event subscription.",
    )
    parser.add_argument(
        "--schedule",
        type=str,
        help="Replace the firing source with this five-field UTC cron expression.",
    )
    parser.add_argument(
        "--targets-json",
        type=JsonFileOrStrType,
        help=(
            "Replace the target list. Same shape as 'create'. A target whose id is referenced by existing "
            "dispatches must keep that id."
        ),
    )
    condition = parser.add_mutually_exclusive_group()
    condition.add_argument(
        "--condition-json",
        type=JsonFileOrStrType,
        help="Replace the condition. Inline JSON or a path to a JSON file.",
    )
    condition.add_argument("--clear-condition", action="store_true", help="Remove the condition entirely.")
    add_org_arg(parser=parser)


def get(args, context: CLIContext, parser: argparse.ArgumentParser):
    trigger = Trigger.from_name(name=args.name, owner_org_id=args.org, roboto_client=context.roboto_client)
    print(json.dumps(trigger.to_dict(), indent=2))


def get_setup_parser(parser):
    parser.add_argument("name", type=str, help=NAME_PARAM_HELP)
    add_org_arg(parser=parser)


def list_triggers(args, context: CLIContext, parser: argparse.ArgumentParser):
    records = [
        trigger.to_dict() for trigger in Trigger.list(owner_org_id=args.org, roboto_client=context.roboto_client)
    ]
    print(json.dumps(records, indent=2))


def list_setup_parser(parser):
    add_org_arg(parser=parser)


def _set_enabled(args, context: CLIContext, enabled: bool):
    trigger = Trigger.from_name(name=args.name, owner_org_id=args.org, roboto_client=context.roboto_client)
    trigger.set_enabled(enabled)
    print(f"Trigger '{args.name}' is now {'enabled' if enabled else 'disabled'}.")


def enable(args, context: CLIContext, parser: argparse.ArgumentParser):
    _set_enabled(args, context, enabled=True)


def disable(args, context: CLIContext, parser: argparse.ArgumentParser):
    _set_enabled(args, context, enabled=False)


def name_org_setup_parser(parser):
    parser.add_argument("name", type=str, help=NAME_PARAM_HELP)
    add_org_arg(parser=parser)


def delete(args, context: CLIContext, parser: argparse.ArgumentParser):
    trigger = Trigger.from_name(name=args.name, owner_org_id=args.org, roboto_client=context.roboto_client)
    trigger.delete()
    print(f"Successfully deleted trigger '{args.name}'")


def dry_run(args, context: CLIContext, parser: argparse.ArgumentParser):
    trigger = Trigger.from_name(name=args.name, owner_org_id=args.org, roboto_client=context.roboto_client)
    trace = trigger.dry_run(
        dataset_id=args.dataset_id,
        file_id=args.file_id,
        invocation_id=args.invocation_id,
        session_id=args.session_id,
        event_id=args.event_id,
        event_type=PlatformEventType(args.on) if args.on else None,
        scheduled_for=args.scheduled_for,
    )
    print(trace.verdict)
    for gate in trace.gates:
        marker = {
            TriggerDryRunGateStatus.Passed: "PASS",
            TriggerDryRunGateStatus.Failed: "FAIL",
            TriggerDryRunGateStatus.NotEvaluated: "SKIP",
        }[gate.status]
        print(f"  [{marker}] {gate.gate.value}: {gate.detail or ''}")
        for leaf in gate.condition_leaves or []:
            print(
                f"         {leaf.field} {leaf.comparator.value} {leaf.expected!r} "
                f"-- actual: {leaf.actual!r} ({'ok' if leaf.passed else 'miss'})"
            )
        for target in gate.targets or []:
            reason = f" -- {target.reason}" if target.reason else ""
            print(f"         target {target.target_id}: {'accepts' if target.accepted else 'declines'}{reason}")


def dry_run_setup_parser(parser):
    parser.add_argument("name", type=str, help=NAME_PARAM_HELP)
    subject = parser.add_mutually_exclusive_group()
    subject.add_argument("--dataset-id", type=str, help="Synthesize an event about this dataset.")
    subject.add_argument("--file-id", type=str, help="Synthesize an event about this file.")
    subject.add_argument("--invocation-id", type=str, help="Synthesize an event about this invocation.")
    subject.add_argument("--session-id", type=str, help="Synthesize an event about this session.")
    subject.add_argument("--event-id", type=str, help="Synthesize a platform event about this event.")
    subject.add_argument(
        "--scheduled-for",
        type=datetime.datetime.fromisoformat,
        help=(
            "For a schedule-fired trigger: the UTC minute to pretend the schedule fired at "
            "(ISO 8601, e.g. 2026-09-16T15:00:00Z). Defaults to the schedule's next occurrence; "
            "a schedule-fired trigger takes no entity reference."
        ),
    )
    parser.add_argument(
        "--on",
        choices=[member.value for member in PlatformEventType],
        help="Which subscribed platform event type to synthesize; defaults to the first compatible with the reference.",
    )
    add_org_arg(parser=parser)


create_command = RobotoCommand(
    name="create",
    logic=create,
    setup_parser=create_setup_parser,
    command_kwargs={"help": "Creates a trigger subscribing to platform events with one or more targets."},
)

update_command = RobotoCommand(
    name="update",
    logic=update,
    setup_parser=update_setup_parser,
    command_kwargs={"help": "Changes a trigger's firing source, condition, or targets."},
)

get_command = RobotoCommand(
    name="get",
    logic=get,
    setup_parser=get_setup_parser,
    command_kwargs={"help": "Looks up a trigger by name."},
)

list_command = RobotoCommand(
    name="list",
    logic=list_triggers,
    setup_parser=list_setup_parser,
    command_kwargs={"help": "Lists every trigger in the org, event-fired and scheduled."},
)

enable_command = RobotoCommand(
    name="enable",
    logic=enable,
    setup_parser=name_org_setup_parser,
    command_kwargs={"help": "Enables a trigger."},
)

disable_command = RobotoCommand(
    name="disable",
    logic=disable,
    setup_parser=name_org_setup_parser,
    command_kwargs={"help": "Disables a trigger."},
)

delete_command = RobotoCommand(
    name="delete",
    logic=delete,
    setup_parser=name_org_setup_parser,
    command_kwargs={"help": "Deletes a trigger."},
)

dry_run_command = RobotoCommand(
    name="dry-run",
    logic=dry_run,
    setup_parser=dry_run_setup_parser,
    command_kwargs={"help": "Explains whether a trigger would fire for an entity, gate by gate."},
)


def sample(args, context: CLIContext, parser: argparse.ArgumentParser):
    samples = Trigger.platform_event_samples(roboto_client=context.roboto_client)
    sample = samples[PlatformEventType(args.event_type)]
    if args.paths:
        for path in sample.paths:
            print(path)
        return
    print(json.dumps({"event": sample.event, "namespace": sample.namespace}, indent=2))


def sample_setup_parser(parser):
    parser.add_argument(
        "event_type",
        choices=[member.value for member in PlatformEventType],
        help="The event type to show a sample of.",
    )
    parser.add_argument(
        "--paths",
        action="store_true",
        help="Print only the {{root.path}} names a condition or template may reference, one per line.",
    )


sample_command = RobotoCommand(
    name="sample",
    logic=sample,
    setup_parser=sample_setup_parser,
    command_kwargs={
        "help": "Shows a realistic, fully dereferenced sample of an event type: what conditions and templates can see."
    },
)

commands = [
    create_command,
    update_command,
    get_command,
    list_command,
    enable_command,
    disable_command,
    delete_command,
    dry_run_command,
    sample_command,
]

command_set = RobotoCommandSet(
    name="triggers",
    help="Create and manage event-driven triggers (platform events, conditions, multi-target).",
    commands=commands,
)
