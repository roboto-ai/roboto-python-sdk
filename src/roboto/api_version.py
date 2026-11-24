# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from .compat import StrEnum


class RobotoApiVersion(StrEnum):
    """Version of the Roboto API a request asks for, which sets the request and response shapes Roboto uses for it.

    Each version is named for a date in ``YYYY-MM-DD`` form. Each member's docstring says what changes from that
    version on; a request at an older version keeps the earlier behavior. The SDK sends the version ``latest``
    returns in the ``X-Roboto-Api-Version`` header of its requests, except where a method needs an older version's
    shape. Roboto serves a request that names no version, or a version it does not know, at its own latest version.
    """

    v2025_01_01 = "2025-01-01"
    """Earliest version, with the behavior every later version changes."""

    v2025_07_14 = "2025-07-14"
    """Same behavior as ``v2025_01_01``."""

    v2026_01_02 = "2026-01-02"
    """In a dataset update, ``None`` for ``name``, ``description`` or ``device_id`` clears the field.

    This covers :py:meth:`~roboto.domain.datasets.Dataset.update`. Clients on older API versions send ``None`` for a
    field they leave unset, so for them ``None`` leaves the field unchanged.
    """

    v2026_02_02 = "2026-02-02"
    """Queries honor their ``content_mode``, so ``RecordOnly`` returns records without their metadata.

    The mode is a :py:class:`~roboto.query.QueryContentMode`, and
    :py:attr:`~roboto.query.QueryContentMode.RecordOnly` is the mode that leaves metadata out. Clients on older API
    versions receive every record with its metadata, whatever ``content_mode`` they send.
    """

    v2026_02_11 = "2026-02-11"
    """Each message path a request creates on a topic must set ``path_in_schema``.

    The field is :py:attr:`~roboto.domain.topics.AddMessagePathRequest.path_in_schema`. For clients on older API
    versions, Roboto fills a missing one from the message path's ``column_name`` metadata, or else by splitting
    ``message_path`` on dots.
    """

    v2026_03_13 = "2026-03-13"
    """Query results can lag recent writes unless the request sets the ``X-Roboto-Connection-Consistency`` header.

    The lag covers writes made moments before the query. Clients on older API versions receive query results that
    reflect every completed write.
    """

    v2026_05_20 = "2026-05-20"
    """AI chats are agent threads (:py:class:`~roboto.ai.agent_thread.AgentThread`) in requests and responses.

    ``thread_id`` replaces ``chat_id`` and ``session_id``, ``forked_from_thread_id`` replaces
    ``forked_from_session_id``, ``/v1/ai/threads`` replaces ``/v1/ai/chats``, and
    ``POST /v1/ai/agents/{agent_id}/launch`` starts an agent. A request at this version to a ``/v1/ai/chats`` path is
    refused with HTTP 400. Clients on older API versions receive ``session_id`` and ``chat_id`` in place of
    ``thread_id``, and can still call the ``/v1/ai/chats`` paths.
    """

    v2026_07_05 = "2026-07-05"
    """``PUT /v1/files/upload/{upload_id}/progress`` responds with ``{uri, file_id}`` pairs.

    The pairs replace a bare list of file IDs, so an upload client can tell which created file belongs to which
    uploaded path. Clients on older API versions continue to receive the bare list.
    """

    v2026_08_10 = "2026-08-10"
    """Tag listings for datasets, events and files respond with a paginated ``{items, next_token}`` object.

    The endpoints are ``GET /v1/datasets/tags``, ``GET /v1/events/tags``, and ``GET /v1/files/tags``. They accept
    optional ``search``, ``limit`` and ``page_token`` query parameters, and the object replaces a bare list of
    strings, so tag autocomplete can page through every unique tag. Clients on older API versions continue to receive
    the bare list.
    """

    v2026_08_27 = "2026-08-27"
    """``/v1/triggers`` sends and accepts triggers in the shape of :py:class:`~roboto.domain.triggers.Trigger`.

    That shape has ``events``, ``once_per`` and ``targets`` instead of the ``causes``, ``for_each`` and action fields
    of :py:class:`~roboto.domain.actions.Trigger`. ``/v1/triggers`` also rejects a caller-supplied
    ``service_user_id``. Clients on older API versions keep the older shape: Roboto translates their creates and
    updates onto triggers of the newer shape and translates responses back. A trigger the older shape cannot express
    (several targets, a target other than an action, or a newer platform event type) is dropped from their trigger
    listings and reported as not found when read directly.
    """

    v2026_09_30 = "2026-09-30"
    """Agent thread messages can carry ``client_context`` content blocks.

    Such a block records what the user was viewing when they sent the message, and is stored on the message itself.
    Clients on older API versions receive threads with those blocks removed, since their ``AgentContent`` union cannot
    parse them.
    """

    v2026_10_02 = "2026-10-02"
    """A file record can be a link: its ``fs_type`` is ``Link``.

    A link's ``roboto://`` URI pins one version of another file. Clients on older API versions, whose
    :py:class:`~roboto.domain.files.FSType` has only ``File`` and ``Directory``, never receive a link: links are
    dropped from file listings, and reading one directly by ID or path reports it as not found.
    """

    v2026_10_05 = "2026-10-05"
    """The read plan states the bounds each partition's rows are selected in on a per-partition ``window``.

    This is the plan ``POST /v2/topics/id/{topic_id}/read-plan`` returns, which states those bounds on an ``extent``
    at older versions. Clients on older API versions continue to receive ``extent``, set on every partition to the
    plan's own window; such a client selects rows by the plan's window alone. For those clients, two kinds of read
    are refused with HTTP 400 and a message to upgrade, rather than served by the plan's window: a read scoped to a
    session that holds a file over only part of the requested time span, and a read covering a file that packs
    several partitions' data. Either would otherwise return rows belonging to another session, or to another
    partition packed into the same file.

    Adding files to a session, removing them, and publishing metrics answer with one element per entry the
    request named, in the order it named them, each holding the entry's result or the error that refused
    it. An entry Roboto refuses leaves the others in place: an add decides every refusal before writing
    anything and adds the rest together, and a remove removes together every file the session holds and reports
    the rest as not held. An unexpected failure, such as a timeout, adds or removes none of them. An add naming a
    file that does not exist is refused whole, before any entry is applied. A file entry states the window the
    session holds the file over in the file's own timestamps, on ``min_file_timestamp_ns`` and
    ``max_file_timestamp_ns``, and a call names at least one file. Listing a session's files reports each file's
    window in nanoseconds since the Unix epoch on ``min_wall_clock_timestamp_ns`` and ``max_wall_clock_timestamp_ns``.

    Clients on older API versions keep the earlier contract for these four calls. Listing a session's files
    reports the same window on ``range_min_timestamp_ns`` and ``range_max_timestamp_ns``. A file entry carries
    the file's ID, an optional ``data_range``, and a window in nanoseconds since the Unix epoch on
    ``range_min_timestamp_ns`` and ``range_max_timestamp_ns``. Adds and removes accept a call naming no
    files and answer with the session's refreshed record. An add stands or falls whole: when Roboto
    refuses a file, it answers with the error for the first refused file and adds none of them, and a file
    named twice is added over its last entry. A remove stands or falls whole too, and skips a file the
    session does not hold. Metric publication answers with a ``succeeded`` list and a ``failed`` list.
    ``succeeded`` holds one record per metric and session, carrying the last value written when a call published
    the same pair more than once; each entry in ``failed`` is named by the metric name the caller submitted.
    """

    v2026_10_06 = "2026-10-06"
    """A saved View's filter rows can carry ``or_null``, and a ``boolean`` ``EQUALS`` row can name both values.

    The filter rows are :py:class:`~roboto.query.SavedFilters`. Clients on older API versions, whose filter rows
    forbid unknown fields and allow a boolean exactly one value, never receive a View they cannot parse: a boolean
    ``EQUALS`` over both values reaches them as the ``IS_NOT_NULL`` it means, a View with a row using ``or_null`` is
    dropped from View listings and reported as not found when read by ID, and updating such a View is refused with
    HTTP 400 and a message to upgrade.
    """

    v2026_10_22 = "2026-10-22"
    """Event search (:py:attr:`~roboto.query.QueryTarget.Events`) also returns events created on a session.

    Those are ``roboto.experimental.events.EventRecord`` records, with IDs ``evt_*``, returned beside dataset events
    (:py:class:`~roboto.domain.events.EventRecord`, IDs ``ev_*``). It returns them only in organizations that have
    session events enabled, and only to a caller who may view the organization's sessions. Clients on older API
    versions receive dataset events only. They also never receive the ``session_event.created`` platform event's
    sample, triggers subscribed to that platform event, or the dispatches it produced, which their
    ``PlatformEventType`` cannot parse.
    """

    v2026_10_25 = "2026-10-25"
    """Creating an organization succeeds even when the creator's email domain it asks to bind stays unbound.

    The response's :py:attr:`~roboto.domain.orgs.CreateOrgResponse.email_domain_binding_outcome` can be any member of
    :py:class:`~roboto.domain.orgs.EmailDomainBindingOutcome`: ``HeldByAnotherOrg`` when another organization holds
    the domain, ``VerificationStarted`` with the DNS TXT record that verifies the domain in
    :py:attr:`~roboto.domain.orgs.CreateOrgResponse.verification_txt_record`, and ``EmailNotProven``, which Roboto
    does not return. Clients on older API versions keep the earlier contract: when another organization holds the
    domain, the creation is refused with HTTP 409 and creates no organization, and in place of ``VerificationStarted``
    they receive no outcome and no DNS TXT record.
    """

    v2026_11_02 = "2026-11-02"
    """The read plan includes a partition whose stored representations fail the coverage checks.

    This is the plan ``POST /v2/topics/id/{topic_id}/read-plan`` returns. A partition fails them when one of its
    representations names a field outside its schema, or when it owns a slice of a shared file and a projected field
    that one of its representations holds is held by none readable at the slice's row positions. The plan gives such
    a partition scan tasks over the representations that can serve the read, or no scan tasks when none can. An SDK
    release that sends this version issues one ``UnreadableTopicPartitionsWarning`` naming every partition with no
    scan tasks, and raises :py:class:`~roboto.exceptions.RobotoReadPlanExecutionException` when a partition's scan
    tasks leave out a projected field. Requests at older API versions keep the coverage checks: a read in which any
    partition fails them is refused with HTTP 400 and a message that names up to 20 failing partitions and why each
    fails, and asks the caller to upgrade.
    """

    v2026_11_05 = "2026-11-05"
    """A View's ``definition`` is ``view_v2``: its display states the sort as one ``sort`` field.

    That field (:py:const:`~roboto.domain.views.ViewSort`: the target's default, no sort, or one column in one
    direction) replaces ``sort_by``, ``sort_direction`` and ``unsorted``. Roboto reads a definition in either shape.
    Clients on older API versions receive every View as ``view_v1`` with the three older fields.
    """

    v2026_11_19 = "2026-11-19"
    """The access routes of datasets, collections and Views take and return grants instead of tuples.

    ``GET`` and ``PUT`` on ``/v1/datasets/{dataset_id}/access``, ``/v1/collections/{collection_id}/access`` and
    ``/v1/views/id/{view_id}/access`` respond with :py:class:`~roboto.auth.RecordAccessResponse`: whether members of
    the record's organization need a grant to reach it, and the record's grants, each a subject and a role. A ``PUT``
    takes :py:class:`~roboto.auth.EditRecordAccessRequest`, and one that changes nothing needs only permission to read
    the record. The response does not list the record's owner, a View's author or a dataset's collections. Clients on
    older API versions keep sending and receiving tuples, each a user, a relation and a record
    (:py:class:`~roboto.auth.EditAccessRequest` and :py:class:`~roboto.auth.GetAccessResponse`), and the tuples they
    receive include the record's owner, a View's author and a dataset's collections.
    """

    v2026_11_20 = "2026-11-20"
    """A skill can have accessibility ``roboto``: a skill that Roboto ships.

    Members of an organization can read such a skill (:py:attr:`~roboto.domain.skills.SkillAccessibility.Roboto`), and
    nobody can edit it, delete it or subscribe to it. Its version lists its resources, each by name and when the AI
    reads it (:py:attr:`~roboto.domain.skills.SkillVersionRecord.resources`), and has an empty ``body``: Roboto never
    returns such a skill's instructions or the text of a resource. Clients on older API versions, whose
    ``SkillAccessibility`` cannot parse ``roboto``, never receive one: skill listings leave these skills out, and a
    request for one by ID or by name, for its summary, or for its versions is answered with HTTP 404.
    """

    v2026_11_23 = "2026-11-23"
    """A topic record holds only the message paths that fit in one response, with a token for the rest.

    ``POST /v1/topics``, ``GET /v1/topics/id/{topic_id}``,
    ``GET /v1/topics/association/{encoded_association}/name/{url_quoted_topic_name}`` and
    ``GET /v1/topics/association/{encoded_association}`` return topic records that list a topic's message paths, a
    parent before its children, up to the last one that fits in one response. A record that leaves message paths out
    sets :py:attr:`~roboto.domain.topics.TopicRecord.message_paths_next_token`, which
    ``GET /v1/topics/id/{topic_id}/message-paths`` takes as ``page_token`` to return the rest. Clients on older API
    versions receive every message path from the three ``GET`` routes, and their request for a topic whose record
    does not fit in one response fails. At every API version, ``POST /v1/topics`` returns only the message paths
    that fit.
    """

    @staticmethod
    def latest() -> RobotoApiVersion:
        """Return the newest API version this release of the SDK knows."""
        return RobotoApiVersion.v2026_11_23

    def is_latest(self) -> bool:
        """Return whether this version is the one ``latest`` returns."""
        return self == RobotoApiVersion.latest()

    def __str__(self) -> str:
        """Return the version's ``YYYY-MM-DD`` value."""
        return self.value
