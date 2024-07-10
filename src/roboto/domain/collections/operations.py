# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Optional, Union

import pydantic
from pydantic import ConfigDict

from roboto.sentinels import NotSet, NotSetType

from .record import CollectionResourceRef


class CreateCollectionRequest(pydantic.BaseModel):
    description: Optional[str] = None
    name: Optional[str] = None
    resources: Optional[list[CollectionResourceRef]] = None
    tags: Optional[list[str]] = None


class UpdateCollectionRequest(pydantic.BaseModel):
    add_resources: Union[list[CollectionResourceRef], NotSetType] = NotSet
    add_tags: Union[list[str], NotSetType] = NotSet
    description: Optional[Union[NotSetType, str]] = NotSet
    name: Optional[Union[NotSetType, str]] = NotSet
    remove_resources: Union[list[CollectionResourceRef], NotSetType] = NotSet
    remove_tags: Union[list[str], NotSetType] = NotSet

    model_config = ConfigDict(json_schema_extra=NotSetType.openapi_schema_modifier)
