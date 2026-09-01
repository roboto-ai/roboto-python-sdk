# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Regenerate the checked-in filter comparator manifest.

The manifest states which operators each filter variant accepts, derived from the models in
:mod:`roboto.query.filters`. A Vitest test in web-ui reads it to check that the filter UI's
own copy of that vocabulary agrees, since there is no code generation between the two.

``test_the_checked_in_comparator_manifest_is_current`` fails when the models and the manifest
disagree. This is what fixes that:

    pants run packages/roboto/build-support/generate_filter_comparators
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
