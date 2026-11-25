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
from ...http import ACTION_CONFIG_VERSION_HEADER, RobotoClient
from ...query import QuerySpecification
from ...sentinels import (
    NotSet,
    NotSetType,
    is_set,
)
from .action_operations import (
    SetActionAccessibilityRequest,
)
from .action_record import (
    Accessibility,
    ActionParameter,
    ActionRecord,
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
)
from .action_version import (
    ActionVersion,
    CreateReleaseRequest,
    CreateVersionedActionRequest,
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
        release: CreateReleaseRequest,
        description: typing.Optional[str] = None,
        short_description: typing.Optional[str] = None,
        tags: typing.Optional[list[str]] = None,
        metadata: typing.Optional[dict[str, typing.Any]] = None,
        caller_org_id: typing.Optional[str] = None,
        roboto_client: typing.Optional[RobotoClient] = None,
        action_config_version: typing.Optional[int] = None,
    ) -> "Action":
        """Create an action together with its first release.

        The first release is version ``1.0.0`` unless ``release.version`` names another. Publish later releases
        with :py:meth:`create_release`.

        Args:
            name: Human-readable name of the action, unique within its organization. Letters, digits, underscores,
                and dashes only.
            release: What the first release runs, on which compute, and with which defaults.
            description: Human-readable description of the action.
            short_description: Brief human-readable description of the action, at most 140 characters
                (``SHORT_DESCRIPTION_LENGTH``).
            tags: Tags to set on the action. ``None`` sets none.
            metadata: Key-value metadata to set on the action. ``None`` sets none.
            caller_org_id: Organization to create the action in. Required when the caller belongs to more than one
                organization; otherwise the caller's only organization.
            roboto_client: Client to make requests to Roboto with. Defaults to one configured from the environment,
                by :py:meth:`~roboto.http.RobotoClient.from_env`.
            action_config_version: Schema version of the ``action.json`` file the request was built from (see
                :py:class:`~roboto.domain.actions.ActionConfig`). ``None`` when the request was not built from one.

        Returns:
            The new action, fetched by name after it is created. :py:meth:`get_version` returns its release.

        Raises:
            RobotoIllegalArgumentException: ``short_description`` is longer than 140 characters. Raised before any
                request.
            RobotoConflictException: The organization already has an action with this name.
            RobotoInvalidRequestException: The release is malformed or cannot run as declared.
            RobotoLimitExceededException: The organization has as many actions as its plan allows, or the release's
                ``timeout_s_default`` is above the organization's limit.
            RobotoUnauthorizedException: The caller's credential holds fewer grants than the release states.

        Examples:
            Create an action that runs a container image:

            >>> from roboto.domain.actions import (
            ...     Action,
            ...     ComputeShape,
            ...     CreateReleaseRequest,
            ...     ReleaseExecutable,
            ...     Substrate,
            ... )
            >>> action = Action.create(
            ...     name="hello_world",
            ...     release=CreateReleaseRequest(
            ...         substrate=Substrate.Fargate,
            ...         executable=ReleaseExecutable(image_ref="ubuntu:latest"),
            ...         shape=ComputeShape(vcpu=0.5, memory_mib=1024),
            ...         timeout_s_default=600,
            ...     ),
            ...     description="A simple hello world action",
            ... )

            Create an action whose runs write data, with parameters and container settings:

            >>> from roboto.domain.actions import ActionParameter, FargateSubstrateConfig
            >>> action = Action.create(
            ...     name="data_processor",
            ...     release=CreateReleaseRequest(
            ...         substrate=Substrate.Fargate,
            ...         executable=ReleaseExecutable(image_ref="my-registry.com/processor:v1.0"),
            ...         shape=ComputeShape(vcpu=4, memory_mib=8192),
            ...         timeout_s_default=3600,
            ...         grants=["*:*"],
            ...         parameters=[ActionParameter(name="threshold", required=True)],
            ...         substrate_config=FargateSubstrateConfig(env_vars={"MODE": "fast"}),
            ...     ),
            ...     tags=["data-processing", "sensors"],
            ... )

            Create an action that runs a Python file:

            >>> import pathlib
            >>> action = Action.create(
            ...     name="summarize",
            ...     release=CreateReleaseRequest(
            ...         substrate=Substrate.Microvm,
            ...         executable=ReleaseExecutable(payload=pathlib.Path("summarize.py").read_bytes()),
            ...         shape=ComputeShape(memory_mib=2048),
            ...         timeout_s_default=300,
            ...     ),
            ... )
        """
        if short_description is not None and len(short_description) > SHORT_DESCRIPTION_LENGTH:
            raise RobotoIllegalArgumentException(
                f"Short description exceeds max length of {SHORT_DESCRIPTION_LENGTH} characters"
            )

        request = CreateVersionedActionRequest(
            description=description,
            short_description=short_description,
            tags=tags or [],
            metadata=metadata or {},
            release=release,
        )

        roboto_client = RobotoClient.defaulted(roboto_client)
        # Dumped in full: a model passed as data is sent with only the fields the caller set, which would drop the
        # substrate_config and output discriminators (they are defaults), and Roboto needs them to parse the body.
        roboto_client.post(
            f"v1/actions/{name}",
            data=request.model_dump(mode="json"),
            caller_org_id=caller_org_id,
            headers=_action_config_headers(action_config_version),
        )
        return cls.from_name(name, owner_org_id=caller_org_id, roboto_client=roboto_client)

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

    def create_release(
        self, release: CreateReleaseRequest, action_config_version: typing.Optional[int] = None
    ) -> ActionVersion:
        """Publish a new release of this action, which invocations that name no version then run.

        Releases are immutable: this never changes what an existing release runs. This instance keeps its earlier
        record; fetch the action again with :py:meth:`from_name` to see the new release.

        Args:
            release: What the new release runs, on which compute, and with which defaults. Unless
                ``release.version`` names a number, Roboto publishes a patch bump of the highest number this action
                has used, deleted releases included.
            action_config_version: Schema version of the ``action.json`` file the request was built from (see
                :py:class:`~roboto.domain.actions.ActionConfig`). ``None`` when the request was not built from one.

        Returns:
            The published release.

        Raises:
            RobotoConflictException: ``release.version`` is not higher than every number this action has used, or
                the release names only an image and the latest release already runs exactly the same content.
            RobotoInvalidRequestException: The release is malformed or cannot run as declared.
            RobotoUnauthorizedException: The caller's credential holds fewer grants than the release states.

        Examples:
            >>> from roboto.domain.actions import ComputeShape, CreateReleaseRequest, ReleaseExecutable, Substrate
            >>> action = Action.from_name("data_processor")
            >>> version = action.create_release(
            ...     CreateReleaseRequest(
            ...         substrate=Substrate.Fargate,
            ...         executable=ReleaseExecutable(image_ref="my-registry.com/processor:v1.1"),
            ...         shape=ComputeShape(vcpu=4, memory_mib=8192),
            ...         timeout_s_default=3600,
            ...     )
            ... )
            >>> print(version.version)
        """
        response = self.__roboto_client.post(
            f"v1/actions/{self.name}/versions",
            data=release.model_dump(mode="json"),
            owner_org_id=self.org_id,
            headers=_action_config_headers(action_config_version),
        )
        return response.to_record(ActionVersion)

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

    def get_version(self, ref: str = "latest") -> ActionVersion:
        """Fetch one of this action's releases.

        Args:
            ref: ``"latest"``, a version number such as ``"1.2.0"``, or a label.

        Raises:
            RobotoNotFoundException: No live release of this action matches ``ref``.

        Examples:
            >>> action = Action.from_name("data_processor")
            >>> print(action.get_version().grants)
        """
        response = self.__roboto_client.get(f"v1/actions/{self.name}/versions/{ref}", owner_org_id=self.org_id)
        return response.to_record(ActionVersion)

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

    def set_label(self, label: str, version: str) -> None:
        """Point a label, such as ``"stable"``, at one of this action's releases, creating the label if needed.

        Args:
            label: Name of the label. ``"latest"`` is reserved: it always names the newest release.
            version: Version number of the release, such as ``"1.2.0"``.

        Raises:
            RobotoInvalidRequestException: ``label`` is ``"latest"``.
            RobotoNotFoundException: This action has no live release with this number.

        Examples:
            >>> action = Action.from_name("data_processor")
            >>> action.set_label("stable", "1.2.0")
        """
        self.__roboto_client.put(
            f"v1/actions/{self.name}/labels/{label}", data={"version": version}, owner_org_id=self.org_id
        )

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
        release: typing.Optional[CreateReleaseRequest] = None,
        description: typing.Union[str, None, NotSetType] = NotSet,
        short_description: typing.Union[str, None, NotSetType] = NotSet,
        tags: typing.Union[list[str], NotSetType] = NotSet,
        metadata: typing.Union[dict[str, typing.Any], NotSetType] = NotSet,
        labels: typing.Optional[collections.abc.Sequence[str]] = None,
        action_config_version: typing.Optional[int] = None,
    ) -> "Action":
        """Publish a new release of this action, edit its descriptions, tags and metadata, or both.

        Each argument left unset (``NotSet``, or ``None`` for ``release`` and ``labels``) leaves that property
        unchanged; editing only the descriptions, tags or metadata publishes no release. The steps run in this
        order, and a failure leaves the earlier ones done:

        1. Publish ``release``, as :py:meth:`create_release` does.
        2. Point each of ``labels`` at it, as :py:meth:`set_label` does.
        3. Edit the descriptions, tags and metadata.

        Args:
            release: Release to publish. Invocations that name no version run it from then on.
            description: Human-readable description of the action. ``None`` clears it.
            short_description: Brief human-readable description of the action, at most 140 characters
                (``SHORT_DESCRIPTION_LENGTH``). ``None`` clears it.
            tags: Tags to set on the action, replacing the ones it has.
            metadata: Key-value metadata to set on the action, replacing what it has.
            labels: Labels, such as ``"stable"``, to point at the release this call publishes. Requires
                ``release``.
            action_config_version: Schema version of the ``action.json`` file the request was built from (see
                :py:class:`~roboto.domain.actions.ActionConfig`). ``None`` when the request was not built from one.

        Returns:
            This instance, with its record fetched again from Roboto when anything changed.

        Raises:
            RobotoIllegalArgumentException: ``short_description`` is longer than 140 characters, or ``labels`` is
                given without ``release``. Raised before any request.
            RobotoConflictException: ``release.version`` is not higher than every number this action has used, or
                ``release`` names only an image and the latest release already runs exactly the same content.
            RobotoInvalidRequestException: ``release`` is malformed or cannot run as declared, or ``labels``
                includes ``"latest"``.
            RobotoUnauthorizedException: The caller's credential holds fewer grants than ``release`` states.

        Examples:
            Run a new image and point the ``stable`` label at it:

            >>> from roboto.domain.actions import ComputeShape, CreateReleaseRequest, ReleaseExecutable, Substrate
            >>> action = Action.from_name("my_action")
            >>> action.update(
            ...     release=CreateReleaseRequest(
            ...         substrate=Substrate.Fargate,
            ...         executable=ReleaseExecutable(image_ref="my-registry.com/my_action:v2"),
            ...         shape=ComputeShape(vcpu=1, memory_mib=2048),
            ...         timeout_s_default=2700,
            ...     ),
            ...     labels=["stable"],
            ... )

            Edit the description and tags, which publishes nothing:

            >>> action.update(description="Detects anomalies in IMU data", tags=["imu", "anomaly"])
        """
        if labels and release is None:
            raise RobotoIllegalArgumentException("labels can only be moved to a release this update publishes")

        if (
            is_set(short_description)
            and short_description is not None
            and len(short_description) > SHORT_DESCRIPTION_LENGTH
        ):
            raise RobotoIllegalArgumentException(
                f"Short description exceeds max length of {SHORT_DESCRIPTION_LENGTH} characters"
            )

        if release is not None:
            version = self.create_release(release, action_config_version=action_config_version)
            for label in labels or []:
                self.set_label(label, version.version)

        details = {
            field: value
            for field, value in (
                ("description", description),
                ("short_description", short_description),
                ("tags", tags),
                ("metadata", metadata),
            )
            if is_set(value)
        }
        if details:
            self.__roboto_client.put(
                f"v1/actions/{self.name}/details",
                data=details,
                owner_org_id=self.org_id,
                headers=_action_config_headers(action_config_version),
            )

        if release is not None or details:
            self.__record = Action.from_name(
                self.name, owner_org_id=self.org_id, roboto_client=self.__roboto_client
            ).record
        return self


def _action_config_headers(action_config_version: typing.Optional[int]) -> typing.Optional[dict[str, str]]:
    if action_config_version is None:
        return None
    return {ACTION_CONFIG_VERSION_HEADER: str(action_config_version)}
