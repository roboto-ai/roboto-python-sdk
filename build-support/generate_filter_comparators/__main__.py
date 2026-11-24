# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regenerate ``filter_comparators.json``, the checked-in list of the operators each filter type accepts.

The list is read from the filter models in ``roboto.query.filters``. The Roboto web app's tests read the file to check
the web app's own copy of those operators, since nothing generates either one from the other. When a filter model's
operators change, a test fails until you regenerate the file:

    pants run packages/roboto/build-support/generate_filter_comparators:generate
"""

import argparse
import json
import pathlib

from roboto.query.filters import comparators_by_type

DEFAULT_OUTPUT = pathlib.Path("packages/roboto/src/roboto/query/filter_comparators.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT,
        help=f"Where to write the manifest. Defaults to {DEFAULT_OUTPUT}.",
    )
    args = parser.parse_args()

    args.output.write_text(json.dumps(comparators_by_type(), indent=2, sort_keys=True) + "\n")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
