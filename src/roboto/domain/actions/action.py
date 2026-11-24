# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import typing

from ...exceptions import (
    RobotoIllegalArgumentException,
)
from ...http import RobotoClient
from ...query import QuerySpecification
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
    remove_not_set,
)
from ...updates import MetadataChangeset
from .action_operations import (
    CreateActionRequest,
    SetActionAccessibilityRequest,
    UpdateActionRequest,
)
from .action_record import (
    Accessibility,
    ActionParameter,
    ActionParameterChangeset,
    ActionRecord,
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
)
from .invocation import Invocation
from .invocation_operations import (
    CreateInvocationRequest,
)
from .invocation_record import (
    InvocationDataSource,
    InvocationDataSourceType,
    InvocationInput,
    InvocationRecord,
    InvocationSource,
    InvocationUploadDestination,
)

SHORT_DESCRIPTION_LENGTH = 140
"""Maximum length of an action's short description, in characters."""


class Action:
    """An action: a reusable function to process, transform or analyze data in Roboto.

    An action runs a container image with the compute requirements, container parameters, and timeout it sets, and
    each invocation can give values for its parameters. A user invokes it with ``invoke``, or a trigger invokes it
    automatically; each run is an :py:class:`~roboto.domain.actions.Invocation`. An action belongs to one
    organization, and its accessibility says whether only that organization's members can find and invoke it, or
    every Roboto user can, through the Action Hub.

    Get an ``Action`` from ``create``, ``from_name``, or ``query``. Each instance holds a copy of one version of the
    action's record: methods that change the action update that copy from Roboto's response.
    """

    __record: ActionRecord
    __roboto_client: RobotoClient

    @classmethod
    def create(
        cls,
        name: str,
        compute_requirements: typing.Optional[ComputeRequirements] = None,
        container_parameters: typing.Optional[ContainerParameters] = None,
        description: typing.Optional[str] = None,
        inherits: typing.Optional[ActionReference] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        parameters: typing.Optional[list[ActionParameter]] = None,
        requires_downloaded_inputs: typing.Optional[bool] = None,
        short_description: typing.Optional[str] = None,
        tags: typing.Optional[list[str]] = None,
        timeout: typing.Optional[int] = None,
        uri: typing.Optional[str] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Action":
        """Create an action.

        Args:
            name: Human-readable name of the action, unique within its organization. Letters, digits, underscores,
                and dashes only.
            compute_requirements: CPU, memory, and storage for each invocation of the action. ``None`` uses the
                defaults of :py:class:`~roboto.domain.actions.ComputeRequirements`.
            container_parameters: Command, entry point, environment variables, and working directory for the
                action's container. ``None`` sets none of them.
            description: Human-readable description of the action.
            inherits: Deprecated. Roboto rejects a request that sets it; set the configuration on the action itself.
            metadata: Key-value metadata to set on the action. ``None`` sets none.
            parameters: Parameters an invocation of the action can give values for. ``None`` sets none.
            requires_downloaded_inputs: Whether Roboto downloads an invocation's input files into the action's
                container before it runs. ``None`` means ``True``.
            short_description: Brief human-readable description of the action, at most 140 characters
                (``SHORT_DESCRIPTION_LENGTH``).
            tags: Tags to set on the action. ``None`` sets none.
            timeout: Maximum time, in minutes, an invocation of the action may run before Roboto stops it. ``None``
                uses Roboto's default.
            uri: URI of the container image the action runs, such as ``"ubuntu:latest"``. An action without one
                cannot be invoked.
            caller_org_id: Organization to create the action in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Returns:
            The new action.

        Raises:
            RobotoIllegalArgumentException: ``short_description`` is longer than 140 characters. Raised before any
                request.
            RobotoConflictException: The organization already has an action with this name.
            RobotoInvalidRequestException: ``inherits`` is set, two parameters share a name, or a required
                parameter has a default.
            RobotoLimitExceededException: The organization has as many actions as its plan allows, or ``timeout``
                is above the organization's limit.

        Examples:
            Create an action that runs a public image:

            >>> action = Action.create(
            ...     name="hello_world", uri="ubuntu:latest", description="A simple hello world action"
            ... )

            Create an action with parameters and compute requirements:

            >>> from roboto.domain.actions import ComputeRequirements, ActionParameter
            >>> action = Action.create(
            ...     name="data_processor",
            ...     uri="my-registry.com/processor:v1.0",
            ...     description="Processes sensor data with configurable parameters",
            ...     compute_requirements=ComputeRequirements(vCPU=4096, memory=8192),
            ...     parameters=[
            ...         ActionParameter(name="threshold", required=True, description="Processing threshold"),
            ...         ActionParameter(name="output_format", default="json", description="Output format"),
            ...     ],
            ...     tags=["data-processing", "sensors"],
            ...     timeout=60,
            ... )
        """
        request = CreateActionRequest(
            compute_requirements=compute_requirements,
            container_parameters=container_parameters,
            description=description,
            inherits=inherits,
            metadata=metadata or {},
            name=name,
            parameters=parameters or [],
            requires_downloaded_inputs=requires_downloaded_inputs,
            short_description=short_description,
            tags=tags or [],
            timeout=timeout,
            uri=uri,
        )

        if (
            is_set(request.short_description)
            and request.short_description is not None
            and len(request.short_description) > SHORT_DESCRIPTION_LENGTH
        ):
            raise RobotoIllegalArgumentException(
                f"Short description exceeds max length of {SHORT_DESCRIPTION_LENGTH} characters"
            )

        roboto_client = RobotoClient.defaulted(roboto_client)

        response = roboto_client.post(
            "v1/actions",
            data=request,
            caller_org_id=caller_org_id,
        )
        record = response.to_record(ActionRecord)
        return cls(record, roboto_client)

    @classmethod
    def from_name(
        cls,
        name: str,
        digest: typing.Optional[str] = None,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> "Action":
        """Fetch an action by name.

        Action names are unique within an organization, so a name and an organization identify one action.

        Args:
            name: Name of the action.
            digest: Digest of the version to fetch. ``None`` fetches the latest version.
            owner_org_id: Organization that owns the action. Defaults to the organization the caller acts in. Name
                another organization to fetch one of its actions in the Action Hub.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Raises:
            RobotoNotFoundException: The organization has no action with this name, or the action has no version
                with this ``digest``.

        Examples:
            Load the latest version of an action:

            >>> action = Action.from_name("data_processor")

            Load a specific version of an action:

            >>> action = Action.from_name("data_processor", digest="abc123def456")

            Load an action in the Action Hub that another organization owns:

            >>> action = Action.from_name("ros_ingestion", owner_org_id="roboto-public")
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        query_params: dict[str, typing.Any] = {}
        if digest:
            query_params["digest"] = digest
        if owner_org_id:
            query_params["owner_org_id"] = owner_org_id
        response = roboto_client.get(
            f"v1/actions/{name}",
            query=query_params or None,
            # Sets X-Roboto-Resource-Owner-Id, the only place older versions of Roboto read the action's owner from.
            owner_org_id=owner_org_id,
        )
        record = response.to_record(ActionRecord)
        return cls(record, roboto_client)

    @classmethod
    def query(
        cls,
        spec: typing.Optional[QuerySpecification] = None,
        accessibility: Accessibility = Accessibility.Organization,
        owner_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> collections.abc.Generator["Action", None, None]:
        """List the actions in an organization, or in the Action Hub, that match a query specification.

        Fetches one page of results at a time as the generator advances, and writes each page's token to
        ``spec.after`` to request the next.

        Args:
            spec: Conditions, sort order, and page size of the query. Each condition's field must be an
                :py:class:`~roboto.domain.actions.ActionRecord` field, or a dotted path that starts with one, such as
                ``metadata.software_version``. ``None`` lists every action.
            accessibility: :py:attr:`~roboto.domain.actions.Accessibility.Organization` lists an organization's
                actions; :py:attr:`~roboto.domain.actions.Accessibility.ActionHub` lists the actions in the Action
                Hub.
            owner_org_id: Organization whose actions to list. Defaults to the organization the caller acts in.
                Ignored when ``accessibility`` is ``ActionHub``.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.

        Yields:
            Actions that match ``spec``.

        Raises:
            ValueError: ``spec`` names a field that is not an action record field. It surfaces on the first
                iteration, before any request.

        Examples:
            List every action in the organization:

            >>> for action in Action.query():
            ...     print(action.name)

            List the actions in the Action Hub whose names contain ``ros``:

            >>> from roboto.domain.actions import Accessibility
            >>> from roboto.query import Comparator, Condition, QuerySpecification
            >>> spec = QuerySpecification(
            ...     condition=Condition(field="name", comparator=Comparator.Contains, value="ros")
            ... )
            >>> for action in Action.query(spec, accessibility=Accessibility.ActionHub):
            ...     print(action.name)
        """
        roboto_client = RobotoClient.defaulted(roboto_client)
        spec = spec or QuerySpecification()

        known = set(ActionRecord.model_fields.keys())
        actual = set()
        for field in spec.fields():
            # A dotted field such as "metadata.SoftwareVersion" is checked by its first segment.
            if "." in field:
                actual.add(field.split(".")[0])
            else:
                actual.add(field)
        unknown = actual - known
        if unknown:
            plural = len(unknown) > 1
            msg = "are not known attributes of Action" if plural else "is not a known attribute of Action"
            raise ValueError(f"{unknown} {msg}. Known attributes: {known}")

        url_path = "v1/actions/query" if accessibility == Accessibility.Organization else "v1/actions/query/actionhub"

        while True:
            response = roboto_client.post(
                url_path,
                data=spec,
                idempotent=True,
                owner_org_id=owner_org_id,
            )
            paginated_results = response.to_paginated_list(ActionRecord)
            for record in paginated_results.items:
                yield cls(record, roboto_client)
            if paginated_results.next_token:
                spec.after = paginated_results.next_token
            else:
                break

    def __init__(
        self,
        record: ActionRecord,
        roboto_client: typing.Optional[RobotoClient] = None,
    ) -> None:
        self.__record = record
        self.__roboto_client = RobotoClient.defaulted(roboto_client)

    def __repr__(self) -> str:
        return self.__record.model_dump_json()

    @property
    def accessibility(self) -> Accessibility:
        """Who can find and invoke the action."""
        return self.__record.accessibility

    @property
    def compute_requirements(self) -> typing.Optional[ComputeRequirements]:
        """CPU, memory and storage for each invocation of the action, or ``None`` if none were set.

        :py:attr:`~roboto.domain.actions.ActionRecord.compute_requirements` says what can override them.
        """
        return self.__record.compute_requirements

    @property
    def container_parameters(self) -> typing.Optional[ContainerParameters]:
        """How to run the action's container image.

        :py:attr:`~roboto.domain.actions.ActionRecord.container_parameters` says what can override them.
        """
        return self.__record.container_parameters

    @property
    def created(self) -> datetime.datetime:
        """Time the action was created."""
        return self.__record.created

    @property
    def created_by(self) -> str:
        """ID of the user who created the action."""
        return self.__record.created_by

    @property
    def description(self) -> typing.Optional[str]:
        """Human-readable description of the action, or ``None`` if it has none."""
        return self.__record.description

    @property
    def digest(self) -> str:
        """Digest that identifies this version of the action.

        :py:attr:`~roboto.domain.actions.ActionRecord.digest` says where it comes from when the record has none.
        """
        return self.__record.digest if self.__record.digest else self.__record.compute_digest()

    @property
    def inherits_from(self) -> typing.Optional[ActionReference]:
        """Deprecated. Action this action inherits its configuration from.

        Read the configuration from the action's own properties, such as ``compute_requirements`` and ``uri``, instead.
        :py:attr:`~roboto.domain.actions.ActionRecord.inherits` says when Roboto rejects it.
        """
        return self.__record.inherits

    @property
    def metadata(self) -> dict[str, typing.Any]:
        """Key-value metadata on the action.

        :py:attr:`~roboto.domain.actions.ActionRecord.metadata` says which values it may hold.
        """
        return self.__record.metadata

    @property
    def modified(self) -> datetime.datetime:
        """Time the action was last modified."""
        return self.__record.modified

    @property
    def modified_by(self) -> str:
        """ID of the user who last modified the action."""
        return self.__record.modified_by

    @property
    def name(self) -> str:
        """Human-readable name of the action, unique within its organization."""
        return self.__record.name

    @property
    def org_id(self) -> str:
        """ID of the organization that owns the action."""
        return self.__record.org_id

    @property
    def parameters(self) -> collections.abc.Sequence[ActionParameter]:
        """Copies of the parameters that an invocation of the action can give values for."""
        return [param.model_copy() for param in self.__record.parameters]

    @property
    def published(self) -> typing.Optional[datetime.datetime]:
        """Time the action was published to the Action Hub, or ``None`` if it is not in the Action Hub."""
        return self.__record.published

    @property
    def record(self) -> ActionRecord:
        """Record of the action that this instance holds."""
        return self.__record

    @property
    def requires_downloaded_inputs(self) -> bool:
        """Whether Roboto downloads an invocation's input files before the action runs.

        ``True`` unless the action sets it to ``False``.
        """
        return self.__record.requires_downloaded_inputs is not False

    @property
    def short_description(self) -> typing.Optional[str]:
        """Brief description of the action, or ``None`` if it has none.

        :py:attr:`~roboto.domain.actions.ActionRecord.short_description` gives its maximum length.
        """
        return self.__record.short_description

    @property
    def uri(self) -> typing.Optional[str]:
        """URI of the container image the action runs, or ``None`` if none was set."""
        return self.__record.uri

    @property
    def tags(self) -> list[str]:
        """Tags on the action."""
        return self.__record.tags

    @property
    def timeout(self) -> typing.Optional[int]:
        """Maximum time an invocation of the action may run, in minutes, or ``None`` if the action sets none."""
        return self.__record.timeout

    def delete(self) -> None:
        """Delete this action and every version of it.

        An action in the Action Hub is removed from it first. Deleting an action that no longer exists succeeds
        and changes nothing.

        Examples:
            >>> action = Action.from_name("old_action")
            >>> action.delete()
        """
        self.__roboto_client.delete(
            f"v1/actions/{self.name}",
            owner_org_id=self.org_id,
        )

    def invoke(
        self,
        invocation_source: InvocationSource,
        data_source_id: typing.Optional[str] = None,
        data_source_type: typing.Optional[InvocationDataSourceType] = None,
        input_data: typing.Optional[typing.Union[list[str], InvocationInput]] = None,
        upload_destination: typing.Optional[InvocationUploadDestination] = None,
        compute_requirement_overrides: typing.Optional[ComputeRequirements] = None,
        container_parameter_overrides: typing.Optional[ContainerParameters] = None,
        idempotency_id: typing.Optional[str] = None,
        invocation_source_id: typing.Optional[str] = None,
        parameter_values: typing.Optional[dict[str, typing.Any]] = None,
        timeout: typing.Optional[int] = None,
        caller_org_id: typing.Optional[str] = None,
    ) -> Invocation:
        """Start a run of the version of this action this instance holds.

        The invocation is queued to run in the caller's organization, which may differ from the organization that
        owns the action when the action is in the Action Hub.

        Args:
            invocation_source: Whether a user or a trigger starts the invocation. Only Roboto can create invocations
                with source :py:attr:`~roboto.domain.actions.InvocationSource.Trigger`.
            data_source_id: ID of the dataset the invocation reads from. Required when ``input_data`` is a list of
                patterns. ``None`` names no data source.
            data_source_type: Type of the data source that ``data_source_id`` names.
                :py:attr:`~roboto.domain.actions.InvocationDataSourceType.Dataset` is the only type, and ``None``
                uses it.
            input_data: Gitignore-style patterns for the files in the ``data_source_id`` dataset to read, or an
                :py:class:`~roboto.domain.actions.InvocationInput` that selects files, topics, or sessions. ``None``
                or an empty list selects no inputs.
            upload_destination: Dataset to upload the files the invocation writes to its output directory to.
                ``None`` uploads them to the dataset the invocation's input files and topics come from when they all
                come from one, and otherwise not at all.
            compute_requirement_overrides: Compute requirements, such as vCPU and memory, that replace the action's
                own. Fields left unset keep the action's values; ``None`` keeps them all.
            container_parameter_overrides: Container parameters, such as the entry point and environment variables,
                that replace the action's own. Fields left unset keep the action's values; ``None`` keeps them all.
            idempotency_id: ID that no other invocation may share, so retrying a request never runs the action
                twice. ``None`` sets no such ID.
            invocation_source_id: ID of the user or trigger that starts the invocation. On an
                :py:attr:`~roboto.domain.actions.InvocationSource.Manual` invocation, Roboto replaces it with the
                caller's user ID.
            parameter_values: Values for the action's parameters, keyed by parameter name. Roboto converts each value
                to a string, and gives each parameter left out its default.
            timeout: Maximum time the invocation may run, in minutes. ``None`` uses the action's timeout, or
                Roboto's default when the action has none.
            caller_org_id: Organization to create the invocation in. Required when the caller belongs to more than
                one organization; otherwise the caller's only organization.

        Returns:
            The new invocation, with status :py:attr:`~roboto.domain.actions.InvocationStatus.Queued`.

        Raises:
            RobotoIllegalArgumentException: ``input_data`` is a non-empty list and ``data_source_id`` is not set.
                Raised before any request.
            RobotoConflictException: Another invocation already has this ``idempotency_id``.
            RobotoInvalidRequestException: The action has no container image URI, ``parameter_values`` leaves out
                a required parameter, ``upload_destination`` is not a dataset, or the ``data_source_id`` dataset
                does not exist or has no files that match ``input_data``.
            RobotoLimitExceededException: The compute requirements or ``timeout`` are above the organization's
                limits, or the organization has used up its compute credits.

        Examples:
            Ingest a dataset's ROS bag files with an action from the Action Hub, and wait for it to finish:

            >>> from roboto import (
            ...     Action,
            ...     InvocationDataSourceType,
            ...     InvocationSource,
            ...     InvocationUploadDestination,
            ... )
            >>> action = Action.from_name("ros_ingestion", owner_org_id="roboto-public")
            >>> iv = action.invoke(
            ...     invocation_source=InvocationSource.Manual,
            ...     data_source_id="ds_12345",
            ...     data_source_type=InvocationDataSourceType.Dataset,
            ...     input_data=["**/*.bag"],
            ...     upload_destination=InvocationUploadDestination.dataset("ds_12345"),
            ... )
            >>> iv.wait_for_terminal_status()

            Invoke an action with a parameter value and more compute than the action asks for, then print the
            status it ends in:

            >>> from roboto import Action, InvocationSource, ComputeRequirements
            >>> action = Action.from_name("data_processor")
            >>> compute_reqs = ComputeRequirements(vCPU=4096, memory=8192)
            >>> iv = action.invoke(
            ...     invocation_source=InvocationSource.Manual,
            ...     compute_requirement_overrides=compute_reqs,
            ...     parameter_values={"threshold": 0.75},
            ... )
            >>> iv.wait_for_terminal_status()
            >>> print(iv.current_status)
        """

        resolved_input_data: typing.Optional[InvocationInput] = None
        file_paths: list[str] = []

        if isinstance(input_data, InvocationInput):
            resolved_input_data = input_data
        elif isinstance(input_data, list) and input_data:
            if not data_source_id:
                raise RobotoIllegalArgumentException(
                    "'data_source_id' is required when 'input_data' is a list of file name patterns!"
                )

            file_paths = input_data
            resolved_input_data = InvocationInput.from_dataset_file_paths(
                dataset_id=data_source_id, file_paths=input_data
            )

        request = CreateInvocationRequest(
            data_source_id=(data_source_id or InvocationDataSource.unspecified().data_source_id),
            data_source_type=(data_source_type or InvocationDataSource.unspecified().data_source_type),
            input_data=file_paths,
            rich_input_data=resolved_input_data,
            invocation_source=invocation_source,
            compute_requirement_overrides=compute_requirement_overrides,
            container_parameter_overrides=container_parameter_overrides,
            idempotency_id=idempotency_id,
            invocation_source_id=invocation_source_id,
            parameter_values=parameter_values,
            timeout=timeout,
            upload_destination=upload_destination,
            owner_org_id=self.org_id,
        )

        if request.timeout is None:
            request.timeout = self.__record.timeout

        response = self.__roboto_client.post(
            f"v1/actions/{self.name}/invoke",
            data=request,
            caller_org_id=caller_org_id,
            # Sets X-Roboto-Resource-Owner-Id, the only place older versions of Roboto read the action's owner from.
            owner_org_id=self.org_id,
            query={"digest": self.digest},
        )
        record = response.to_record(InvocationRecord)
        return Invocation(record, self.__roboto_client)

    def set_accessibility(self, accessibility: Accessibility) -> "Action":
        """Set who can find and invoke this action: members of its organization, or every Roboto user.

        Accessibility applies to every version of the action. Only Roboto administrators can change it.

        Args:
            accessibility: :py:attr:`~roboto.domain.actions.Accessibility.ActionHub` publishes the action to the
                Action Hub; :py:attr:`~roboto.domain.actions.Accessibility.Organization` limits it to members of the
                organization that owns it.

        Returns:
            This instance, with its record updated from Roboto's response, which holds the action's latest version.

        Examples:
            Publish an action to the Action Hub:

            >>> from roboto.domain.actions import Accessibility
            >>> action = Action.from_name("my_action")
            >>> action.set_accessibility(Accessibility.ActionHub)

            Limit it to members of its organization again:

            >>> action.set_accessibility(Accessibility.Organization)
        """
        request = SetActionAccessibilityRequest(accessibility=accessibility)
        response = self.__roboto_client.put(
            f"v1/actions/{self.name}/accessibility",
            data=request,
            owner_org_id=self.org_id,
        )
        record = response.to_record(ActionRecord)
        self.__record = record
        return self

    def to_dict(self) -> dict[str, typing.Any]:
        """Return this action's record as a dictionary of JSON-compatible values.

        Returns:
            :py:class:`~roboto.domain.actions.ActionRecord` of the action, as a JSON-compatible dictionary.

        Examples:
            >>> action = Action.from_name("my_action")
            >>> action_dict = action.to_dict()
            >>> print(action_dict["name"])
            my_action
        """
        return self.__record.model_dump(mode="json")

    def update(
        self,
        compute_requirements: typing.Optional[typing.Union[ComputeRequirements, NotSetType]] = NotSet,
        container_parameters: typing.Optional[typing.Union[ContainerParameters, NotSetType]] = NotSet,
        description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        inherits: typing.Optional[typing.Union[ActionReference, NotSetType]] = NotSet,
        metadata_changeset: typing.Union[MetadataChangeset, NotSetType] = NotSet,
        parameter_changeset: typing.Union[ActionParameterChangeset, NotSetType] = NotSet,
        short_description: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        timeout: typing.Optional[typing.Union[int, NotSetType]] = NotSet,
        uri: typing.Optional[typing.Union[str, NotSetType]] = NotSet,
        requires_downloaded_inputs: typing.Union[bool, NotSetType] = NotSet,
    ) -> "Action":
        """Update this action's properties.

        Each argument left unset (``NotSet``) leaves that property unchanged. A change to what the action runs (its
        image, container, compute, parameters, timeout, or input downloading) creates a new version of the action,
        with a new digest. A change to only its descriptions, tags, or metadata does not.

        Args:
            compute_requirements: CPU, memory, and storage for each invocation of the action. ``None`` resets them to
                the defaults of :py:class:`~roboto.domain.actions.ComputeRequirements`.
            container_parameters: Command, entry point, environment variables, and working directory for the
                action's container. ``None`` clears them.
            description: Human-readable description of the action. ``None`` or ``""`` clears it.
            inherits: Deprecated. Roboto rejects a request that sets it to an action reference; set the
                configuration on the action itself.
            metadata_changeset: Changes to the action's tags and metadata.
            parameter_changeset: Parameters to add, replace, or remove, matched by name.
            short_description: Brief human-readable description of the action, at most 140 characters
                (``SHORT_DESCRIPTION_LENGTH``). ``None`` or ``""`` clears it.
            timeout: Maximum time, in minutes, an invocation of the action may run before Roboto stops it. ``None``
                clears it, so invocations use Roboto's default.
            uri: URI of the container image the action runs, with surrounding whitespace stripped. ``None`` clears
                it.
            requires_downloaded_inputs: Whether Roboto downloads an invocation's input files into the action's
                container before it runs.

        Returns:
            This instance, with its record updated from Roboto's response.

        Raises:
            RobotoIllegalArgumentException: ``short_description`` is longer than 140 characters. Raised before any
                request.
            RobotoInvalidRequestException: ``inherits`` is set to an action reference, two added parameters share a
                name, or an added required parameter has a default.
            RobotoLimitExceededException: ``compute_requirements`` or ``timeout`` is above the organization's
                limits.

        Examples:
            Update the description and timeout:

            >>> action = Action.from_name("my_action")
            >>> action.update(description="Updated description of what this action does", timeout=45)

            Update the compute requirements:

            >>> from roboto.domain.actions import ComputeRequirements
            >>> action.update(compute_requirements=ComputeRequirements(vCPU=4096, memory=8192))

            Set two metadata fields and add a tag:

            >>> from roboto.updates import MetadataChangeset
            >>> changeset = (
            ...     MetadataChangeset.Builder()
            ...     .put_field("version", "2.0")
            ...     .put_field("team", "ml")
            ...     .put_tag("ml")
            ...     .build()
            ... )
            >>> action.update(metadata_changeset=changeset)
        """
        request = remove_not_set(
            UpdateActionRequest(
                compute_requirements=compute_requirements,
                container_parameters=container_parameters,
                description=description,
                inherits=inherits,
                metadata_changeset=metadata_changeset,
                parameter_changeset=parameter_changeset,
                uri=uri,
                short_description=short_description,
                timeout=timeout,
                requires_downloaded_inputs=requires_downloaded_inputs,
            )
        )

        if (
            is_set(request.short_description)
            and request.short_description is not None
            and len(request.short_description) > SHORT_DESCRIPTION_LENGTH
        ):
            raise RobotoIllegalArgumentException(
                f"Short description exceeds max length of {SHORT_DESCRIPTION_LENGTH} characters"
            )

        response = self.__roboto_client.put(
            f"v1/actions/{self.name}",
            data=request,
            owner_org_id=self.org_id,
        )
        record = response.to_record(ActionRecord)
        self.__record = record
        return self
