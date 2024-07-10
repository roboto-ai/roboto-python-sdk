# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import warnings


def roboto_default_warning_behavior():
    # https://github.com/boto/botocore/issues/619
    warnings.filterwarnings(
        "ignore",
        module="botocore.vendored.requests.packages.urllib3.connectionpool",
        message=".*",
    )
