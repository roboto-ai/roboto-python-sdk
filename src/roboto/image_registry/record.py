# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pydantic


class ContainerImageRepositoryRecord(pydantic.BaseModel):
    org_id: str
    repository_name: str
    repository_uri: str
    arn: str


class ContainerImageRecord(pydantic.BaseModel):
    org_id: str
    repository_name: str
    image_tag: str
    image_uri: str
