# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import collections.abc
import time
import typing
from typing import Optional, Union

from ...http import RobotoClient
from ..core import RobotoLLMContext
from .event import (
    ChatEvent,
    ChatStartTextEvent,
    ChatTextDeltaEvent,
    ChatTextEndEvent,
    ChatToolResultEvent,
    ChatToolUseEvent,
)
from .record import (
    ChatMessage,
    ChatRecord,
    ChatRecordDelta,
    ChatRole,
    ChatStatus,
    ChatTextContent,
    ChatToolResultContent,
    ChatToolUseContent,
    SendMessageRequest,
    StartChatRequest,
)


class Chat:
    """An interactive AI chat session within the Roboto platform.

    A Chat represents a conversational interface with Roboto's AI assistant, enabling
    users to ask questions, request data analysis, and interact with their robotics
    data through natural language. Chat sessions maintain conversation history and
    support streaming responses for real-time interaction.

    Chat sessions are stateful and persistent, allowing users to continue conversations
    across multiple interactions. Each chat maintains a sequence of messages between
    the user, AI assistant, and Roboto system, with support for tool usage and
    structured responses.

    The Chat class provides methods for starting new conversations, sending messages,
    streaming responses, and managing conversation state. It integrates with Roboto's
    broader ecosystem to provide contextual assistance with data analysis, platform
    navigation, and robotics workflows.
    """

    @classmethod
    def from_id(
        cls,
        chat_id: str,
        roboto_client: Optional[RobotoClient] = None,
        load_messages: bool = True,
    ) -> Chat:
        """Retrieve an existing chat session by its unique identifier.

        Loads a previously created chat session from the Roboto platform, allowing
        users to resume conversations and access message history. This method is
        useful for continuing interrupted conversations or accessing chat sessions
        from different contexts.

        Args:
            chat_id: Unique identifier for the chat session.
            roboto_client: HTTP client for API communication. If None, uses the default client.
            load_messages: Whether to load the chat's messages. If False, the chat's messages will be empty.

        Returns:
            Chat instance representing the existing chat session.

        Raises:
            RobotoNotFoundException: If the chat session does not exist.
            RobotoUnauthorizedException: If the caller lacks permission to access the chat.

        Examples:
            Resume an existing chat session:

            >>> chat = Chat.from_id("chat_abc123")
            >>> print(f"Chat has {len(chat.messages)} messages")
            Chat has 5 messages

            Resume a chat and continue the conversation:

            >>> chat = Chat.from_id("chat_abc123")
            >>> chat.send_text("What was my previous question?")
            >>> for text in chat.stream():
            ...     print(text, end="", flush=True)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        query_params = {"load_messages": load_messages}
        record = roboto_client.get(f"v1/ai/chats/{chat_id}", query=query_params).to_record(ChatRecord)

        return Chat(record=record, roboto_client=roboto_client)

    @classmethod
    def start(
        cls,
        message: Union[str, ChatMessage, collections.abc.Sequence[ChatMessage]],
        context: Optional[RobotoLLMContext] = None,
        system_prompt: Optional[str] = None,
        org_id: Optional[str] = None,
        roboto_client: Optional[RobotoClient] = None,
    ) -> Chat:
        """Start a new chat session with an initial message.

        Creates a new chat session and sends the initial message to begin the conversation.
        The AI assistant will process the message and generate a response, which can be
        retrieved using streaming or polling methods, or :py:meth:`await_user_turn()`.

        Args:
            message: Initial message to start the conversation. Can be a simple text string,
                a structured ChatMessage object, or a sequence of ChatMessage objects for
                multi-turn initialization.
            system_prompt: Optional system prompt to customize the AI assistant's behavior
                and context for this conversation.
            org_id: Organization ID to create the chat in. If None, uses the caller's
                default organization.
            roboto_client: HTTP client for API communication. If None, uses the default client.

        Returns:
            Chat instance representing the newly created chat session.

        Raises:
            RobotoInvalidRequestException: If the message format is invalid.
            RobotoUnauthorizedException: If the caller lacks permission to create chats.

        Examples:
            Start a simple chat with a text message:

            >>> chat = Chat.start("What datasets do I have access to?")
            >>> for text in chat.stream():
            ...     print(text, end="", flush=True)

        """
        roboto_client = RobotoClient.defaulted(roboto_client)

        if isinstance(message, ChatMessage):
            messages = [message]
        elif isinstance(message, str):
            messages = [ChatMessage.text(text=message, role=ChatRole.USER)]
        else:
            messages = list(message)

        request = StartChatRequest(
            context=context,
            messages=list(messages),
            system_prompt=system_prompt,
        )

        record = roboto_client.post("v1/ai/chats", caller_org_id=org_id, data=request).to_record(ChatRecord)

        return Chat(
            record=record,
            roboto_client=roboto_client,
        )

    def __init__(self, record: ChatRecord, roboto_client: Optional[RobotoClient] = None):
        """Initialize a Chat instance with a chat record.

        Note:
            This constructor is intended for internal use. Users should create Chat
            instances using :py:meth:`Chat.start` or :py:meth:`Chat.from_id` instead.

        Args:
            record: ChatRecord containing the chat session data.
            roboto_client: HTTP client for API communication. If None, uses the default client.
        """
        self.__record: ChatRecord = record
        self.__roboto_client: RobotoClient = RobotoClient.defaulted(roboto_client)

    @property
    def chat_id(self) -> str:
        """Unique identifier for this chat session."""
        return self.__record.chat_id

    @property
    def latest_message(self) -> Optional[ChatMessage]:
        """The most recent message in the conversation, or None if no messages exist."""
        if len(self.__record.messages) == 0:
            return None
        return self.__record.messages[-1]

    @property
    def messages(self) -> list[ChatMessage]:
        """Complete list of messages in the conversation in chronological order."""
        return self.__record.messages

    @property
    def status(self) -> ChatStatus:
        """Current status of the chat session."""
        return self.__record.status

    @property
    def transcript(self) -> str:
        """Human-readable transcript of the entire conversation.

        Returns a formatted string containing all messages in the conversation,
        with role indicators and message content clearly separated.
        """
        return f"=== {self.__record.chat_id} ===\n" + "\n".join(str(message) for message in self.messages)

    def __get_delta_and_update(self) -> ChatRecordDelta:
        delta = self.__roboto_client.get(
            f"v1/ai/chats/{self.__record.chat_id}/delta",
            query={"next_token": self.__record.continuation_token},
        ).to_record(ChatRecordDelta)

        self.__record.continuation_token = delta.continuation_token

        for idx in sorted(delta.messages_by_idx.keys()):
            if idx < len(self.__record.messages):
                self.__record.messages[idx].status = delta.messages_by_idx[idx].status
                self.__record.messages[idx].content.extend(delta.messages_by_idx[idx].content)
            else:
                self.__record.messages.append(delta.messages_by_idx[idx])

        if delta.status is not None:
            self.__record.status = delta.status

        return delta

    def await_user_turn(self, tick: float = 0.2, timeout: Optional[float] = None) -> Chat:
        """Wait for the conversation to reach a state where user input is expected.

        Polls the chat session until the AI assistant has finished generating its response
        and is ready for the next user message. This method is useful for synchronous
        interaction patterns where you need to wait for the assistant to complete before
        proceeding.

        Args:
            tick: Polling interval in seconds between status checks.
            timeout: Maximum time to wait in seconds. If None, waits indefinitely.

        Returns:
            Self for method chaining.

        Raises:
            TimeoutError: If the timeout is reached before the user turn is ready.

        Examples:
            Wait for the assistant to finish responding:

            >>> chat = Chat.start("Analyze my latest dataset")
            >>> chat.await_user_turn(timeout=30.0)
            >>> chat.send_text("What were the key findings?")

            Wait for the assistant to finish responding, as a one-liner:

            >>> chat = Chat.start("Analyze my latest dataset").await_user_turn()
            >>> chat.send_text("What were the key findings?").await_user_turn()

            Use in a synchronous conversation loop:

            >>> chat = Chat.start("Hello")
            >>> while True:
            ...     chat.await_user_turn()
            ...     user_input = input("You: ")
            ...     if user_input.lower() == "quit":
            ...         break
            ...     chat.send_text(user_input)
        """
        start_time = time.time()

        while not self.is_user_turn():
            if timeout is not None and time.time() - start_time > timeout:
                raise TimeoutError("Timeout waiting for user turn")
            self.__get_delta_and_update()
            time.sleep(tick)

        return self

    def is_user_turn(self) -> bool:
        """Check if the conversation is ready for user input.

        Determines whether the AI assistant has finished generating its response and
        is waiting for the next user message. This is true when the latest message
        is a completed text response from the assistant.

        Returns:
            True if it's the user's turn to send a message, False otherwise.

        Examples:
            Check conversation state before sending a message:

            >>> chat = Chat.start("Hello")
            >>> if chat.is_user_turn():
            ...     chat.send_text("How are you?")
            ... else:
            ...     print("Assistant is still responding...")

            Use in a polling loop (which you'd more typically use await_user_turn() for):

            >>> chat = Chat.start("Analyze my data")
            >>> while not chat.is_user_turn():
            ...     time.sleep(0.1)
            >>> print("Assistant finished responding")
        """
        return self.status == ChatStatus.USER_TURN

    def refresh(self) -> Chat:
        """Update the chat session with the latest messages and status.

        Fetches any new messages or updates from the server and updates the local chat state.

        Returns:
            Self for method chaining.

        Examples:
            Manually refresh chat state:

            >>> chat = Chat.from_id("chat_abc123", load_messages=False)
            >>> print(f"Chat has {len(chat.messages)} messages")
            >>> chat.refresh()
            >>> print(f"Chat now has {len(chat.messages)} messages")
        """
        self.__get_delta_and_update()
        return self

    def send(self, message: ChatMessage, context: typing.Optional[RobotoLLMContext] = None) -> Chat:
        """Send a structured message to the chat session.

        Sends a ChatMessage object to the conversation. The message will be processed by the AI assistant, and a
        response will be generated.

        Args:
            message: ChatMessage object containing the message content and metadata.
            context: Optional context to include with the message.

        Returns:
            Self for method chaining.

        Raises:
            RobotoInvalidRequestException: If the message format is invalid.
            RobotoUnauthorizedException: If the caller lacks permission to send messages.

        Examples:
            Send a structured message:

            >>> from roboto.ai.chat import ChatMessage, ChatRole
            >>> message = ChatMessage.text("What's in my latest dataset?", ChatRole.USER)
            >>> chat.send(message)
            >>> for text in chat.stream():
            ...     print(text, end="", flush=True)
        """
        request = SendMessageRequest(message=message, context=context)

        self.__roboto_client.post(
            f"v1/ai/chats/{self.__record.chat_id}/messages",
            data=request,
        )

        self.__record.messages.append(message)
        return self

    def send_text(self, text: str, context: typing.Optional[RobotoLLMContext] = None) -> Chat:
        """Send a text message to the chat session.

        Convenience method for sending a simple text message without needing to construct a ChatMessage object. The
        text will be sent as a user message and processed by the AI assistant.

        Args:
            text: Text content to send to the assistant.
            context: Optional context to include with the message.

        Returns:
            Self for method chaining.

        Raises:
            RobotoInvalidRequestException: If the text is empty or invalid.
            RobotoUnauthorizedException: If the caller lacks permission to send messages.

        Examples:
            Send a simple text message:

            >>> chat = Chat.start("Hello")
            >>> chat.await_user_turn()
            >>> chat.send_text("What datasets do I have access to?")
            >>> for response in chat.stream():
            ...     print(response, end="", flush=True)
        """
        return self.send(ChatMessage.text(text=text, role=ChatRole.USER), context=context)

    def stream_events(
        self,
        tick: float = 0.2,
        timeout: Optional[float] = None,
    ) -> collections.abc.Generator[ChatEvent, None, None]:
        """Stream events from the chat session in real-time.

        Continuously polls the chat session and yields ChatRecordDelta objects as they become available. This provides
        a real-time streaming experience which allows you to get partial content as it is generated by potentially
        long-running conversational AI processing.

        Args:
            tick: Polling interval in seconds between checks for new content.
            timeout: Maximum time to wait in seconds. If None, waits indefinitely.

        Yields:
            ChatRecordDelta objects containing new messages and updates as they become available.

        Examples:
            Stream events and print them in real-time:

            >>> chat = Chat.start("Hello")
            >>> for delta in chat.stream_events():
            ...     for idx in sorted(delta.messages_by_idx.keys()):
            ...         print(f"Message {idx}: {delta.messages_by_idx[idx]}")
        """
        start_time = time.time()

        text_in_progress = False

        while True:
            delta = self.__get_delta_and_update()

            for idx in sorted(delta.messages_by_idx.keys()):
                message = delta.messages_by_idx[idx]
                if message.role == ChatRole.USER:
                    continue
                for content in message.content:
                    if isinstance(content, ChatTextContent):
                        if not text_in_progress:
                            yield ChatStartTextEvent()
                            text_in_progress = True

                        yield ChatTextDeltaEvent(text=content.text)
                    else:
                        if text_in_progress:
                            yield ChatTextEndEvent()
                            text_in_progress = False

                    if isinstance(content, ChatToolUseContent):
                        yield ChatToolUseEvent(name=content.tool_name, tool_use_id=content.tool_use_id)
                    elif isinstance(content, ChatToolResultContent):
                        tool_use_id = content.tool_use_id
                        tool_name = content.tool_name
                        yield ChatToolResultEvent(
                            name=tool_name,
                            tool_use_id=tool_use_id,
                            success=content.status == "success",
                        )

            if self.is_user_turn():
                if text_in_progress:
                    yield ChatTextEndEvent()
                return

            if timeout is not None and time.time() - start_time > timeout:
                raise TimeoutError("Timeout waiting for results to complete streaming")
            time.sleep(tick)

    def stream(self, tick: float = 0.2, timeout: Optional[float] = None) -> collections.abc.Generator[str, None, None]:
        """Stream the AI assistant's response in real-time.

        Continuously polls the chat session and yields text content as it becomes available from the AI assistant.
        This provides a real-time streaming experience which allows you to get partial content as it is generated
        by potentially long-running conversational AI processing.

        The generator will continue yielding text until the assistant completes its
        response and the conversation reaches a user turn state.

        Args:
            tick: Polling interval in seconds between checks for new content.
            timeout: Maximum time to wait in seconds. If None, waits indefinitely.

        Yields:
            Text content from the AI assistant's response as it becomes available.

        Raises:
            TimeoutError: If the timeout is reached before the response completes.

        Examples:
            Stream a response and print it in real-time:

            >>> chat = Chat.start("Explain machine learning")
            >>> for text in chat.stream():
            ...     print(text, end="", flush=True)
            >>> print()  # New line after streaming completes

            Stream with timeout and error handling:

            >>> try:
            ...     for text in chat.stream(timeout=30.0):
            ...         print(text, end="", flush=True)
            ... except TimeoutError:
            ...     print("Response timed out")

        """
        start_time = time.time()

        while True:
            delta = self.__get_delta_and_update()

            for idx in sorted(delta.messages_by_idx.keys()):
                if delta.messages_by_idx[idx].role == ChatRole.USER:
                    continue

                for content in delta.messages_by_idx[idx].content:
                    if isinstance(content, ChatTextContent):
                        yield content.text

            if self.is_user_turn():
                return

            if timeout is not None and time.time() - start_time > timeout:
                raise TimeoutError("Timeout waiting for results to complete streaming")
            time.sleep(tick)
