# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain.files import File
from ..command import RobotoCommand
from ..context import CLIContext
from .shared_helpdoc import DATASET_ID_HELP


def import_external_file(args, context: CLIContext, parser: argparse.ArgumentParser):
    normalized_relative_path = args.path if args.path else args.file.split("/")[-1]

    fl = File.import_one(
        dataset_id=args.dataset_id,
        relative_path=normalized_relative_path,
        uri=args.file,
        roboto_client=context.roboto_client,
    )
    print(fl.file_id)


def import_external_file_setup_parser(parser):
    parser.add_argument(
        "-d", "--dataset-id", type=str, required=True, help=DATASET_ID_HELP
    )
    parser.add_argument(
        "-p",
        "--path",
        type=str,
        required=False,
        help="Relative path of the uploaded file. If unprovided, defaults to the basename from the file URI.",
    )
    parser.add_argument(
        "-f",
        "--file",
        type=str,
        help="The URI of the file to import, e.g. s3://my-bucket/path/to/file.txt for S3 files.",
    )


import_external_file_command = RobotoCommand(
    name="import-external-file",
    logic=import_external_file,
    setup_parser=import_external_file_setup_parser,
    command_kwargs={
        "help": "Imports a file from an external storage location "
        "(like a pre-registered S3 bring-your-own-bucket) into a dataset."
    },
)
