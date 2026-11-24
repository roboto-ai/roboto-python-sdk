# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import shlex
import signal
import subprocess
import sys

from ...auth import Permissions
from ...image_registry import ImageRegistry
from ...waiters import TimeoutError, wait_for
from ..command import RobotoCommand
from ..common_args import add_org_arg
from ..context import CLIContext
from ..terminal import print_error_and_exit


def push(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    """Push a local Docker image to Roboto's image registry, creating its repository if needed, and print the image URI.

    1. Exits with an error unless ``docker image inspect`` finds the image and reports its architecture as ``amd64``.
    2. Creates the repository ``<org_id>/<repository>``, named after the local image's repository, or reuses the one
       that already has that name. An image name with more than one colon exits with an error.
    3. Logs Docker in to the registry with temporary read-write credentials, passing the password on standard input.
    4. Tags the local image with the repository's URI and the same tag, ``latest`` when the local name has none, and
       runs ``docker push``.
    5. Checks Roboto for the tag at once, then after waits of 1, 2, 4 and so on seconds, at most 32, and exits with an
       error if the tag has not appeared within five minutes.

    The exit status of ``docker push`` is not checked, so a failed push surfaces only when step 5 gives up. Exits with
    status 130 (128 plus SIGINT) when interrupted during the push or the wait.
    """
    inspect_format_string = "{{ .Architecture }}"
    inspect_cmd = f"docker image inspect --format '{inspect_format_string}' {args.local_image}"
    try:
        inspect_completed_process = subprocess.run(
            shlex.split(inspect_cmd),
            capture_output=True,
            check=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        print_error_and_exit(
            f"Could not find locally built image '{args.local_image}'. Is the repository name and tag correct?",
        )

    if inspect_completed_process.stdout.strip() != "amd64":
        print_error_and_exit(
            [
                "Only amd64 images are supported by the Roboto Platform.",
                "You might be seeing this error if running docker on an ARM-based Mac.",
                "Refer to Docker documentation for how to build AMD-compatible images on non-AMD platforms:",
                "https://docs.docker.com/build/building/multi-platform/",
            ]
        )

    image_registry = ImageRegistry(context.roboto_client)
    parts = args.local_image.split(":")
    if len(parts) == 1:
        repo, tag = parts[0], "latest"
    elif len(parts) == 2:
        repo, tag = parts
    else:
        print_error_and_exit("Invalid image format. Expected '<repository>:<tag>'.")
    repository = image_registry.create_repository(repo, org_id=args.org)
    credentials = image_registry.get_temporary_credentials(
        repository["repository_uri"], Permissions.ReadWrite, org_id=args.org
    )
    login_cmd = f"docker login --username {credentials.username} --password-stdin {credentials.registry_url}"
    try:
        subprocess.run(
            shlex.split(login_cmd),
            capture_output=True,
            check=True,
            input=credentials.password,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        msgs = [
            "Failed to set Docker credentials for Roboto's image registry.",
        ]
        if exc.stdout:
            msgs.append(exc.stdout)
        if exc.stderr:
            msgs.append(exc.stderr)
        print_error_and_exit(msgs)

    image_uri = f"{repository['repository_uri']}:{tag}"
    tag_cmd = f"docker tag {args.local_image} {image_uri}"
    try:
        subprocess.run(
            shlex.split(tag_cmd),
            capture_output=True,
            check=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        msgs = [f"Failed to tag local image '{args.local_image}' as '{image_uri}'."]
        if exc.stdout:
            msgs.append(exc.stdout)
        if exc.stderr:
            msgs.append(exc.stderr)
        print_error_and_exit(msgs)

    push_cmd = f"docker push {image_uri}"
    if args.quiet:
        push_cmd = f"{push_cmd} --quiet"

    with subprocess.Popen(
        shlex.split(push_cmd),
        text=True,
    ) as push_proc:
        try:
            push_proc.wait()
        except KeyboardInterrupt:
            push_proc.kill()
            print("")
            sys.exit(128 + signal.SIGINT.value)

    if not args.quiet:
        print("Waiting for image to be available...")
    try:
        wait_for(
            image_registry.repository_contains_image,
            args=[repository["repository_name"], tag, args.org],
            interval=lambda iteration: min((2**iteration) / 2, 32),
        )
        if not args.quiet:
            print(f"Image pushed successfully! You can now use '{image_uri}' in your Roboto Actions.")
    except TimeoutError:
        print_error_and_exit("Image could not be confirmed as successfully pushed. Try pushing again in a few minutes.")
    except KeyboardInterrupt:
        print("")
        sys.exit(128 + signal.SIGINT.value)


def push_parser(parser: argparse.ArgumentParser) -> None:
    add_org_arg(parser)

    parser.add_argument(
        "local_image",
        action="store",
        help=(
            "Specify the local image to push, in the format ``<repository>:<tag>``. "
            "If no tag is specified, ``latest`` is assumed. "
            "Image must exist locally (i.e. ``docker images`` must list it)."
        ),
    )

    parser.add_argument(
        "-q",
        "--quiet",
        dest="quiet",
        action="store_true",
        help="Only output the image URI, terminated by a newline, if successful.",
    )


push_command = RobotoCommand(
    name="push",
    logic=push,
    setup_parser=push_parser,
    command_kwargs={"help": ("Push a local container image into Roboto's image registry. Requires Docker CLI.")},
)
