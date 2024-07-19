# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json

from ...domain.orgs import (
    Org,
    OrgInvite,
    OrgRoleName,
)
from ...domain.orgs.s3_integration import (
    S3IntegrationService,
)
from ..command import (
    RobotoCommand,
    RobotoCommandSet,
)
from ..common_args import get_defaulted_org_id
from ..context import CLIContext

GENERIC_ORG_ONLY_SETUP_PARSER_DEFAULT_HELP = "perform some action"


def generic_org_add_argument(
    parser, action_to_perform: str = GENERIC_ORG_ONLY_SETUP_PARSER_DEFAULT_HELP
):
    parser.add_argument(
        "--org",
        type=str,
        help=f"The org_id of the org for which to {action_to_perform}. "
        + "This parameter is only required if the caller is a member of more than one org, "
        + "otherwise this action will be performed implicitly on their single org.",
    )


def generic_org_only_setup_parser(
    action_to_perform: str = GENERIC_ORG_ONLY_SETUP_PARSER_DEFAULT_HELP,
):
    def setup(parser):
        generic_org_add_argument(parser=parser, action_to_perform=action_to_perform)

    return setup


def create(args, context: CLIContext, parser: argparse.ArgumentParser):
    org = Org.create(
        name=args.name,
        bind_email_domain=args.bind_email_domain,
        roboto_client=context.roboto_client,
    )
    print(json.dumps(org.to_dict(), indent=2))


def create_setup_parser(parser):
    parser.add_argument(
        "--name", type=str, required=True, help="A human readable name for this org"
    )
    parser.add_argument(
        "--bind-email-domain",
        action="store_true",
        help="Automatically add new users with your email domain to this org",
    )


def delete(args, context: CLIContext, parser: argparse.ArgumentParser):
    org = Org.from_id(org_id=args.org, roboto_client=context.roboto_client)

    if not args.ignore_prompt:
        print("Are you absolutely sure you want to delete your org? [y/n]: ")

        choice = input().lower()
        if choice not in ["y", "yes"]:
            return

    org.delete()
    print("Successfully deleted!")


def delete_setup_parser(parser):
    parser.add_argument(
        "--org",
        type=str,
        required=True,
        help="The org_id for the org you're about to delete.",
    )

    parser.add_argument(
        "--ignore-prompt",
        action="store_true",
        help="Ignore the prompt which asks you to confirm that you'd like to delete your org.",
    )


def show(args, context: CLIContext, parser: argparse.ArgumentParser):
    record = Org.from_id(org_id=args.org, roboto_client=context.roboto_client)
    print(json.dumps(record.to_dict(), indent=2))


def show_setup_parser(parser):
    parser.add_argument(
        "--org",
        type=str,
        help="The org_id for the org you want to see.",
    )


def list_org_members(args, context: CLIContext, parser: argparse.ArgumentParser):
    org_users = Org.from_id(args.org).users()
    for org_user in org_users:
        # We'll need to rethink filtering out service users once
        # they are more directly customer-facing
        if org_user.user.is_service_user:
            continue

        print(
            org_user.model_dump_json(
                indent=2,
                exclude={
                    "org",
                },
            )
        )


def list_org_members_setup_parser(parser):
    parser.add_argument(
        "--org",
        type=str,
        help="The org_id for the org you want to see.",
    )


def remove_user(args, context: CLIContext, parser: argparse.ArgumentParser):
    org = Org.from_id(org_id=args.org, roboto_client=context.roboto_client)
    org.remove_user(user_id=args.user)
    print("Successfully removed!")


def remove_user_setup_parser(parser):
    parser.add_argument(
        "--user",
        type=str,
        required=True,
        help="The user_id of the user to remove.",
    )
    parser.add_argument(
        "--org",
        type=str,
        help="The org_id of the org to remove a user from. "
        + "Required only if the caller is a member of more than one org.",
    )


def invite_user(args, context: CLIContext, parser: argparse.ArgumentParser):
    OrgInvite.create(
        invited_user_id=args.user,
        org_id=args.org,
        roboto_client=context.roboto_client,
    )
    print("Invite sent!")


def invite_user_setup_parser(parser):
    parser.add_argument(
        "--user",
        type=str,
        required=True,
        help="The user_id of the user to invite.",
    )
    parser.add_argument(
        "--org",
        help="The org_id of the org to invite a user to. "
        + "Required only if the caller is a member of more than one org.",
    )


def list_invites(args, context: CLIContext, parser: argparse.ArgumentParser):
    invites = OrgInvite.for_org(org_id=args.org, roboto_client=context.roboto_client)
    for invite in invites:
        print(json.dumps(invite.to_dict(), indent=2))


def list_invites_setup_parser(parser):
    parser.add_argument(
        "--org",
        help="The org_id of the org to view invites for. "
        + "Required only if the caller is a member of more than one org.",
    )


def add_role(args, context: CLIContext, parser: argparse.ArgumentParser):
    Org.from_id(org_id=args.org, roboto_client=context.roboto_client).add_role_for_user(
        user_id=args.user, role=args.role
    )
    print("Added!")


def add_role_setup_parser(parser):
    parser.add_argument(
        "--user",
        type=str,
        required=True,
        help="The user_id of the user to add a role for.",
    )
    parser.add_argument(
        "--role",
        type=OrgRoleName,
        choices=[OrgRoleName.admin, OrgRoleName.owner],
        help="The role to grant to the specified user",
    )
    parser.add_argument(
        "--org",
        type=str,
        help="The org_id of the org for which to add permissions for the specified user. "
        + "Required only if the caller is a member of more than one org.",
    )


def remove_role(args, context: CLIContext, parser: argparse.ArgumentParser):
    Org.from_id(
        org_id=args.org, roboto_client=context.roboto_client
    ).remove_role_from_user(user_id=args.user, role=args.role)
    print("Removed!")


def remove_role_setup_parser(parser):
    parser.add_argument(
        "--user",
        type=str,
        required=True,
        help="The user_id of the user to add a role for. "
        + "This can be your own user_id if you would like to step down as an admin or owner.",
    )
    parser.add_argument(
        "--role",
        type=OrgRoleName,
        choices=[OrgRoleName.admin, OrgRoleName.owner],
        help="The role to remove for the specified user",
    )
    parser.add_argument(
        "--org",
        type=str,
        help="The org_id of the org for which to remove permissions for the specified user. "
        + "Required only if the caller is a member of more than one org.",
    )


def bind_email_domain(args, context: CLIContext, parser: argparse.ArgumentParser):
    Org.from_id(org_id=args.org, roboto_client=context.roboto_client).bind_email_domain(
        args.email_domain
    )
    print(f"Successfully bound domain {args.email_domain}")


def bind_email_domain_setup_parser(parser):
    generic_org_add_argument(parser=parser, action_to_perform="bind an email domain")
    parser.add_argument(
        "--email-domain",
        type=str,
        required=True,
        help="The email domain to bind to an org.",
    )


def unbind_email_domain(args, context: CLIContext, parser: argparse.ArgumentParser):
    Org.from_id(
        org_id=args.org, roboto_client=context.roboto_client
    ).unbind_email_domain(args.email_domain)
    print(f"Successfully unbound domain {args.email_domain}")


def unbind_email_domain_setup_parser(parser):
    generic_org_add_argument(parser=parser, action_to_perform="unbind an email domain")
    parser.add_argument(
        "--email-domain",
        type=str,
        required=True,
        help="The email domain to unbind from an org.",
    )


def list_email_domains(args, context: CLIContext, parser: argparse.ArgumentParser):
    for domain in Org.from_id(
        org_id=args.org, roboto_client=context.roboto_client
    ).email_domains():
        print(domain)


def register_bucket(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    service = S3IntegrationService(context.roboto_client)
    org_id = get_defaulted_org_id(args.org)

    service.register_bucket(
        org_id=org_id,
        bucket_name=args.bucket_name,
        account_id=args.aws_account,
    )

    print(
        "Bucket registered successfully! It will be used to store files for all new datasets."
    )


def register_bucket_setup_parser(parser: argparse.ArgumentParser) -> None:
    generic_org_add_argument(parser, "register an S3 bring-your-own-bucket")
    parser.add_argument(
        "--bucket-name",
        type=str,
        required=True,
        help="The base name of the S3 bucket you want to register, e.g. 'my-company-roboto-byob'",
    )
    parser.add_argument(
        "--aws-account",
        type=str,
        required=True,
        help="The AWS account to register the bucket in. This command will only work if you also have the calling "
        + "environment configured with AWS credentials for this account that the underlying boto3 client can use. "
        + "For more information on configuring AWS credentials, see "
        + "https://docs.aws.amazon.com/sdkref/latest/guide/standardized-credentials.html.",
    )


create_command = RobotoCommand(
    name="create",
    logic=create,
    setup_parser=create_setup_parser,
    command_kwargs={"help": "Creates a new organization"},
)


delete_command = RobotoCommand(
    name="delete",
    logic=delete,
    setup_parser=delete_setup_parser,
    command_kwargs={"help": "Deletes an existing organization"},
)


show_command = RobotoCommand(
    name="show",
    logic=show,
    setup_parser=show_setup_parser,
    command_kwargs={"help": "Gets metadata for a single organization"},
)


list_org_members_command = RobotoCommand(
    name="members",
    logic=list_org_members,
    setup_parser=list_org_members_setup_parser,
    command_kwargs={"help": "Lists the members of an organization"},
)

remove_user_command = RobotoCommand(
    name="remove-user",
    logic=remove_user,
    setup_parser=remove_user_setup_parser,
    command_kwargs={"help": "Removes a user from an organization"},
)

invite_command = RobotoCommand(
    name="invite-user",
    logic=invite_user,
    setup_parser=invite_user_setup_parser,
    command_kwargs={"help": "Invites a user to join an org."},
)

list_invites_command = RobotoCommand(
    name="list-invites",
    logic=list_invites,
    setup_parser=list_invites_setup_parser,
    command_kwargs={"help": "Lists the current pending invites for a specified org"},
)

bind_email_domain_command = RobotoCommand(
    name="bind-email-domain",
    logic=bind_email_domain,
    setup_parser=bind_email_domain_setup_parser,
    command_kwargs={
        "help": "Binds an email domain to this org, so all new users whose "
        + "emails are part of that domain will automatically be added."
    },
)

unbind_email_domain_command = RobotoCommand(
    name="unbind-email-domain",
    logic=unbind_email_domain,
    setup_parser=unbind_email_domain_setup_parser,
    command_kwargs={
        "help": "Unbinds an email domain from this org, so all new users whose "
        + "emails are part of that domain will no longer be automatically added."
    },
)

list_email_domains_command = RobotoCommand(
    name="list-email-domains",
    logic=list_email_domains,
    setup_parser=generic_org_only_setup_parser(
        action_to_perform="list bound email domains"
    ),
    command_kwargs={
        "help": "Lists the email domains associated with a particular org."
    },
)

add_role_command = RobotoCommand(
    name="add-role",
    logic=add_role,
    setup_parser=add_role_setup_parser,
    command_kwargs={"help": "Promotes a user to a more permissive org access level."},
)

remove_role_command = RobotoCommand(
    name="remove-role",
    logic=remove_role,
    setup_parser=remove_role_setup_parser,
    command_kwargs={"help": "Demotes a user to a less permissive org access level."},
)

register_bucket_command = RobotoCommand(
    name="register-bucket",
    logic=register_bucket,
    setup_parser=register_bucket_setup_parser,
    command_kwargs={
        "help": "Registers an S3 bring-your-own-bucket with Roboto. Only available to premium tier orgs."
    },
)

commands = [
    add_role_command,
    bind_email_domain_command,
    delete_command,
    invite_command,
    list_email_domains_command,
    list_invites_command,
    list_org_members_command,
    register_bucket_command,
    remove_role_command,
    remove_user_command,
    show_command,
    unbind_email_domain_command,
]

command_set = RobotoCommandSet(
    name="orgs",
    help="View details of organizations that you are in, including administration options if applicable.",
    commands=commands,
)
