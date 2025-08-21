# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import time

from ...ai.chat import Chat
from ..command import RobotoCommand
from ..common_args import add_org_arg
from ..context import CLIContext

COLOR_BLUE = "\033[34m"
COLOR_WHITE = "\033[37m"
COLOR_RED = "\033[31m"
COLOR_RESET = "\033[0m"

BIG_ART = f"""|===========================|
||       {COLOR_WHITE}@@@@@@@@@@{COLOR_RESET}        ||
||    {COLOR_WHITE}@@@@@@@@@@@@@@@@{COLOR_RESET}     ||
||   {COLOR_WHITE}@@@@@@@@@@@@@@@@@@@{COLOR_RESET}   ||
||  {COLOR_WHITE}@@@@@@        @@@@@@@{COLOR_RESET}  ||
|| {COLOR_WHITE}@@@@@    {COLOR_RED}===={COLOR_WHITE}    @@@@@{COLOR_RESET}  ||
|| {COLOR_RED}        ======{COLOR_WHITE}   @@@@@{COLOR_RESET}  ||
|| {COLOR_RED}        ======{COLOR_WHITE}   @@@@@{COLOR_RESET}  ||
|| {COLOR_WHITE}@@@@@    {COLOR_RED}===={COLOR_WHITE}    @@@@@{COLOR_RESET}  ||
|| {COLOR_WHITE}@@@@@          @@@@@@{COLOR_RESET}   ||
|| {COLOR_WHITE}@@@@@       @@@@@@@@{COLOR_RESET}    ||
|| {COLOR_WHITE}@@@@@ {COLOR_BLUE}     {COLOR_WHITE}@@@@@@@{COLOR_RESET}      ||
|| {COLOR_WHITE}@@@@@ {COLOR_BLUE}oboto {COLOR_WHITE}@@@@@@{COLOR_RESET}      ||
|| {COLOR_WHITE}@@@@@ {COLOR_BLUE}chat   {COLOR_WHITE}@@@@@@{COLOR_RESET}     ||
|| {COLOR_WHITE}@@@@@ {COLOR_BLUE}client  {COLOR_WHITE}@@@@@@{COLOR_RESET}    ||
|| {COLOR_WHITE}@@@@@ {COLOR_BLUE}for cool  {COLOR_WHITE}@@@@@{COLOR_RESET}   ||
|| {COLOR_WHITE}@@@@@ {COLOR_BLUE}engineers  {COLOR_WHITE}@@@@@@{COLOR_RESET} ||
|===========================|"""


VALID_EXIT_COMMANDS = ("quit", "exit", "q", "e")


def start(args, context: CLIContext, parser: argparse.ArgumentParser):
    org_id = args.org

    print(BIG_ART)
    print("\nWhat do you want to chat about? (Enter 'quit' to exit)")

    chat: Chat | None = None

    while True:
        prompt = input("> ")

        if prompt in VALID_EXIT_COMMANDS:
            break

        if prompt.strip() == "":
            continue

        print()

        if chat is None:
            chat = Chat.start(
                message=prompt,
                org_id=org_id,
                roboto_client=context.roboto_client,
            )
        else:
            chat.send_text(prompt)

        for text in chat.stream():
            print(text, end="", flush=True)
            time.sleep(0.05)
        print("\n")


def start_setup_parser(parser):
    add_org_arg(parser)


start_command = RobotoCommand(
    name="start",
    logic=start,
    setup_parser=start_setup_parser,
    command_kwargs={"help": "Start an interactive chat session."},
)
