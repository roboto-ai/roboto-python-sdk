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
    """A comment: text a user writes on an action, collection, dataset, file, invocation, or trigger.

    A comment belongs to the organization it was created in. Its text can mention other users of that organization,
    each written ``@[<display_name>](<user_id>)``, and Roboto notifies the users it mentions.

    Get a ``Comment`` from ``create`` or ``from_id``, or list comments with ``for_entity``, ``for_entity_type``,
    ``for_user``, and ``recent_for_org``. To wrap a :py:class:`~roboto.domain.comments.CommentRecord` already fetched
    from Roboto, build a ``Comment`` from it directly. Each instance holds a copy of the comment's record, which
    ``update_comment`` replaces with Roboto's response.

    Args:
        record: Record of the comment.
        roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
            :py:meth:`~roboto.http.RobotoClient.from_env`.
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
        """Create a comment on an action, collection, dataset, file, invocation, or trigger.

        A mention in ``comment_text``, written ``@[<display_name>](<user_id>)``, adds that user to the comment's
        :py:attr:`~roboto.domain.comments.CommentRecord.mentions` and notifies them, by email unless their settings
        turn off comment-mention emails. The caller may mention themselves; Roboto does not notify them.

        Args:
            comment_text: Text of the comment.
            entity_id: ID of the resource to comment on, such as a dataset's ``ds_`` ID.
            entity_type: Kind of resource ``entity_id`` names.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.
            caller_org_id: Organization to create the comment in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.

        Returns:
            The new comment.

        Raises:
            RobotoUnauthorizedException: ``comment_text`` mentions a user outside the organization. Roboto has
                already saved the comment.

        Examples:
            Comment on a dataset:

            >>> comment = Comment.create(
            ...     comment_text="This dataset looks good!",
            ...     entity_id="ds_12345",
            ...     entity_type=CommentEntityType.Dataset,
            ... )

            Comment on a file and mention a user, which notifies them:

            >>> comment = Comment.create(
            ...     comment_text="@[Alex Kim](alex@example.com) please review this",
            ...     entity_id="fl_12345",
            ...     entity_type=CommentEntityType.File,
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        request = CreateCommentRequest(
            entity_type=entity_type,
            entity_id=entity_id,
            comment_text=comment_text,
        )

        record = roboto_client.post("v1/comments", data=request, caller_org_id=caller_org_id).to_record(CommentRecord)

        return cls(record, roboto_client)

    @classmethod
    def from_id(
        cls,
        comment_id: str,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Comment":
        """Fetch a comment by its ID.

        Reading a comment takes permission to read the resource it is on.

        Args:
            comment_id: ID of the comment, beginning with ``cm_``.
            owner_org_id: Organization that owns the comment. Defaults to the organization the caller acts in.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The comment.

        Raises:
            RobotoNotFoundException: The organization has no comment with this ID.
            RobotoUnauthorizedException: The caller may not read the resource the comment is on.

        Examples:
            >>> comment = Comment.from_id("cm_12345")
            >>> print(comment.record.comment_text)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        record = roboto_client.get(f"v1/comments/{comment_id}", owner_org_id=owner_org_id).to_record(CommentRecord)
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
        """List one page of the comments on a resource, newest first.

        Each page holds up to 100 comments. A resource that has no comments, or that does not exist, returns an empty
        page. Listing a resource's comments takes permission to read the resource.

        Args:
            entity_type: Kind of resource ``entity_id`` names.
            entity_id: ID of the resource whose comments to list, such as a dataset's ``ds_`` ID.
            owner_org_id: Organization that owns the comments. Defaults to the organization the caller acts in.
            page_token: Token from a previous page's response that resumes the listing after it. ``None`` starts at the
                first page.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            ``(comments, next_token)``: the page's comments and the token for the next page. Pass ``next_token`` as
            ``page_token`` to fetch the next page; it is ``None`` on the last page.

        Examples:
            List the first page of comments on a dataset:

            >>> page, next_token = Comment.for_entity(entity_type=CommentEntityType.Dataset, entity_id="ds_12345")

            List every comment on a file, a page at a time:

            >>> all_comments = []
            >>> page_token = None
            >>> while True:
            ...     page, page_token = Comment.for_entity(
            ...         entity_type=CommentEntityType.File,
            ...         entity_id="fl_12345",
            ...         page_token=page_token,
            ...     )
            ...     all_comments.extend(page)
            ...     if page_token is None:
            ...         break
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = page_token

        response_page = roboto_client.get(
            f"v1/comments/{entity_type}/{entity_id}",
            query=query_params,
            owner_org_id=owner_org_id,
        ).to_paginated_list(CommentRecord)

        return [cls(record, roboto_client) for record in response_page.items], response_page.next_token

    @classmethod
    def for_entity_type(
        cls,
        entity_type: CommentEntityType,
        owner_org_id: typing.Optional[str] = None,
        page_token: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> tuple[collections.abc.Sequence["Comment"], typing.Optional[str]]:
        """List one page of an organization's comments on one kind of resource, newest first.

        Each page holds up to 100 comments.

        Comments on an entity the caller may not read are left out of the
        page they fall on, so a page can hold fewer comments than usual, or
        none, and still return a pagination token. Keep requesting pages until
        the token is None.

        Args:
            entity_type: Kind of resource whose comments to list, such as
                :py:attr:`~roboto.domain.comments.CommentEntityType.Dataset` for every comment on a dataset.
            owner_org_id: Organization that owns the comments. Defaults to the organization the caller acts in.
            page_token: Token from a previous page's response that resumes the listing after it. ``None`` starts at the
                first page.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            ``(comments, next_token)``: the page's comments and the token for the next page. Pass ``next_token`` as
            ``page_token`` to fetch the next page; it is ``None`` on the last page.

        Examples:
            List the first page of comments on datasets:

            >>> page, next_token = Comment.for_entity_type(entity_type=CommentEntityType.Dataset)

            List the first page of comments on invocations, naming the organization:

            >>> page, next_token = Comment.for_entity_type(
            ...     entity_type=CommentEntityType.Invocation, owner_org_id="og_12345"
            ... )
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = page_token

        response_page = roboto_client.get(
            f"v1/comments/type/{entity_type}",
            query=query_params,
            owner_org_id=owner_org_id,
        ).to_paginated_list(CommentRecord)

        return [cls(record, roboto_client) for record in response_page.items], response_page.next_token

    @classmethod
    def for_user(
        cls,
        user_id: str,
        owner_org_id: typing.Optional[str] = None,
        page_token: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> tuple[collections.abc.Sequence["Comment"], typing.Optional[str]]:
        """List one page of the comments a user wrote in an organization, newest first.

        Each page holds up to 100 comments.

        Comments on an entity the caller may not read are left out of the
        page they fall on, so a page can hold fewer comments than usual, or
        none, and still return a pagination token. Keep requesting pages until
        the token is None.

        Args:
            user_id: ID of the user whose comments to list, which for a person is their email address.
            owner_org_id: Organization whose comments to list. Defaults to the organization the caller acts in.
            page_token: Token from a previous page's response that resumes the listing after it. ``None`` starts at the
                first page.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            ``(comments, next_token)``: the page's comments and the token for the next page. Pass ``next_token`` as
            ``page_token`` to fetch the next page; it is ``None`` on the last page.

        Examples:
            List the first page of a user's comments:

            >>> page, next_token = Comment.for_user(user_id="alex@example.com")

            List the first page of a user's comments, naming the organization:

            >>> page, next_token = Comment.for_user(user_id="sam@example.com", owner_org_id="og_12345")
        """
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

        return [cls(record, roboto_client) for record in response_page.items], response_page.next_token

    @classmethod
    def recent_for_org(
        cls,
        owner_org_id: typing.Optional[str] = None,
        page_token: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> tuple[collections.abc.Sequence["Comment"], typing.Optional[str]]:
        """List one page of an organization's comments on every kind of resource, newest first.

        Comments are ordered by the time they were created; editing a comment does not move it. Each page holds up to
        100 comments.

        Comments on an entity the caller may not read are left out of the
        page they fall on, so a page can hold fewer comments than usual, or
        none, and still return a pagination token. Keep requesting pages until
        the token is None.

        Args:
            owner_org_id: Organization that owns the comments. Defaults to the organization the caller acts in.
            page_token: Token from a previous page's response that resumes the listing after it. ``None`` starts at the
                first page.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment, by
                :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            ``(comments, next_token)``: the page's comments and the token for the next page. Pass ``next_token`` as
            ``page_token`` to fetch the next page; it is ``None`` on the last page.

        Examples:
            Print the organization's most recent comment:

            >>> page, next_token = Comment.recent_for_org()
            >>> if page:
            ...     print(page[0].record.comment_text)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        query_params: dict[str, typing.Any] = {}
        if page_token:
            query_params["page_token"] = page_token

        response_page = roboto_client.get(
            "v1/comments/recent", query=query_params, owner_org_id=owner_org_id
        ).to_paginated_list(CommentRecord)

        return [cls(record, roboto_client) for record in response_page.items], response_page.next_token

    def __init__(self, record: CommentRecord, roboto_client: typing.Optional[RobotoClient] = None) -> None:
        self.__roboto_client = RobotoClient.defaulted(roboto_client)
        self.__record = record

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def comment_id(self) -> str:
        """Unique ID of the comment, beginning with ``cm_``."""
        return self.__record.comment_id

    @property
    def created(self) -> datetime.datetime:
        """Time the comment was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """ID of the user who wrote the comment."""
        return self.__record.created_by

    @property
    def modified(self) -> datetime.datetime:
        """Time the comment was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """ID of the user who wrote the comment.

        :py:attr:`~roboto.domain.comments.CommentRecord.modified_by` describes how Roboto sets it.
        """
        return self.__record.modified_by

    @property
    def record(self) -> CommentRecord:
        """Record of the comment that this instance holds.

        ``update_comment`` replaces it with the edited one.
        """
        return self.__record

    def delete_comment(self) -> None:
        """Delete the comment. This cannot be undone.

        Only the comment's author or a Roboto administrator can delete it. Deleting a comment that no longer exists
        succeeds and changes nothing.

        Raises:
            RobotoUnauthorizedException: The caller may not delete the comment.

        Examples:
            >>> comment = Comment.from_id("cm_12345")
            >>> comment.delete_comment()
        """
        self.__roboto_client.delete(f"/v1/comments/{self.comment_id}")

    def update_comment(self, comment_text: str) -> "Comment":
        """Replace the comment's text.

        Only the comment's author or a Roboto administrator can edit it. Roboto rereads the mentions from the new text
        and notifies only the users the previous text did not mention.

        Args:
            comment_text: New text of the comment, with mentions written ``@[<display_name>](<user_id>)``.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoNotFoundException: The comment has been deleted.
            RobotoUnauthorizedException: The caller may not edit the comment, or ``comment_text`` newly mentions a
                user outside the organization. In the second case Roboto has already saved the new text.

        Examples:
            Replace the text:

            >>> comment = Comment.from_id("cm_12345")
            >>> updated = comment.update_comment("Updated text content")
            >>> print(updated.record.comment_text)
            Updated text content

            Mention a user in the new text, which notifies them:

            >>> comment.update_comment("@[Sam Lee](sam@example.com) please check this")
        """
        self.__record = self.__roboto_client.put(
            f"/v1/comments/{self.comment_id}",
            data=UpdateCommentRequest(
                comment_text=comment_text,
            ),
        ).to_record(CommentRecord)

        return self
