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
    """A comment attached to a Roboto platform entity.

    Comments provide a way to add contextual information, feedback, or discussion
    to various Roboto platform resources including datasets, files, actions,
    invocations, triggers, and collections. Comments support `@mention` syntax
    using the format ``@[display_name](user_id)`` to notify specific users.

    Comments are created through the :py:meth:`create` class method and cannot
    be instantiated directly. They can be retrieved by entity, entity type,
    user, or organization using the various class methods provided.

    Each comment tracks creation and modification metadata, including timestamps
    and user information. Comments can be updated or deleted by authorized users.

    Note:
        Comments cannot be instantiated directly through the constructor.
        Use :py:meth:`create` to create new comments or the various retrieval
        methods to access existing comments.
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
        """Create a new comment on a Roboto platform entity.

        Creates a comment attached to the specified entity. The comment text
        can include `@mention` syntax to notify users using the format
        ``@[display_name](user_id)``.

        Args:
            comment_text: The text content of the comment. May include `@mention`
                syntax to notify users.
            entity_id: Unique identifier of the entity to attach the comment to.
            entity_type: Type of entity being commented on.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.
            caller_org_id: Optional organization ID of the caller. If not provided,
                uses the organization from the client context.

        Returns:
            A new Comment instance representing the created comment.

        Raises:
            RobotoUnauthorizedException: If the user lacks permission to comment
                on the specified entity.
            RobotoNotFoundException: If the specified entity does not exist.
            RobotoIllegalArgumentException: If the provided arguments are invalid.

        Examples:
            >>> from roboto.domain import comments
            >>> # Create a comment on a dataset
            >>> comment = comments.Comment.create(
            ...     comment_text="This dataset looks good!",
            ...     entity_id="ds_1234567890abcdef",
            ...     entity_type=comments.CommentEntityType.Dataset
            ... )
            >>> print(comment.comment_id)
            cm_abcdef1234567890

            >>> # Create a comment with user mentions
            >>> comment = comments.Comment.create(
            ...     comment_text="@[John Doe](john.doe@example.com) please review this",
            ...     entity_id="fl_9876543210fedcba",
            ...     entity_type=comments.CommentEntityType.File
            ... )
        """
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
        """Retrieve a comment by its unique identifier.

        Fetches a specific comment using its comment ID. The caller must have
        permission to access the comment and its associated entity.

        Args:
            comment_id: Unique identifier of the comment to retrieve.
            owner_org_id: Optional organization ID that owns the comment.
                If not provided, uses the organization from the client context.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            A Comment instance representing the retrieved comment.

        Raises:
            RobotoNotFoundException: If the comment does not exist or the caller
                lacks permission to access it.
            RobotoUnauthorizedException: If the user lacks permission to access
                the comment.

        Examples:
            >>> from roboto.domain import comments
            >>> # Retrieve a specific comment
            >>> comment = comments.Comment.from_id("cm_1234567890abcdef")
            >>> print(comment.record.comment_text)
            This is the comment text

            >>> # Retrieve a comment from a specific organization
            >>> comment = comments.Comment.from_id(
            ...     comment_id="cm_abcdef1234567890",
            ...     owner_org_id="og_fedcba0987654321"
            ... )
        """
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
        """Retrieve all comments for a specific entity.

        Fetches all comments attached to a particular entity, such as a dataset,
        file, action, invocation, trigger, or collection. Results are paginated
        and returned in chronological order.

        Args:
            entity_type: Type of entity to retrieve comments for.
            entity_id: Unique identifier of the entity.
            owner_org_id: Optional organization ID that owns the entity.
                If not provided, uses the organization from the client context.
            page_token: Optional pagination token to retrieve the next page
                of results. Use None to start from the beginning.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            A tuple containing:
                - A sequence of Comment instances for the entity
                - An optional pagination token for the next page, or None if
                  no more pages are available

        Raises:
            RobotoNotFoundException: If the entity does not exist.
            RobotoUnauthorizedException: If the user lacks permission to access
                the entity or its comments.

        Examples:
            >>> from roboto.domain import comments
            >>> # Get all comments for a dataset
            >>> comments_list, next_token = comments.Comment.for_entity(
            ...     entity_type=comments.CommentEntityType.Dataset,
            ...     entity_id="ds_1234567890abcdef"
            ... )
            >>> print(f"Found {len(comments_list)} comments")
            Found 5 comments

            >>> # Paginate through comments
            >>> all_comments = []
            >>> page_token = None
            >>> while True:
            ...     comments_page, page_token = comments.Comment.for_entity(
            ...         entity_type=comments.CommentEntityType.File,
            ...         entity_id="fl_9876543210fedcba",
            ...         page_token=page_token
            ...     )
            ...     all_comments.extend(comments_page)
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
        """Retrieve all comments for a specific entity type.

        Fetches all comments attached to entities of a particular type within
        an organization. For example, retrieve all comments on datasets or
        all comments on files. Results are paginated and returned in
        chronological order.

        Args:
            entity_type: Type of entities to retrieve comments for.
            owner_org_id: Optional organization ID to scope the search to.
                If not provided, uses the organization from the client context.
            page_token: Optional pagination token to retrieve the next page
                of results. Use None to start from the beginning.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            A tuple containing:
                - A sequence of Comment instances for the entity type
                - An optional pagination token for the next page, or None if
                  no more pages are available

        Raises:
            RobotoUnauthorizedException: If the user lacks permission to access
                comments for the specified entity type.

        Examples:
            >>> from roboto.domain import comments
            >>> # Get all comments on datasets in the organization
            >>> dataset_comments, next_token = comments.Comment.for_entity_type(
            ...     entity_type=comments.CommentEntityType.Dataset
            ... )
            >>> print(f"Found {len(dataset_comments)} dataset comments")
            Found 12 dataset comments

            >>> # Get all comments on action invocations
            >>> invocation_comments, _ = comments.Comment.for_entity_type(
            ...     entity_type=comments.CommentEntityType.Invocation,
            ...     owner_org_id="og_1234567890abcdef"
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
        """Retrieve all comments created by a specific user.

        Fetches all comments authored by the specified user within an organization.
        Results are paginated and returned in chronological order.

        Args:
            user_id: Unique identifier of the user whose comments to retrieve.
            owner_org_id: Optional organization ID to scope the search to.
                If not provided, uses the organization from the client context.
            page_token: Optional pagination token to retrieve the next page
                of results. Use None to start from the beginning.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            A tuple containing:
                - A sequence of Comment instances created by the user
                - An optional pagination token for the next page, or None if
                  no more pages are available

        Raises:
            RobotoUnauthorizedException: If the user lacks permission to access
                comments by the specified user.

        Examples:
            >>> from roboto.domain import comments
            >>> # Get all comments by a specific user
            >>> user_comments, next_token = comments.Comment.for_user(
            ...     user_id="john.doe@example.com"
            ... )
            >>> print(f"User has created {len(user_comments)} comments")
            User has created 8 comments

            >>> # Get comments by user in a specific organization
            >>> org_user_comments, _ = comments.Comment.for_user(
            ...     user_id="jane.smith@example.com",
            ...     owner_org_id="og_1234567890abcdef"
            ... )
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
        """Retrieve recent comments for an organization.

        Fetches the most recently created or modified comments within an
        organization, across all entity types. Results are paginated and
        returned in reverse chronological order (most recent first).

        Args:
            owner_org_id: Optional organization ID to retrieve comments for.
                If not provided, uses the organization from the client context.
            page_token: Optional pagination token to retrieve the next page
                of results. Use None to start from the beginning.
            roboto_client: Optional Roboto client instance. If not provided,
                uses the default client.

        Returns:
            A tuple containing:
                - A sequence of Comment instances ordered by recency
                - An optional pagination token for the next page, or None if
                  no more pages are available

        Raises:
            RobotoUnauthorizedException: If the user lacks permission to access
                comments in the organization.

        Examples:
            >>> from roboto.domain import comments
            >>> # Get recent comments in the organization
            >>> recent_comments, next_token = comments.Comment.recent_for_org()
            >>> print(f"Found {len(recent_comments)} recent comments")
            Found 10 recent comments

            >>> # Get recent comments for a specific organization
            >>> org_comments, _ = comments.Comment.recent_for_org(
            ...     owner_org_id="og_1234567890abcdef"
            ... )
            >>> if org_comments:
            ...     print(f"Most recent comment: {org_comments[0].record.comment_text}")
        """
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
        """Unique identifier for this comment."""
        return self.__record.comment_id

    @property
    def created(self) -> datetime.datetime:
        """Timestamp when the comment was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """User ID of the comment author."""
        return self.__record.created_by

    @property
    def modified(self) -> datetime.datetime:
        """Timestamp when the comment was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """User ID of the user who last modified this comment."""
        return self.__record.modified_by

    @property
    def record(self) -> CommentRecord:
        """The underlying CommentRecord data structure."""
        return self.__record

    def delete_comment(self) -> None:
        """Delete this comment permanently.

        Removes the comment from the platform. This action cannot be undone.
        Only the comment author or users with appropriate permissions can
        delete a comment.

        Raises:
            RobotoUnauthorizedException: If the user lacks permission to delete
                this comment.
            RobotoNotFoundException: If the comment no longer exists.

        Examples:
            >>> from roboto.domain import comments
            >>> comment = comments.Comment.from_id("cm_1234567890abcdef")
            >>> comment.delete_comment()
            # Comment is now permanently deleted
        """
        self.__roboto_client.delete(f"/v1/comments/{self.comment_id}")

    def update_comment(self, comment_text: str) -> "Comment":
        """Update the text content of this comment.

        Modifies the comment text and updates the modification timestamp.
        The updated comment text can include `@mention` syntax to notify users.
        Only the comment author or users with appropriate permissions can
        update a comment.

        Args:
            comment_text: New text content for the comment. May include
                `@mention` syntax to notify users.

        Returns:
            This Comment instance with updated content.

        Raises:
            RobotoUnauthorizedException: If the user lacks permission to update
                this comment.
            RobotoNotFoundException: If the comment no longer exists.
            RobotoIllegalArgumentException: If the comment text is invalid.

        Examples:
            >>> from roboto.domain import comments
            >>> comment = comments.Comment.from_id("cm_1234567890abcdef")
            >>> updated_comment = comment.update_comment("Updated text content")
            >>> print(updated_comment.record.comment_text)
            Updated text content

            >>> # Update with mentions
            >>> comment.update_comment("@[Jane Doe](jane.doe@example.com) please check this")
        """
        self.__record = self.__roboto_client.put(
            f"/v1/comments/{self.comment_id}",
            data=UpdateCommentRequest(
                comment_text=comment_text,
            ),
        ).to_record(CommentRecord)

        return self
