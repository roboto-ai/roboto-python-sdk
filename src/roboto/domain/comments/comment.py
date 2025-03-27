# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing
import urllib.parse

from ...http import RobotoClient
from .operations import (
    CreateCommentRequest,
    UpdateCommentRequest,
)
from .record import (
    CommentEntityType,
    CommentRecord,
)


class Comment:
    """
    Comments can be made on a number of Roboto resources, like datasets, files, action invocations, and more.
    They support ``@<user_id>`` mention syntax that you can use to notify others of the comment.
    """

    __record: CommentRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        comment_text: str,
        entity_id: str,
        entity_type: CommentEntityType,
        roboto_client: typing.Optional[RobotoClient] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> "Comment":
        roboto_client = RobotoClient.defaulted(roboto_client)

        request = CreateCommentRequest(
            entity_type=entity_type,
            entity_id=entity_id,
            comment_text=comment_text,
        )

        record = roboto_client.post(
            "v1/comments", data=request, caller_org_id=caller_org_id
        ).to_record(CommentRecord)

        return cls(record, roboto_client)

    @classmethod
    def from_id(
        cls,
        comment_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Comment":
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(
            f"v1/comments/{comment_id}", owner_org_id=owner_org_id
        ).to_record(CommentRecord)
        return cls(record, roboto_client)

    @classmethod
    def for_entity(
        cls,
        entity_type: CommentEntityType,
        entity_id: str,
        owner_org_id: typing.Optional[str] = None,
        page_token: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> tuple[collections.abc.Sequence["Comment"], typing.Optional[str]]:
        roboto_client = RobotoClient.defaulted(roboto_client)

        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = page_token

        response_page = roboto_client.get(
            f"v1/comments/{entity_type}/{entity_id}",
            query=query_params,
            owner_org_id=owner_org_id,
        ).to_paginated_list(CommentRecord)

        return [
            cls(record, roboto_client) for record in response_page.items
        ], response_page.next_token

    @classmethod
    def for_entity_type(
        cls,
        entity_type: CommentEntityType,
        owner_org_id: typing.Optional[str] = None,
        page_token: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> tuple[collections.abc.Sequence["Comment"], typing.Optional[str]]:
        roboto_client = RobotoClient.defaulted(roboto_client)

        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = page_token

        response_page = roboto_client.get(
            f"v1/comments/type/{entity_type}",
            query=query_params,
            owner_org_id=owner_org_id,
        ).to_paginated_list(CommentRecord)

        return [
            cls(record, roboto_client) for record in response_page.items
        ], response_page.next_token

    @classmethod
    def for_user(
        cls,
        user_id: str,
        owner_org_id: typing.Optional[str] = None,
        page_token: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> tuple[collections.abc.Sequence["Comment"], typing.Optional[str]]:
        roboto_client = RobotoClient.defaulted(roboto_client)

        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = page_token

        quoted_user_id = urllib.parse.quote(user_id, safe="")
        response_page = roboto_client.get(
            f"v1/comments/user/{quoted_user_id}",
            query=query_params,
            owner_org_id=owner_org_id,
        ).to_paginated_list(CommentRecord)

        return [
            cls(record, roboto_client) for record in response_page.items
        ], response_page.next_token

    @classmethod
    def recent_for_org(
        cls,
        owner_org_id: typing.Optional[str] = None,
        page_token: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> tuple[collections.abc.Sequence["Comment"], typing.Optional[str]]:
        roboto_client = RobotoClient.defaulted(roboto_client)

        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = page_token

        response_page = roboto_client.get(
            "v1/comments/recent", query=query_params, owner_org_id=owner_org_id
        ).to_paginated_list(CommentRecord)

        return [
            cls(record, roboto_client) for record in response_page.items
        ], response_page.next_token

    def __init__(
        self, record: CommentRecord, roboto_client: typing.Optional[RobotoClient] = None
    ) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def comment_id(self) -> str:
        return self.__record.comment_id

    @property
    def created(self) -> datetime.datetime:
        return self.__record.created

    @property
    def created_by(self) -> str:
        return self.__record.created_by

    @property
    def modified(self) -> datetime.datetime:
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        return self.__record.modified_by

    @property
    def record(self) -> CommentRecord:
        return self.__record

    def delete_comment(self) -> None:
        self.__roboto_client.delete(f"/v1/comments/{self.comment_id}")

    def update_comment(self, comment_text: str) -> "Comment":
        self.__record = self.__roboto_client.put(
            f"/v1/comments/{self.comment_id}",
            data=UpdateCommentRequest(
                comment_text=comment_text,
            ),
        ).to_record(CommentRecord)

        return self
