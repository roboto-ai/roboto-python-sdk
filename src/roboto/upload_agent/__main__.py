# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import collections.abc
import logging
import pathlib
import sys
import time
import typing

import filelock
import pydantic

from ..config import DEFAULT_ROBOTO_DIR
from ..domain import datasets
from ..http import (
    RobotoClient,
    RobotoRequester,
    RobotoTool,
)
from ..logging import default_logger
from .agent import UploadAgent
from .files import UploadAgentConfig

logger = default_logger()
logging.basicConfig(format="%(asctime)s [%(levelname)s]: %(message)s", datefmt="%Y-%m-%dT%H:%M:%S%z")

agent_config_file = DEFAULT_ROBOTO_DIR / "upload_agent.json"
"""Path of the upload agent's settings file, which ``configure`` writes and ``run`` reads."""

agent_config_lockfile = DEFAULT_ROBOTO_DIR / "tmp" / "upload_agent.lock"
"""Path of the lock file that stops two runs of the upload agent on one machine from uploading at the same time."""


def configure():
    """Prompt for the upload agent's settings and write them to ``~/.roboto/upload_agent.json``.

    ``roboto-agent configure`` calls this. It asks for the name of the upload config file to look for, whether to
    delete files once they are uploaded, and at least one directory to scan, and asks before overwriting an existing
    settings file.
    """
    if not DEFAULT_ROBOTO_DIR.is_dir():
        print(
            f"Roboto config directory {DEFAULT_ROBOTO_DIR} has not been created yet, creating it now\n",
        )
        DEFAULT_ROBOTO_DIR.mkdir(parents=True)

    if agent_config_file.is_file():
        print(
            f"Roboto config file {agent_config_file} already exists, this will command overwrite it.",
        )
        choice = input("Do you want to continue? [y/n]: ").lower()
        if choice not in ["y", "yes"]:
            return
        print("")

    print(
        "Enter an upload config filename for the agent to search for, or press enter to use the "
        + "default (.roboto_upload.json).\n"
        + "Any file with this name signals to the upload agent that a new dataset should be created and files in the "
        + "same directory or subdirectories as the upload config file should be uploaded to the newly created dataset."
    )
    upload_config_filename = input("Upload config filename [.roboto_upload.json]: ")
    upload_config_filename = upload_config_filename.strip() or ".roboto_upload.json"

    print("")
    choice = input("Do you want the roboto-agent to locally delete files after they've been uploaded? [y/n]: ").lower()
    delete_uploaded_files = choice in ["y", "yes"]

    search_paths: list[pathlib.Path] = []
    print(
        "\nEnter one search path at a time (absolute or relative).\n"
        "These paths will be scanned recursively for upload config files each time the upload agent runs.\n"
        "Press enter on an empty line to finish entering search paths.\n"
    )

    while True:
        user_input = input("Search path: ")
        if user_input.strip() == "":
            if len(search_paths) == 0:
                print(
                    "No search paths were provided, at least one is required for the upload agent to work.\n",
                )
                continue
            print("Done adding search paths.\n")
            break

        search_path = pathlib.Path(user_input).resolve()
        if not search_path.is_dir():
            print(
                f"Path {search_path} does not exist or is not a directory.\n",
            )
            continue

        search_paths.append(search_path)
        print(f"Added search path {search_path}\n")

    new_config_file = UploadAgentConfig(
        upload_config_filename=upload_config_filename,
        search_paths=search_paths,
        delete_uploaded_files=delete_uploaded_files,
    )

    agent_config_file.write_text(new_config_file.model_dump_json(indent=2))
    print(f"Wrote config file to {agent_config_file}")


def configure_subcommand(args: argparse.Namespace) -> None:
    """Run ``configure``.

    ``roboto-agent configure`` calls this.

    Args:
        args: Ignored.
    """
    configure()


def run(
    auto_create_upload_configs: bool,
    merge_uploads: bool,
    default_roboto_upload_file: typing.Optional[pathlib.Path] = None,
) -> None:
    """Upload, once, the directories in the search paths that hold an upload config file.

    ``roboto-agent run`` calls this. It reads the settings ``configure`` wrote to ``~/.roboto/upload_agent.json`` and
    makes its requests with credentials from the environment. While it holds ``~/.roboto/tmp/upload_agent.lock``, it:

    1. Writes an upload config file into each non-empty directory one level under a search path that has no upload
       config, in-progress, or completed file, when ``auto_create_upload_configs`` is set.
    2. Uploads each directory that holds an upload config file, with its subdirectories, and logs how many datasets
       it created.

    It logs an error and uploads nothing when the settings file is missing or cannot be parsed, or when
    ``default_roboto_upload_file`` is given without ``auto_create_upload_configs``. When another run holds the lock
    for more than one second, it logs that the agent is already running and returns.

    Args:
        auto_create_upload_configs: Whether to write upload config files into new directories before uploading.
        merge_uploads: Whether to upload every directory into one new dataset instead of one dataset per directory.
        default_roboto_upload_file: Upload config file whose contents the written upload config files copy. Only
            valid with ``auto_create_upload_configs``. ``None`` uses ``~/.roboto/default_roboto_upload.json`` when it
            exists, and an empty upload config otherwise.
    """
    if default_roboto_upload_file is not None and not auto_create_upload_configs:
        logger.error("--default-upload-config can only be used with --auto-create-upload-configs")
        return

    if not agent_config_file.is_file():
        logger.error(
            f"No upload agent config file found at {agent_config_file}. Please run "
            + "'roboto-agent configure' to generate it."
        )
        return

    try:
        agent_config = UploadAgentConfig.model_validate_json(agent_config_file.read_text())
    except pydantic.ValidationError:
        logger.error(
            f"Upload agent config file {agent_config_file} could not be parsed, which means it's incorrectly "
            + "formatted. Please run 'roboto-agent configure' to generate a new one."
        )
        return

    roboto_client = RobotoClient.from_env()
    roboto_client.http_client.set_requester(RobotoRequester.for_tool(RobotoTool.UploadAgent))

    upload_agent = UploadAgent(
        agent_config,
        roboto_client,
        default_roboto_upload_file,
    )

    uploaded_datasets: collections.abc.Sequence[datasets.Dataset]

    try:
        with filelock.FileLock(agent_config_lockfile, timeout=1):
            if auto_create_upload_configs:
                upload_agent.create_upload_configs()

            uploaded_datasets = upload_agent.process_uploads(merge_uploads=merge_uploads)
    except filelock.Timeout:
        logger.info(
            "Roboto upload agent appears to already be running, nothing to do. If you don't think this is correct, "
            + "the agent filelock %s may have been orphaned, which you can fix by deleting it.",
            agent_config_lockfile,
        )
        return

    logger.info("Uploaded %d datasets", len(uploaded_datasets))


def run_forever(
    scan_period_seconds: int,
    auto_create_upload_configs: bool,
    merge_uploads: bool,
    default_roboto_upload_file: typing.Optional[pathlib.Path] = None,
) -> None:
    """Call ``run`` repeatedly, waiting ``scan_period_seconds`` after each run finishes, until the user presses Ctrl+C.

    ``roboto-agent run --forever`` calls this. Ctrl+C stops it even in the middle of a run, and it then returns
    without raising ``KeyboardInterrupt``.

    Args:
        scan_period_seconds: Seconds to wait after one run finishes before starting the next.
        auto_create_upload_configs: Passed to ``run``.
        merge_uploads: Passed to ``run``.
        default_roboto_upload_file: Passed to ``run``.
    """
    print(
        "Starting roboto-agent in run forever mode, press Ctrl+C to stop.",
        file=sys.stdout,
    )

    try:
        while True:
            logger.info("Running upload agent")
            run(
                auto_create_upload_configs=auto_create_upload_configs,
                merge_uploads=merge_uploads,
                default_roboto_upload_file=default_roboto_upload_file,
            )
            logger.info(f"Run completed, sleeping for {scan_period_seconds} seconds before next attempt.")
            time.sleep(scan_period_seconds)
    except KeyboardInterrupt:
        pass


def run_subcommand(args: argparse.Namespace) -> None:
    """Run the upload agent once, or with ``--forever``, repeatedly with 30-second waits.

    ``roboto-agent run`` calls this.

    Args:
        args: Parsed command-line arguments of ``roboto-agent run``.
    """
    if args.forever:
        run_forever(
            scan_period_seconds=30,
            auto_create_upload_configs=args.auto_create_upload_configs,
            merge_uploads=args.merge_uploads,
            default_roboto_upload_file=args.default_roboto_upload_file,
        )
    else:
        run(
            auto_create_upload_configs=args.auto_create_upload_configs,
            merge_uploads=args.merge_uploads,
            default_roboto_upload_file=args.default_roboto_upload_file,
        )


def main():
    """Parse the ``roboto-agent`` command line, set the log level, and run the chosen subcommand.

    ``roboto-agent`` and ``python -m roboto.upload_agent`` call this. It prints the help and returns when no
    subcommand is given.
    """
    parser = argparse.ArgumentParser(
        prog="roboto-agent",
        description="Upload agent for managing automatic dataset uploads to Roboto based on configuration.",
    )

    verbosity_group = parser.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        "--verbose",
        "-v",
        help=(
            "Set increasing levels of verbosity. -v prints WARNING logs, -vv prints INFO logs, -vvv prints DEBUG logs."
        ),
        action="count",
        default=0,
    )
    verbosity_group.add_argument("-q", "--quiet", action="store_true", help="Suppress output except for errors")

    subparsers = parser.add_subparsers(dest="command", help="sub-command help")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument(
        "-f",
        "--forever",
        help="Attempts to call run every 30 seconds forever, " + "and sleeps between runs.",
        action="store_true",
    )
    run_parser.add_argument(
        "-m",
        "--merge-uploads",
        action="store_true",
        help=(
            "If set, all uploads will be merged into a single dataset. If combined with "
            "--auto-create-upload-configs, this will allow you to set many disparate output locations as your "
            "search paths, and still unite everything under a single dataset. "
            "Any tags/metadata/description set in .roboto_upload.json files will be applied sequentially as updates "
            "to the created dataset. If there are collisions, like multiple different descriptions or multiple "
            "metadata values for the same key, the last one encountered will be used, and the traversal order will "
            "be non-deterministic."
        ),
    )
    run_parser.add_argument(
        "-a",
        "--auto-create-upload-configs",
        action="store_true",
        help="If set, the agent will attempt to create upload configs for any directories one level under your "
        + "configured search paths which don't already have a .roboto_upload.json, "
        + ".roboto_upload_in_progress.json, or .roboto_upload_complete.json file. "
        + "For example, if your search_paths are set to ['/home/username/output'], a directory like "
        + "/home/username/output/2024_01_01T00_00_00 will be automatically prepared for upload. "
        + "By default the contents of the generated .roboto_upload.json file will be {}, but you can override "
        + "this by writing a ~/.roboto/default_roboto_upload.json file, whose contents will always be used instead. "
        + "Environment variables referenced in this file will be resolved appropriately, so you can add something "
        + 'like {"dataset":{"metadata":{"user_from_env":"$USER"}}}.',
    )
    run_parser.add_argument(
        "--default-roboto-upload-file",
        type=pathlib.Path,
        help="Path to a custom default upload config JSON file to use when auto-creating upload configs. "
        + "Only valid when --auto-create-upload-configs is specified. "
        + "If not provided, ~/.roboto/default_roboto_upload.json will be used if it exists.",
        required=False,
    )
    run_parser.set_defaults(func=run_subcommand)

    configure_parser = subparsers.add_parser("configure")
    configure_parser.set_defaults(func=configure_subcommand)

    args = parser.parse_args()

    if args.quiet:
        log_level = logging.ERROR
    elif args.verbose >= 3:
        log_level = logging.DEBUG
    elif args.verbose == 2:
        log_level = logging.INFO
    elif args.verbose == 1:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO

    logging.getLogger().setLevel(log_level)

    if args.command is None:
        parser.print_help()
        return

    args.func(args)


if __name__ == "__main__":
    main()
