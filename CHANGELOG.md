# Changelog

# 0.55.0
## Breaking Changes
  - Custom fields (experimental): a `String` value is capped at 256 characters, where it was previously unbounded, and is stored with surrounding whitespace trimmed. The cap is measured on the value as sent, so padding counts against it without being stored. A value that is blank once trimmed is rejected; pass `None` to clear the field instead.
  - Custom fields (experimental): a `Timestamp` value given as an all-digit string is read as epoch seconds, where it previously parsed as an ISO 8601 basic-format date. `"20260101"` now names an instant in August 1970 rather than 1 January 2026. Spell a date with separators — `"2026-01-01"` — to keep the previous reading.
  - A `collection.collection_id` (alias `collection.id`) filter on a Datasets, Events, or Files query accepts only `EQUALS` and `NOT_EQUALS`, and returns HTTP 400 for every other comparator. Previously none of these three query targets checked the field against Roboto's field catalog, so every comparator reached SQL: `CONTAINS` and `NOT_CONTAINS` matched against any substring of the ID; `LIKE` and `NOT_LIKE` compared through SQL `LIKE`, which is an exact comparison unless the value carries a `%` or `_` wildcard; `BEGINS_WITH` compared through a wildcard `LIKE` pattern; `GREATER_THAN`, `GREATER_THAN_OR_EQUAL`, `LESS_THAN`, and `LESS_THAN_OR_EQUAL` ordered the ID as text; and `IS_NULL`, `IS_NOT_NULL`, `EXISTS`, and `NOT_EXISTS` tested it for null. All thirteen now return 400. This is the allow-list a Collections query and a Sessions query already applied to the same field; the three query targets that bypassed it now go through the same path. A collection ID is an opaque `cl_`-prefixed handle, so rewrite any of these filters to compare against the whole ID with `EQUALS` or `NOT_EQUALS`.
  - A filter value naming an instant before the Unix epoch returns HTTP 400 on the six timestamp fields that take one: Sessions `min_timestamp_ns` and `max_timestamp_ns` (aliased `start_time` and `end_time`), Events `start_time` and `end_time`, and Topics `start_time` and `end_time`. These columns count nanoseconds forward from 1970 and hold nothing negative, so a negative bound names no instant a caller could have meant. Previously a negative integer was passed through as written, and a negative float, numeric string, or `Decimal`, or a datetime earlier than 1970, was converted to a negative nanosecond count and compared, so a filter as ordinary-looking as `start_time != -1` was accepted. The rejection reads the converted value rather than what you wrote, so every spelling of the same instant is refused the same way; `-1` and `-1.0` no longer take different paths.

## Features Added
  - `Metric.query` (experimental): add time asc/desc sorting to the metrics query API backend endpoint.
  - Custom fields (experimental): a `Timestamp` value may be given as epoch seconds — a `float`, a `decimal.Decimal`, or a numeric string — alongside the `datetime`, ISO 8601 string, and epoch-nanoseconds `int` already accepted. A string is read as epoch seconds whenever it parses as a number, and as ISO 8601 only when it does not. A value that states no time zone — a naive `datetime`, or an ISO 8601 string carrying no offset — is read as UTC.
  - `roboto.query.SavedFilters` gains an eighth filter kind, `identity`, for the audit columns that hold a principal rather than a plain string (`created_by`, `modified_by`). Its operator names a principal type instead of a comparison: `IS_USER`, `IS_DEVICE`, `IS_INVOCATION`, `IS_INTEGRATION`, and `IS_ORG` each carry the principals of that type to match, and the valueless `IS_ANY_USER`, `IS_ANY_DEVICE`, `IS_ANY_INVOCATION`, `IS_ANY_INTEGRATION`, and `IS_ANY_ORG` match the whole type. These are `roboto.query.IdentityComparator`, not `Comparator` members, because a client expands them on the way to a query: `IS_<TYPE>` becomes `EQUALS` against each named principal (several are alternatives, so they fan out to an OR) and `IS_ANY_<TYPE>` becomes `LIKE '<type>:%'`. Values are `roboto.query.LabeledOption`s, each carrying the fully-qualified principal (`user:<user_id>`, `device:<device_id>@<org_id>`) alongside the display name shown when it was picked, since a principal ID is not a name a reader can place. A value whose type disagrees with the operator, or that is not a `<type>:<id>` principal at all, is rejected rather than stored as a filter that can never match.
  - `Metric.query` and `Metric.aggregate` (experimental) accept a `condition`, a single `Condition` or a nested `ConditionGroup`, so a metric can be read for only the sessions, devices, and collections you care about rather than every session in the time window. Every field must name the entity it filters on, in either the singular or the plural spelling: `session.<field>` (or `sessions.<field>`) and `session.custom.<name>` for the session a data point belongs to, `device.<field>` (or `devices.<field>`) and `device.custom.<name>` for the device that produced it, and `collection.collection_id` (or `collections.collection_id`, alias `collection.id`) and `collection.custom.<name>` for the collections the data point's session belongs to. The collection ID field accepts only `EQUALS` and `NOT_EQUALS`, the same two comparators it takes on every other query; any other comparator returns HTTP 400. A session belongs to any number of collections, so a collection condition quantifies over that set: a data point matches when its session belongs to at least one collection satisfying the condition, and a negated comparator means its session belongs to no collection satisfying the positive form, so a session in no collection at all matches every negated collection condition. On `aggregate`, the filter narrows what each bucket aggregates, and a bucket left with no matching data points is omitted.
  - Files can now be filtered by `ingestion_status` through `RobotoSearch.find_files` and the structured-query API, by equality or inequality against `not_ingested`, `partly_ingested`, or `ingested`. A file becomes `partly_ingested` as soon as a topic is recorded against it, and `ingested` only when a caller marks it so with `File.mark_ingested()` — conventionally the ingestion action that processed the file, though nothing enforces that. Only `ingested` makes a file eligible for post-ingestion triggers, so `partly_ingested` is where to look for files whose ingestion started but never reported completion. Files in formats Roboto does not ingest, such as images or PDFs, stay `not_ingested` unless a caller marks them ingested.
  - Sessions (experimental) can now be provided as inputs to action invocations, selected by session ID, session name, or RoboQL query. In the SDK that is `InvocationInput.sessions`, with the convenience factories `InvocationInput.from_session_id` and `InvocationInput.session_query`; action code reads the resolved `Session` entities off the `InvocationContext` as `ctx.get_input().sessions`. On the CLI, `roboto actions invoke` and `roboto actions invoke-local` take a repeatable `--session-id` and a `--session-query`, which combine as a union (each matched session runs once) and sit alongside `--file-query` and `--topic-query` in the selector-based input group, so one invocation can take files, topics, and sessions together; no flag in that group can be combined with `--dataset` or `--file-path`.

## Bugs Fixed
  - Custom fields (experimental): a `Timestamp` value read back from an entity's `custom_fields` is an ISO 8601 string, and a UTC one is now spelled with a `+00:00` offset instead of a `Z` suffix. `datetime.datetime.fromisoformat` rejects the `Z` form before Python 3.11, and we support Python 3.10. The instant is unchanged, and a value in another time zone keeps its own offset; only the spelling of UTC differs.
  - Custom fields (experimental): a `Timestamp` value outside the range a date and time can represent — year 1 through year 9999 — is rejected with a 400 naming the field and the offending value.
  - A timestamp filter value that a Sessions or Events query could not convert to epoch nanoseconds returned HTTP 500 for two families of bad input: a value that overflows during the conversion (`"inf"`, `"-inf"`, `"infinity"`), and a decimal exponent beyond what Python's decimal arithmetic will evaluate (`"1E+999999"`). Both now return HTTP 400 naming the field, as every other unconvertible value already did.
  - A boolean filter value on a Sessions, Events, or Topics timestamp field returns HTTP 400 rather than HTTP 500. RoboQL accepts a boolean literal on the right of any binary comparator, so `start_time > true` parses and used to reach Postgres, which has no comparison between a `bigint` column and a boolean and failed the request as an unhandled server error.
  - `start_time` and `end_time` on an Events query accept every shape `roboto.time.Time` accepts that names an instant at or after the Unix epoch: an integer (read as epoch nanoseconds), a float or `Decimal` (read as epoch seconds), an ISO8601 string, a `"<sec>.<nsec>"` string, or a datetime. Only strings were converted before; a float, `Decimal`, or datetime reached the comparison unchanged, to be compared against a column holding nanosecond counts.
  - `start_time` and `end_time` on a Topics query get that same conversion. They had none at all before, so any value other than an integer count of nanoseconds reached the comparison unchanged.
  - `collection.id` is accepted on a Datasets query, where it produces exactly the filter `collection.collection_id` does. An Events query and a Files query already accepted the alias; only a Datasets query turned it away, reporting that `collection.id` is not a valid field for the Datasets target.
  - A collection filter whose field name only begins with an accepted one is rejected rather than silently trimmed down to it. On a Datasets, Events, or Files query, `collection.identifier` was read as `collection.id` and `collection.collection_id_v2` as `collection.collection_id`, dropping the rest of the name and filtering on a field the query never asked for.
  - A name-based `topics` or `files` input selector on an action invocation quotes each name the way RoboQL spells a string literal, so a name that used to produce a malformed query resolves. A `files` selector applied no escaping, so a double quote or a backslash in a name broke the query. A `topics` selector escaped as JSON, which spells those two characters as RoboQL does but renders every non-ASCII character (an accent, a CJK character, an emoji) as a `\uXXXX` escape, a form RoboQL has no syntax for. `LIKE` wildcards in a `files` name are unaffected: this changes how a name is spelled in the query, not how it is matched.
  - A double-quoted RoboQL string literal containing a control character returns HTTP 400 naming the literal, rather than HTTP 500. Carriage return and newline were already refused by the grammar; the other 30 codepoints below U+0020 passed the grammar and then failed JSON decoding as an unhandled server error. A double-quoted literal has no escape syntax for any of the 32, so none of them can be carried in one.
  - `Dataset.upload_file` resolves the `File` it returns through the file ID the upload itself reported, instead of looking the destination path up again. The file you get back is always the one this upload created; the path lookup could return a different file when a concurrent upload replaced the same destination in between. Reading an attribute off it now costs a single indexed lookup, where the path lookup's cost grew with the size of the dataset it ran against. Resolution stays lazy, so a caller that ignores the return value still pays no request at all. An upload that completes without reporting an ID for the file raises `RobotoInternalException`.
  - A `BEGINS_WITH` filter matches values that start with the operand. It previously matched values that *ended* with it: the SQL the query engine generated anchored its wildcard on the wrong side of the bound value, so `metadata.serial BEGINS_WITH "RB-"` compiled to the pattern `%RB-` and kept rows whose value finished with `RB-` while dropping every row the filter was asking for. The comparator is spelled `startswith` in the SDK's own client-side `Condition.matches` and as DynamoDB's `begins_with` on the query paths that go to that store, both of which were always right; only the Postgres path disagreed. A filter written against the old behavior, expecting a suffix match, should be rewritten as `LIKE "%<value>"`.

# 0.54.0
## Breaking Changes
  - `roboto.storage.FileService.upload` returns a mapping from each uploaded local path to the ID of the file record it created, in place of the unordered list of file IDs it returned before. `Dataset.upload_files` callers need no change: it passes the mapping through, and previously returned nothing.
  - `Dataset.upload_files` and `roboto.storage.FileService.upload` raise `ValueError` when two of the files passed to them resolve to the same destination path, instead of uploading them. A file with no entry in `file_destination_paths` (`destination_paths` on `FileService.upload`) is destined for its own filename, so two like-named files from different directories collide; give each its own destination.
  - `roboto secrets read` was removed, so a secret's value can no longer be printed from the CLI. `roboto secrets list`, `write`, and `delete` are unchanged, as is the SDK: a script that needs a value can still read it with `Secret.from_name("my-api-key").read_value().get_secret_value()`, which is how actions resolve secrets at runtime.
  - `TopicPartitionRecord` (experimental) locates a topic's data within its file with one `data_range` pair, `(start, end)`, in place of the separate `data_from_index` and `data_to_index` bounds. `start` is the first covered position and `end` is one past the last, counted in row positions from 0 for tabular files and in nanoseconds from the start of the media for video. The `message_count`, `segment_index`, and `segment_name` fields are removed.
  - `CustomField.create` (experimental): the backend API now explicitly rejects requests with `metadata_path` set. This request field is not yet implemented, and should be left unset.

## Features Added
  - `Dataset.upload_files` returns a mapping from each local path it uploaded to the ID of the file record Roboto created for it, so you can act on the files you just uploaded without looking each one up by path.
  - `MessagePathStatistic` gains the five distribution statistics Roboto ingestion already writes alongside the existing `count`/`min`/`max`/`mean`/`median`: `Stddev`, `P25`, `P75`, `P95`, and `P99`. `MessagePath` exposes each as a property (`stddev`, `p25`, `p75`, `p95`, `p99`), matching the existing statistic accessors. Which statistics a given message path carries depends on the ingestion path that produced it, so every one may be `None` — a missing statistic never means zero.
  - `ClientViewingContext` gains `collection_ids` and `device_ids`, alongside the existing `dataset_ids` and `file_ids`. Pass them to `AgentThread.start` or `AgentThread.send_message` to tell the agent which collections and devices the caller is looking at, so it can resolve "this collection" or "this device" without the user spelling out an ID. Both default to empty, so existing callers are unaffected.
  - A file added to a session (experimental) may declare which slice of the file the session covers, through the optional `data_range` on `SessionFile`. Use it when one file holds several sessions' data: `(start, end)` marks the slice, `start` included and `end` excluded, counted in row positions from 0 for tabular files and in nanoseconds from the start of the media for video. A topic's data in that file is included only when it falls entirely inside the range; the range never cuts a topic's data in half. Leaving it unset contributes the whole file. `Session.list_files()` reports each file's `data_range`.
  - `roboto.experimental.ingest` (experimental) holds the types for declaring what already-uploaded files contain. A `Schema` lists one topic's columns as `Field`s, each carrying the source format's own type name, Roboto's `CanonicalDataType` for it, and an optional unit. A column carrying timestamps is declared by typing it `CanonicalDataType.Timestamp` and giving its `unit` a `TimeUnit` value (`"s"`, `"ms"`, `"us"`, or `"ns"`); there is no separate flag, and a `Timestamp`-typed field without a valid unit is rejected. Two declarations with identical fields are treated as the same schema, so repeat the same schema on every file that uses it.
  - `AgentThreadRecord` gains `origin` (`roboto.ai.agent_thread.ThreadOrigin`), naming the surface a thread was started from — `API` for Roboto's own surfaces (web app, CLI, SDK, direct REST), `SLACK` for a thread started by mentioning @Roboto in Slack. It is `None` on threads created before the field existed, which is equivalent to `API`. It is `None` for threads started from the web app or the API, which is every thread you create through the SDK. A thread with an `origin` is mirrored into a conversation Roboto does not own, so `AgentThread.send` and `send_text` raise the new `roboto.exceptions.RobotoThreadReadOnlyException` (HTTP 403) on one; reading, cancelling, and rating it are unaffected, and `fork` yields an ordinary writable thread with no `origin`.
  - `AgentThread.set_pinned(True)` pins a thread for you, promoting it to the top of your chat sidebar; `set_pinned(False)` unpins it. A pin is personal and invisible to everyone else, so anyone who can read a thread can pin it — unlike `set_visibility`, which stays creator-only. `AgentThreadRecord.pinned_at` reports when *you* pinned the thread, and is `None` if you have not; it is populated only on listing and search responses, which join your pins, and is `None` when a single thread is fetched by ID.
  - `roboto.query.SavedFilters` describes a set of filter controls — which field, which operator, which values — in the form a saved View stores. Anything that can call the API can now build a View, rather than only a client that already knows the filter UI's internal shape. Seven filter kinds (`string`, `numeric`, `metric`, `date`, `boolean`, `set`, `enum`) each accept only the operators that make sense for them, so a Boolean asking for `GREATER_THAN` is rejected rather than stored. `ViewDefinition.filters` is typed as this instead of an untyped mapping.
  - `roboto.query.FilterOnlyComparator` names the operators a saved filter needs that `Comparator` cannot express: `BETWEEN`, and the relative windows `TODAY`, `LAST_7_DAYS`, `LAST_30_DAYS`, `LAST_90_DAYS`, and `THIS_MONTH`. It exists so those gaps are visible in the SDK rather than implied, and is expected to shrink as `Comparator` grows to cover them.
  - `RobotoApiVersion.v2026_08_10` pins the cutover where `GET /v1/{datasets,events,files}/tags` gain `search`, `limit`, and `page_token` query parameters and return a paginated `{items, next_token}` object in place of a bare list of tag strings, so tag autocomplete can search server-side instead of loading every unique tag. Clients on earlier API versions continue to receive the bare string list via a server-side transform, capped to the first page.
  - RoboQL now supports Boolean literals — a bare, case-insensitive `true`/`false` parses as a Boolean, so you can filter Boolean-typed fields by value (e.g. `custom.is_nominal = true`). Quote the value (`field = "true"`) to compare against a field storing the literal text instead.
  - (experimental) `MetricDefinition` gains an optional `unit` — a free-form string naming what its values measure, e.g. `"%"`, `"ms"`, `"m/s"`. Omitting `unit` defaults to unitless, so existing metrics and callers are unaffected.
  - `AgentThread.set_visibility()` shares a thread with the caller's organization (`ThreadVisibility.ORG`) or takes it back to creator-only (`ThreadVisibility.PRIVATE`); visibility was previously fixed at thread creation. The new `AgentThread.visibility` property reports the current scope. Only the thread's creator may change it: Roboto admins read every thread but cannot re-scope one they did not create. Setting the scope a thread already has changes nothing.

## Bugs Fixed
  - Custom fields (experimental): the number of options for an enum custom field is now capped at 250, and duplicates are collapsed to one copy. Options with tabs, newlines, and a few other disallowed characters are rejected. Valid options get whitespace-trimmed and NFC-normalized.
  - Custom fields (experimental): an empty/whitespace-only display name or description defaults to `None`. When updating a custom field, this has the effect of clearing the existing value of the attribute, rather than changing it to a blank string.
  - `SigV4AuthDecorator` now resolves AWS credentials for each request instead of freezing them at construction, so a long-lived process signing with role credentials keeps working when those credentials rotate. Previously a process running longer than its credentials' lifetime — a container or VM, as opposed to a Lambda — would sign every subsequent request with an expired snapshot and be rejected until it restarted. Passing `credentials=` explicitly is unchanged: those are used exactly as given, and no session is consulted.

# 0.53.0
## Breaking Changes
  - `Session.list_files()` now yields `SessionFileView` — the contribution's file id and clipping range joined with display fields of the contributing file (name, dataset id, created/modified, tags, size, origination, relative path) — instead of `SessionFile`. `SessionFileView` is re-exported from the package root alongside the other session types.

## Features Added
  - New `Dashboard` feature allows creating, editing, and managing dashboards of Metrics
  - `HttpClient` accepts an optional `options=HttpClientOptions(...)` for transport behavior. `HttpRetryOptions` controls retries: `predicate` swaps the retry decision per client — the exported `never_retry` gives every request a single attempt, for calls whose side effect must not run twice — and `max_attempts` bounds the retry ladder (default 10, unchanged). `HttpLoggingOptions.scrub_headers` names additional headers (matched case-insensitively) whose values render as `*` wherever the client logs a request. `HttpRequest`, `HttpClientOptions`, `HttpLoggingOptions`, `HttpRetryOptions`, `RetryPredicate`, `never_retry`, and `is_expected_to_be_transient` (the default retry classification) are now exported from `roboto.http`.
  - Collections gain the `.name` and `.description` properties that every other entity already has.
  - Docstring fix (to support the agent doing RAG) about `Topic.get_data_as_df` array-typed-path contract.
  - `AgentThreadRecord` gains `created_by_principal`, the serialized `RobotoPrincipal` that started the thread (e.g. `user:jo@example.com`, `invocation:iv_123`). Where `created_by` is always a user id, `created_by_principal` records what drove the thread, such as a person, a device, or an action invocation. It is `None` on threads created before the field existed.
  - `Collection` gains `Session` (experimental) as a fourth resource type, alongside `Dataset`, `File`, and `Event`. `Collection.create(session_ids=[...])` seeds a Session-typed collection, and `add_session(session_id)` / `remove_session(session_id)` manage membership on an existing one; the new `sessions` property lists a collection's member session IDs. The CLI gains matching `--session-id`, `--add-session-id`, and `--remove-session-id` flags on `roboto collections create` / `update`. `RobotoSearch.find_sessions` also gains a `collection.collection_id` (alias `collection.id`) query field to find sessions belonging to a given collection. Session-typed collections are gated behind the `ReleaseSessions` feature flag; Roboto enables it per organization, so contact us to opt in.
  - Events can now be filtered and sorted by `duration` through `RobotoSearch.find_events` and the structured-query API.
  - `Skill.get_summary(skill_id)` fetches one skill's `SkillSummary` — its record, latest version, and your subscription row — in a single request, where you previously had to page `Skill.list_for_org()` to find it. `summary.subscription` is `None` unless you authored or subscribed to the skill. Raises `RobotoNotFoundException` if the skill isn't visible to you, same as `Skill.from_id()`.

## Bugs Fixed
  - `repr(HttpRequest)` and `HttpClient`'s DEBUG request logging no longer include `Authorization` header values; they render as `*`.
  - `Collection.changes(to_version=0)` now returns the empty range instead of the collection's entire history. `0` is a real collection version, but the previous check treated it as an omitted argument.

# 0.52.0
## Features Added
  - `roboto.experimental.video` now decodes H.265 (HEVC), VP9, and AV1 compressed-video topics in addition to H.264. A new `decode_stream(encoded_frames, codec)` decodes an in-order stream of encoded frames for any supported codec, and `decode_frames_in_range` gains a `codec` argument (defaulting to H.264). Pass one of the exported codec descriptors (`H264`, `H265`, `VP9`, `AV1`) as `codec`, or resolve one from a message's `format` field with `resolve_codec(format)`, which returns `None` for formats without a decode path; `supported_formats()` returns the format tokens that have one. `decode_h264_stream` behaves as before and is now a wrapper over `decode_stream`.
  - `roboto.experimental.video` gains dependency-free bitstream-inspection helpers for the new codecs, mirroring the existing H.264 helpers: `roboto.experimental.video.h265` (`find_nal_units`, `is_keyframe`, `NalUnitType`), `roboto.experimental.video.vp9` (`is_keyframe`), and `roboto.experimental.video.av1` (`find_obus`, `is_keyframe`, `Obu`, `ObuType`).
  - Restored the `roboto` console script removed in 0.51.0: `pip install roboto` installs the `roboto` command again, and `pipx install roboto`, `uvx roboto`, and `uv tool install roboto` are supported. The standalone CLI binaries (Homebrew, `.deb`, release executables) remain the recommended way to install the CLI, and `python -m roboto.cli` continues to work in any Python environment with the SDK installed.

## Internals
  - The REST endpoints behind tag autocomplete — `GET /v1/datasets/tags`, `/v1/events/tags`, and `/v1/files/tags` — now return a paginated `{items, next_token}` page rather than a bare list of strings, and accept optional `search`, `limit`, and `page_token` query parameters so a caller can narrow a large tag vocabulary on the server instead of fetching it whole. No SDK method calls these endpoints, and none ever has, so nothing in this package changes; the note is recorded for code that calls the REST API directly. `Skill.list_known_tags()` reads a different endpoint, `/v1/skills/tags`, which is unchanged.

# 0.51.0
## Breaking Changes
  - `pip install roboto` no longer installs a `roboto` console script, and `pipx install roboto` / `uvx roboto` / `uv tool install roboto` are no longer supported. Use the standalone CLI binaries (Homebrew, `.deb`, release executables), or `python -m roboto.cli` within a Python environment that has the SDK installed (e.g. `uv run --with roboto python -m roboto.cli ...`). Upgrading the package to this version does not remove a `roboto` executable that an earlier install already placed on your `PATH`; until you remove it, that stale copy keeps shadowing the standalone binary. Run `which -a roboto` to find stray copies, then `pip uninstall roboto` (or `pip install --upgrade roboto`, which now drops the script) in the offending Python environment, and `pipx uninstall roboto` / `uv tool uninstall roboto` for those tools.
  - `Topic.get_data` / `Topic.get_data_as_df` — `uint8`/octet fields of omgidl/ros2idl (DDS/CDR) topics now decode to `array.array('B')` instead of `bytes`, matching how the decoder already returns other numeric arrays. Code that read these fields as `bytes` should treat them as an `array.array` (call `.tobytes()` to recover the previous value).

## Features Added
  - `roboto.experimental.video`: a module that turns compressed-video topics into still frames. `decode_frames_in_range(load_messages, start_time, end_time)` decodes the H.264 frames within a time range, walking back to the preceding keyframe when the range starts mid-GOP so the leading delta frames remain decodable. `decode_h264_stream(encoded_frames)` decodes an in-order stream of Annex B-framed frames. Both yield `DecodedVideoFrame` objects that expose `log_time`, `is_keyframe`, `width`, and `height`, and convert to a PIL image via `to_image()` or an RGB numpy array via `to_ndarray()`. The module also exposes dependency-free H.264 bitstream helpers (`find_nal_units`, `is_keyframe`, `NalUnit`, `NalUnitType`). Decoding requires the new `roboto[video]` extra (PyAV, Pillow, numpy). This surface is experimental and may change.
  - `McapReader` now decodes `msgpack`-encoded MCAP channels (written by Roboto ingestion for compressed-video and similar topics) into nested dict/list/scalar values; previously it left them undecoded. Known limitation: msgpack-numpy ndarray fields (nested maps with binary keys) are not yet unwrapped; every other field of such a message decodes normally.
  - Layouts can now be grouped into folders. `LayoutRecord`, `CreateLayoutRequest`, and `UpdateLayoutRequest` gain a `folder` field — a free-form label (up to 120 characters) that groups the layout under a named folder; `null` (the default) leaves it ungrouped at the root. On `UpdateLayoutRequest`, omitting `folder` leaves the current folder unchanged, while an explicit `null` moves the layout back to the root.
  - `RobotoSearch.find_devices(query)` is now available to filter devices using a structured query, yielding `Device` instances.

## Bugs Fixed
  - Running any `roboto` CLI command no longer prints a spurious Pydantic `UserWarning` about the `model_profile` field conflicting with the protected `model_` namespace. The warning appeared only on Pydantic versions older than 2.10; the agent-thread models that carry `model_profile` now opt out of namespace protection, silencing it on every supported version.

# 0.50.0
## Breaking Changes
- `Session` and its records and operations moved wholesale from `roboto.domain.sessions` to `roboto.experimental.sessions`. The package-root re-exports (`from roboto import Session, SessionFile, SessionFileRecord, SessionRecord`) will keep working; only `roboto.domain.sessions...` imports need updating.
- `Session.list_topics()` now yields `roboto.experimental.topics.Topic` instances instead of `TopicIdentityRecord`s.

## Features Added
- Read topic data over a time window (experimental): an evolution of the existing `roboto.domain.topics.Topic.get_data` / `get_data_as_df` reads. Where the existing `roboto.domain.topics.Topic` is scoped to a single file, `roboto.experimental.topics.Topic` is a durable handle to one topic — a single recorded stream of data, such as a sensor channel — that stays valid across every file carrying that stream. Load one with `Topic.from_id("ti_...")`, then read its rows within a time window with `get_data(start_time=..., end_time=...)`, which yields the same `(timestamp, record)` pairs as before — `timestamp` an integer of nanoseconds since the Unix epoch, `record` a dict of the topic's fields. The same window is also available as a pandas DataFrame from `get_data_as_df(...)` and, new on this surface, as Apache Arrow `RecordBatch`es from `get_data_as_record_batches(...)` for columnar processing. Narrow any read to just the fields you need with `fields_include` / `fields_exclude`. Rows come back in the order they were recorded, not necessarily time order. This surface is in progress and may change.
- `Session.get_topic(topic_name)` (experimental) returns the single topic reachable from a session by exact name in one request, raising `RobotoNotFoundException` when none matches — including when the topic exists in the org but does not contribute within the session's window. It is the by-name complement to `Session.list_topics()`.
- Skills can now declare the topics their procedure investigates. `Skill.create`, `CreateSkillVersionRequest`, and `UpdateSkillVersionRequest` accept `relevant_topics` (a list of topic names such as `"/imu/data"`), surfaced on `SkillVersionRecord.relevant_topics`. When the chat AI loads a skill with a dataset in scope, it resolves each name to that dataset's topic schema and returns them alongside the skill body in one tool result, sparing a follow-up `get_topic_schema` turn; names not present in the dataset are reported inline and never fail the load. The SDK stores the list as given (the web UI populates it by scanning the body for `/topic` references).

## Internals
  - `roboto.ai.core` gains two content types on the public `AgentContent` union: `AgentDeletedContent` (`content_type` `deleted`) and `AgentCompressionFillerContent` (`content_type` `compression_filler`), both re-exported from `roboto.ai.core.record` and `roboto.ai.agent_thread`. They are tombstones the server's thread-compression pass writes into a compressed thread variant: `AgentDeletedContent` marks a content block the pass removed, and `AgentCompressionFillerContent` stands in for a message the pass emptied so it keeps its turn and role. Neither carries a payload, and neither appears in the verbatim `original` thread the SDK and UI read; both exist only to type the compressed variant. Groundwork for thread compression; no change to what your reads return.

# 0.49.0
## Breaking Changes
  - `roboto.fs` is renamed to `roboto.storage`. The top-level re-exports (`roboto.FileService`, etc.) are unchanged.
  - `Dataset.get_summary()` no longer generates a summary as a side effect of reading. It now returns the dataset's existing AI summary, or raises `RobotoNotFoundException` if the dataset has never been summarized; call `Dataset.generate_summary()` to create one. Previously, reading a summary-less dataset implicitly kicked off generation (spending AI credits) — so a read can no longer spend credits, and generation is always explicit.

## Features Added
  - `QueryTarget.Devices` is now a supported search target. Devices can be queried via `RobotoSearch` with filters, sort, and pagination using the same `QuerySpecification` interface as datasets, events, collections, and sessions.
  - `Dataset.rename_file(file_id, new_path)` moves or renames a file within a dataset. Pass a `new_path` with fewer components to move the file up the directory tree, one of the same depth with a different name to rename it in place, or one under a sibling directory to move it laterally. The file's storage URI is unchanged; only its logical location shifts.
  - `Dataset.rename_directory(old_path, new_path)` moves or renames a directory within a dataset, carrying all of its contents. The same depth-change semantics apply.
  - CLI: `roboto datasets rename-file -d <dataset-id> -f <file-id> -p <new-path>` exposes `rename_file` on the command line.
  - CLI: `roboto datasets rename-directory -d <dataset-id> -o <old-path> -p <new-path>` exposes `rename_directory` on the command line.

## Bugs Fixed
  - Invoking an action with no input data (for example, running it against just a dataset) no longer fails. `prepare_invocation_input_data` now always writes the input manifest, treating no input (`input_data=None`) the same as empty input; previously it skipped the manifest entirely for no-input invocations, so the action later crashed reading it.
  - `InvocationContext.get_input()` now tolerates a missing or empty input manifest, returning an empty `ActionInput` instead of raising `FileNotFoundError`. A manifest that is absent entirely is logged as a warning, since setup is expected to always write the file.

## Internals
- MCAP and Parquet fetch-and-decode mechanics moved out of `roboto.domain.topics` into two new packages: `roboto.storage` holds the byte-transport (HTTP range streaming, chunk-index prefetch, cache/stream/download selection) and `roboto.formats` holds the format decoding (parsing, field projection, timestamp extraction, table transforms).

# 0.48.0.post1
## Breaking Changes
  - `RobotoStatementTimeoutException` is renamed to `RobotoOperationTimeoutException` in `roboto.exceptions`. The new name reflects that it signals any operation aborted by Roboto's bounded timeout. Behavior is unchanged, and it still carries HTTP status 504. No alias is kept for the old name, so update imports to `from roboto.exceptions import RobotoOperationTimeoutException`.

## Features Added
  - `Topic.get_data` and `Topic.get_data_as_df` now decode topics recorded from DDS, those whose schema is OMG IDL (`omgidl`) or its ROS 2 dialect (`ros2idl`) with CDR payloads, as produced by stacks such as RTI Connext. Plain CDR, XCDR1 parameter-list (`@mutable`) framing, and the XCDR2 family all decode, alongside the existing ROS 1 and ROS 2 message formats. When a message carries a field whose CDR encoding is undefined (a `wstring` or `wchar` in a non-recoverable position), the reader skips that message and continues reading the file.
  - `QuerySpecification` accepts a new optional `max_results` field that caps the total number of results returned across all pages of a query.
    - Defaults to `None`, which returns the full result set.
    - Distinct from `limit`, which is the per-page size.
    - `max_results` is only honored by `RobotoSearch`'s `find_*` methods. The per-domain `.query()` methods that also accept a `QuerySpecification` — such as `Dataset.query()` — ignore it.
  - Custom fields in search (experimental): custom fields can now be used in search, both as query filters and sort keys. Filter by a custom field with `<entity>.custom.<name>` (the entity prefix is optional) — e.g. `dataset.custom.drone_id` or `custom.severity` — and sort by `custom.<name>` (no entity prefix). Works both with structured `QuerySpecification` objects and RoboQL queries, across `Dataset`, `Event`, `Collection`, and `Session` searches. Each custom field type allows the comparators that make sense for it — ranges on Number and Timestamp, substring matching on String, equality and null checks everywhere.
  - `Event.delete_many(event_ids)` deletes multiple events in one call. As with `Event.delete()`, you can delete any event you're able to manage; if the list includes an event you can't delete, the request is rejected and nothing is deleted. IDs that don't exist are ignored, so the call is idempotent and safe to retry. You can pass any number of IDs — large lists are batched automatically. Deletion cannot be undone.
  - `AgentThread.goals` (experimental): new property returning the goals declared across a thread's turns, oldest first, as `AgentThreadGoalView` wrappers. Each wrapper exposes the goal's `status` (an `AgentGoalStatus`: `PENDING`, `ACHIEVED`, or `FAILED`), reconstructs the original declaration via `to_agent_goal()`, and resolves the achieve-tool invocation the agent submitted for the goal: `achieve_tool_use`, `achieve_tool_result`, and a typed `result`. `result` is a `GoalResult`, one of `DatasetSummaryGoalResult`, `DatasetTriageGoalResult`, or `CreateEventsGoalResult`, exposing the agent's submitted payload as typed fields (e.g. `result.summary`, `result.label_decisions` / `result.applied_labels`, `result.events`) instead of a raw dict. The property returns an empty list when the thread declared no goals or when the record was fetched without loading them; call `refresh()` if you expect goals to be present. Import the result and input models from `roboto.ai.goals`: `GoalResult`, the three `*GoalResult` models, the matching `DatasetSummaryAchieveInput` / `DatasetTriageAchieveInput` / `CreateEventsAchieveInput` models, `EventSpec`, `LabelDecision`, and `AgentGoalStatus`.
  - `AgentThreadGoalRecord` gains an `achieve_tool_use_id` field pointing at the achieve-tool invocation associated with the goal, so callers can locate the exact `tool_use` / `tool_result` pair in the thread's message stream without scanning by tool name.
  - `S3BucketIntegrationRecord` now surfaces bring-your-own-bucket health-check results: a new `last_health_check` field holding a new `S3BucketHealthCheck` model (`reason_code`, `aws_error_code`, `message`, and a per-probe `probes` map), plus a `status_last_updated` timestamp for when the most recent check ran. `status` may now also be `unverified` (registered, never checked) or `unknown` (a check that reached no verdict), alongside `healthy` and `unhealthy`. Both new fields are `None` until the first check.
  - `Agent.launch()` accepts an optional `analysis_scope` that pins the analysis window for the launched thread, backed by a new `analysis_scope` field on `LaunchAgentRequest`. The scope is a `roboto.ai.core.AnalysisScope` with `start_time`/`end_time` bounds in nanoseconds since the Unix epoch. A supplied scope overrides the one in the agent's authored `request_template`; omitting it leaves the template's scope unchanged. Because of this, `launch()` cannot clear a window the author pinned in the template.
  - `roboto.http` now exports `InvalidPaginationTokenError`, which `PaginationToken.from_token` raises when a pagination token is malformed or uses an unsupported scheme (previously a bare `ValueError`). The new error subclasses `ValueError`, so existing `except ValueError` handling still works; callers that need to detect an invalid token can catch it directly.

## Bugs Fixed
  - `Dataset.upload_file` and `Dataset.upload_files` could intermittently fail with a server error when the same destination path was uploaded concurrently (e.g. retrying an upload, or parallel uploads of the same path); these concurrent same-path uploads are now serialized and succeed.
  - A large `include_patterns`/`exclude_patterns` list passed to `Dataset.list_files`, `Dataset.download_files`, or `Dataset.delete_files` previously failed with a server error; lists of hundreds of patterns now succeed.
  - `roboto.time.to_epoch_nanoseconds` now converts `datetime` and ISO-8601 string inputs exactly, preserving their full microsecond resolution. Previously a floating-point seconds multiply rounded away the low-order nanosecond digits of sub-second values (for example, a microsecond-precision timestamp could land on `...001024` instead of `...001000`). Integer inputs were unaffected.

## Internals
  - Message-content primitives (`AgentTextContent`, `AgentToolUseContent`, `AgentToolResultContent`, `AgentErrorContent`, `AgentContentType`, and the `AgentContent` union) now live in a new `roboto.ai.core.content` module and are re-exported from `roboto.ai.core.record`, so existing import paths keep working. This breaks a circular dependency and supports the typed goal-result models.

# 0.47.0
## Features Added
  - New `roboto.experimental` namespace for SDK APIs whose shape may change before stabilizing.
  - `RobotoSearch.find_sessions` (experimental) now supports searching sessions by their metrics with the `metric.<name>` query field.

## Bugs Fixed
  - Client-side tools dispatched by `AgentThread.run()` now receive only their declared parameters. The server adds an internal `_compression_intent` field to every tool's input schema; `run()` previously passed it to the callback, raising `TypeError` for any strict-signature client tool (the only kind `ClientTool.from_function` produces).

## Internals
  - `Topic.get_data` and `Topic.get_data_as_df` are now faster.

# 0.46.0
## Breaking Changes
  - **Name swap:** `AgentThread` is the new name for the wrapper class previously called `AgentSession`, and the matching record is `AgentThreadRecord` (previously `AgentSessionRecord`). This continues the 0.41.0 `Chat → AgentSession` rename. Update imports:
    - `from roboto.ai import AgentThread` (was `AgentSession`)
    - `from roboto.ai.agent_thread import ...` (was `roboto.ai.agent_session`)
    - `AgentThreadRecord` (was `AgentSessionRecord`)
    - `AgentThreadDelta` / `AgentThreadStatus` / `AgentThreadGoalRecord` (was `AgentSession*`)
    - `ThreadVisibility` (was `SessionVisibility`)
    - `StartAgentThreadRequest` (was `StartAgentSessionRequest`)
    - `ForkAgentThreadRequest` (was `ForkChatRequest`)
    - `LaunchAgentRequest` (was `InvokeAgentRequest`)
    The SDK surface keeps no `AgentSession*` aliases; update imports in the same release.
  - `AgentThreadRecord.thread_id` replaces `AgentSessionRecord.session_id`. The constructor still accepts the legacy `session_id` and `chat_id` spellings via Pydantic `AliasChoices`, so `AgentThreadRecord(session_id=..., ...)` still works; the canonical Python attribute is `record.thread_id`, and `record.session_id` raises `AttributeError`. The `chat_id` computed-field alias is gone; pre-v2026_05_20 callers still receive `session_id` and `chat_id` in API response bodies via a server-side transform. `forked_from_session_id` becomes `forked_from_thread_id` with the same input-alias compatibility.
  - `Agent.invoke()` is renamed to `Agent.launch()`, and `InvokeAgentRequest` to `LaunchAgentRequest`. The route path moves from `POST /v1/ai/agents/<agent_id>/invoke` to `…/launch`. `Invocation` continues to mean an action run; `launch` now applies to starting an agent thread. The legacy `/invoke` URL was removed outright (it was a feature-flagged developer-only preview with no in-the-wild callers); upgrade `Agent.invoke()` call sites to `Agent.launch()`.

## Features Added
  - `RobotoApiVersion.v2026_05_20` pins the cutover where `chat_id` and `session_id` become `thread_id` on the wire, `/v1/ai/chats` becomes `/v1/ai/threads`, and agent `invoke` becomes `launch`. Clients on older API versions continue to receive `session_id` (and `chat_id`) in response bodies via a server-side transform and may keep calling the legacy `/v1/ai/chats` paths, which remain registered as aliases on the same handlers. Clients on v2026_05_20 or newer must use `/v1/ai/threads`; the legacy `/chats` paths return `RobotoDeprecatedException` (HTTP 400) for v2026_05_20+ callers so the entire legacy alias block can be deleted in one diff once pre-v2026_05_20 leaves the support window.
  - Experimental: new `AgentThreadSubject` pydantic model under `roboto.ai.agent_thread`. The service appends one subject row per dataset or file an agent thread references via a goal target or `ClientViewingContext`, and `POST /v1/ai/threads/search` gains a `subject_id` filter that returns threads referencing a given association id (e.g. `ds_xxx`). The SDK exports the model now; dedicated SDK search helpers are a follow-up.

# 0.45.0
## Features Added
  - **AI Skills.** Stored, versioned procedures the chat AI can apply during a conversation. Authors create a skill plus its first version with `Skill.create(name=..., body=..., description=..., accessibility=..., tags=[...])` and add versions in place with `Skill.create_version(...)`. Visibility has three tiers: `private` lets only the author see, edit, or invoke the skill; `org` lets every member of the owning org see and invoke it, but only the author edit it; `org-editable` lets every org member see and invoke it, and any member who subscribes can also edit its versions, name, and tags. On every tier, only the author can change a skill's accessibility or delete the skill. Authors are auto-subscribed at create time with the latest version pinned; other org members subscribe explicitly via `Skill.subscribe()` and pin a version for AI auto-invocation via `Skill.set_ai_version(n)` (or `None` to keep the subscription but hide the skill from the AI's `load_skill` tool — manual chip-invocation in chat still works). List skills with `Skill.list_for_org(scope=...)`, where `SkillListScope.Personal` is "authored or subscribed" and `SkillListScope.Org` is "org-shared, not authored." Skill names must match `^[A-Za-z0-9_-]+$` so they can be inserted from the chat composer's inline `/skill-name[@vN]` slash syntax. Skills carry free-form `tags` for organizational grouping (set at create or via `UpdateSkillMetadataRequest.put_tags` / `remove_tags`; `Skill.list_known_tags()` returns the distinct set visible to the caller).
  - **Per-session AI skill set.** `AgentSession.start(available_skills=[...])` accepts an explicit list of `AvailableSkillSpec` (skill id + optional version) defining exactly which skills the chat AI may auto-invoke for that session, replacing the registry it would otherwise derive from the caller's skill subscriptions. Each entry may reference any org-shared skill or the caller's own private skill, at any version — visibility only, no subscription required — and the caller's per-user `ai_version` pins are bypassed. One version per skill (duplicate `skill_id` is rejected). Passing `[]` gives the session's AI no auto-invokable skills; omitting the argument keeps the existing subscription-derived behavior. The set is resolved once at session start and frozen onto the session, so later subscription changes and skill-body edits do not leak into it. It is session configuration, not a turn trigger — a session still needs a message, goal, or invoked skill to start. Import `AvailableSkillSpec` from `roboto.ai.agent_session`.
  - **Filter Sessions via `RobotoSearch.find_sessions` (experimental):** new generator method on `RobotoSearch` that iterates `Session` instances matching a structured query.
  - (experimental) Added `roboto.domain.metrics` module with `Metric` and `MetricDefinition` classes for recording and querying time-series metric data. `MetricDefinition` manages metric schemas. `Metric` supports inserting individual observations, querying raw data points by time range, and aggregating data into calendar-period buckets (daily through yearly) with sum, mean, max, min, and count.
  - **Agents (experimental):** New `roboto.ai.agent` package for storing parameterized agent templates that can be invoked against new subjects without re-authoring the request. `AgentRecord` captures a `StartAgentSessionRequest` (in a field named `request_template`) alongside declared `TemplateVariable` entries. `{{name}}` placeholders embedded in any string value within the request template are substituted client-side at invoke time via `resolve_agent(agent, values)`. Unresolved required values raise `UnresolvedAgentVariablesError`; stray values for variables the agent doesn't declare raise `UnknownAgentVariablesError`. Both subclass `AgentResolutionError`. `TemplateVariableType` (`STRING`, `DATASET_ID`, `DEVICE_ID`) carries a UI hint; for typed values, the invoke handler verifies the referenced entity exists in the caller's org and surfaces a `RobotoInvalidRequestException` if it does not. `CreateAgentRequest`, `UpdateAgentRequest`, and `InvokeAgentRequest` carry the wire payloads for the corresponding `/v1/ai/agents` routes. `extract_placeholders(body)` returns every placeholder name referenced in a request body, useful for tools that inspect or validate a template before saving. Access is enabled per organization; contact us to opt your org in.
  - `StartAgentSessionRequest.visibility` (a new `SessionVisibility` enum: `PRIVATE` or `ORG`) controls who can read a session after it is created. It defaults to `PRIVATE` so a chat started against `POST /chats` does not leak to the rest of the org until the caller opts in. The agent invoke flow defaults to `ORG` because agents exist to share workflows across teammates. Import via `roboto.ai.agent_session.SessionVisibility` (canonical) or `roboto.ai.core.SessionVisibility`.
  - `AgentSessionRecord` exposes two new fields. `visibility` (a `SessionVisibility`) mirrors the value the session was created with. `created_from_agent_id` holds the id of the agent that produced this session via the invoke flow, or `None` for sessions started directly through `POST /chats`. Both are immutable over the life of the session; forks land as `PRIVATE` with `created_from_agent_id=None` regardless of the source session's values.
  - **`CreateEventsGoal` (experimental):** New entry in the closed `roboto.ai.goals.AgentGoal` union, with discriminator `GoalType.CREATE_EVENTS`. Directs the agent to investigate the dataset identified by `dataset_id` and create events on it drawn from a required `event_vocabulary` (a `{event-type-name: description}` map) — the achieve-tool constrains every created event's `name` to a vocabulary key, so the agent can only file events of the declared kinds. An optional `tag_vocabulary` (a `{tag: when-to-apply description}` map) lets the agent attach a subset of the declared tags to each event it creates. `collection_id` is optional: when set, every created event is also added to that event collection; when omitted, events are created on the dataset but not filed into any collection. An optional `event_focus_prompt` (1-4000 chars) layers extra natural-language steering on top of the vocabularies. The dataset id — and the collection id when set — are baked into the achieve-tool so the agent cannot redirect the work.
  - `TemplateVariableType.COLLECTION_ID` joins `DATASET_ID` and `DEVICE_ID` as a typed agent-template variable, and the new `TemplateVariable.collection_content_type` optionally annotates such a variable with the kind of collection it expects (e.g. `event`) so the launch UI can scope its collection picker accordingly. The invoke handler verifies the referenced collection exists in the caller's org before starting the session, failing fast with a 400 instead of letting the agent crash mid-tool-call.
  - Custom fields (experimental): Customer-defined, typed schema-extension points on `Dataset`, `Event`, `Device`, `Collection`, and `Session`, scoped per organization and Roboto entity type. Org admins define a custom field with `CustomField.create(...)`, specifying its name and one of five types: Number, String, Boolean, Timestamp, or Enum. Once defined, anyone in the org can set or change values for it using the existing entity-create and entity-update methods (`Dataset.create`, `Event.update`, etc.). An entity's full set of custom-field values is available on the entity instance via a `custom_fields` property. Custom fields are the first-class lane for attributes that need to participate in search and sort (search support arrives in a follow-up release); reach for `metadata` for opaque annotations.

# 0.44.2
## Bugs Fixed
  - `AgentSession.submit_client_tool_results` now advances the session's local status to `ROBOTO_TURN` on success. Previously, after a turn that mixed server and client tools, the local status stayed on `CLIENT_TOOL_TURN`, so `run()` re-dispatched the same client tools and re-POSTed their results; the duplicate POST raised `RobotoInvalidRequestException` from the server.

# 0.44.1
## Features Added
  - None
## Bugs Fixed
  - `RobotoContextTooLongException` deserializes cleanly against pre-0.44.0 servers.

# 0.44.0
## Breaking Changes
  - `RobotoContextTooLongException` no longer accepts `estimated_tokens` and `max_tokens` constructor arguments, no longer exposes `estimated_tokens` / `max_tokens` properties, and no longer extends the `to_dict()` payload with those fields. The exception now serializes as the standard `{error_code, message}` shape like every other `RobotoDomainException`. The internal heuristic estimate and the model's context limit were never billing-grade values and were not consumed by any in-tree caller; they remain visible in CloudWatch failure logs (see `BedrockLLMBackbone`). Callers that need usage telemetry will get it through a separate, dedicated channel rather than by introspecting the error.

## Features Added
  - **Sessions are queryable (experimental):** Sessions join datasets, files, topics, and events as a queryable resource. You can sort and paginate listings server-side by start time or duration. Higher-level query helpers in the SDK will arrive in a follow-up release. Sessions remain experimental, and Roboto enables access per organization; contact us to opt your org in.

## Bugs Fixed
  - Concurrent `Topic.get_data_as_df` calls no longer race on cache-directory creation (which previously raised `FileExistsError` from `mkdir`) or on Parquet downloads. Within a process, downloads of the same representation are deduped via a per-path lock; across processes, an atomic temp-file-plus-rename write guarantees readers never observe a partial file.

# 0.43.0
## Breaking Changes
  - `ClientToolSpec.name` must now match `^client_[a-z][a-z0-9_]*$`. Names without the `client_` prefix are rejected at deserialization, so the API returns 400 before persisting any session state. This also applies to `@client_tool`-decorated functions, since the decorator defaults the tool name to `fn.__name__`. Either rename the function (e.g. `def client_store_fact`) or pass `name="client_..."` explicitly.
  - `AgentSessionGoalRecord` now requires a `message_sequence_num: int` field. The field is the session-wide message-sequence index of the USER-role message that declared the goal — clients use it to render goal chips adjacent to the turn they were attached to. External consumers that construct the record directly (test fixtures, custom middleware, recorded API responses) will fail validation on upgrade until they pass the new field. In-tree consumers and SDK-side `to_agent_goal()` re-hydration from server responses are unaffected, since the server populates the field on every record it emits.

## Features Added
  - **Sessions (experimental):** Represent an activity — a drone flight, a vehicle drive, a robot arm test run — as a `Session`: an operational time window over zero, one, or many Devices. Create one with `Session.create(name=..., device_ids=...)`, or use the anchored-convenience constructors `Device.create_session(name=...)` and `Dataset.create_session(name=..., ...)`. Include files with `Session.add_file` / `add_files` (each optionally narrowed to a sub-window via `range_min_timestamp_ns` / `range_max_timestamp_ns`), and attach to additional devices via `Session.attach_to_device(device_id)`. Each operation has a symmetric counterpart: removing files, detaching devices, renaming, and deleting. The Session's `min_timestamp_ns` / `max_timestamp_ns` (Unix-epoch nanoseconds) are recomputed on every file add or remove. Enumerate Sessions with `Session.for_dataset`, `Session.for_org`, `Dataset.get_sessions()`, or `Device.list_sessions()`. `Session.list_topics()` iterates every topic reachable through the Session's files, turning "all signals from this flight / drive / run" into a single query. Because a Session is bounded by the activity rather than the recordings, it may span many files or cover only part of one.
  - **Content-addressable topic schemas (experimental):** A `Topic`'s field structure is now represented as a `TopicSchema` identified by a checksum over its fields. Topics whose fields share the same names, paths, and data types reference the same schema within an organization. Retrieve a topic's schema with `Topic.get_schema()`, or look one up directly via `TopicSchema.for_topic(topic_id)` / `TopicSchema.from_id(schema_id)`. Lays the groundwork for finding every topic in an org with a given shape, and for comparing topics across files, sessions, and devices.
  - **Timeline offsets on files (experimental):** `File.set_timeline_offset(unix_epoch_offset_ns, ...)` — and its batched counterpart `File.set_timeline_offsets([...])` — project a file's stored partition timestamps onto Unix-epoch wall-clock (`session_time_ns = stored_time_ns + unix_epoch_offset_ns`) without re-ingest. An offset can be narrowed by topic (`topic` / `topic_name`) and by timeline source (`timeline_source` / `timeline_source_name`). `TimelineSourceKind` names where a timestamp comes from: a field in the message (`schema_field`, e.g. `header.stamp`), the recorder-assigned log time (`message_log_time`), or the publisher-assigned publish time (`message_publish_time`). The same API is available on `Topic` (`Topic.set_timeline_offset` / `set_timeline_offsets`), auto-scoped to a single topic. A bag that starts at zero, a sensor that logs in device-uptime, or a camera that lags the IMU by a few milliseconds can be reconciled after ingest. Session aggregate bounds read from these projected timestamps.
  - `AgentSession.submit_feedback(message_sequence_num, sentiment, categories=[...], notes=None)` persists structured feedback on a specific assistant message. `sentiment` is `FeedbackSentiment.POSITIVE` or `NEGATIVE`; `categories` is a list of `FeedbackCategory` values (multi-select) that must match the selected sentiment. `FeedbackCategory.OTHER` requires `notes`. Resubmitting from the same user on the same message overwrites `sentiment`, `categories`, and `notes` on the existing row rather than creating a duplicate. Replaces the previous write-only Slack-only feedback path with a durable, queryable record.
  - `AgentSession.fork(message_sequence_num)` forks a session at a given message into a new session owned by the caller. Available to the session's creator for their own sessions and to Roboto admins for any session. The new session carries the source's `org_id`; lineage is tracked on `AgentSessionRecord.forked_from_session_id` and `AgentSessionRecord.forked_from_message_sequence_num`.
  - Added `FeedbackSentiment`, `FeedbackCategory`, `SubmitFeedbackRequest`, and `AdminUpdateFeedbackRequest` models to `roboto.ai.agent_session` for programmatic access to AI chat feedback. (`AgentFeedbackRecord`, the admin-triage shape, is intentionally not part of the public surface.)
  - `AgentSessionRecord` now exposes `forked_from_session_id` and `forked_from_message_sequence_num` fields. Both are `None` for sessions that were not created via `AgentSession.fork`.
  - `Topic.get_data` and `Topic.get_data_as_df` accept an optional `representation_selector` (`RepresentationSelector`) to choose among multiple representations. Defaults to raw, untransformed data; filter on `content_format` or `transformations` to match a specific encoding or transformation pipeline.
  - `Topic.set_default_representation` and `Topic.add_message_path_representation` accept optional `format` and `transformations` to describe a representation.
  - `RepresentationRecord` exposes a new `format` field.
  - New `AnalysisScope` in `roboto.ai.core` captures a time window (`start_time` / `end_time`, nanoseconds since the Unix epoch) that scopes which data the agent's tools may consider. `AgentSession.start()`, `.send()`, and `.send_text()` accept an `analysis_scope=` kwarg; on `start` it attaches the scope to the session, on `send`/`send_text` an explicit value replaces the session's current scope (omitting the kwarg leaves it untouched). The scope is persisted on the session and delivered to every tool invocation on the server side. The `analyze_topic` tool honors the scope today by clamping topic data to the window; other tools will opt in as they adopt.
  - New `RobotoFeatureNotAvailableException` in `roboto.exceptions`, raised when an API call targets a route gated by a feature flag that is not enabled for the caller.
  - **AgentSession can now declare hard, verifiable goals per turn.** New `goals=` parameter on `AgentSession.start()`, `.send()`, and `.send_text()` accepts a list of typed goal models from the closed `roboto.ai.goals.AgentGoal` union (capped at 5 entries per turn). The agent runner enforces achievement: it re-prompts up to 3 times if the LLM ends a turn without satisfying every declared goal, then reports the new `AgentSessionStatus.GOALS_FAILED` terminal status (which `AgentSession.run()` raises as a typed `RobotoAgentGoalsFailedException`). The `message`/`messages` parameter becomes optional when `goals=` is provided. Authorization runs at goal-registration time so the caller gets a fast 401 before any model resources are spent. Two concrete goals ship in this release: `DatasetSummaryAgentGoal(dataset_id, summary_format_spec_prompt)` directs the agent to investigate a dataset and persist a summary via `SummaryService.set_dataset_summary`; `DatasetTriageGoal(dataset_id, label_vocabulary={label: description, ...})` directs the agent to deliberate over each label in the vocabulary and apply the ones that fit (zero or more) as dataset tags. `AgentSessionRecord.goals` exposes the per-goal status (`PENDING` / `ACHIEVED` / `FAILED`) and `AgentSessionGoalRecord.to_agent_goal()` re-hydrates the typed goal model from any read. Each `AgentSessionGoalRecord` also carries a `message_sequence_num: int` identifying the USER-role message that declared the goal, so clients can render goal chips adjacent to the turn they were attached to. The corresponding `AgentSessionDelta` now exposes a `goals` field so streaming consumers see goal-status transitions land alongside message and status deltas.
  - `RobotoLLMContext` is deprecated and renamed to `ClientViewingContext` (parameter `client_context` on `AgentSession.start()`, `.send()`, and `.send_text()`, replacing the previous `context=` parameter that took a `RobotoLLMContext`). The rename disambiguates the SDK call site now that `goals` and `analysis_scope` are also turn-level inputs — "context" was overloaded to mean both the goal/scope envelope and the client-side viewing state. The old name is still importable from `roboto.ai.core` and `roboto.ai.agent_session` for one release as a re-export of `ClientViewingContext`; the wire-format `client_context` field also accepts the legacy `context` JSON key for one release via `validation_alias=AliasChoices("client_context", "context")`. Both compatibility aliases will be removed in a subsequent release — migrate to `from roboto.ai.core import ClientViewingContext` and pass it via `client_context=`.
  - Collections now support `event` resources. `CollectionResourceType.Event` works with `Collection.create(resource_type=CollectionResourceType.Event, event_ids=[...])`, `Collection.from_id(...)`, and the `Collection.events`, `add_event()`, and `remove_event()` helpers. The CLI now accepts `--event-id` for `roboto collections create` and `--add-event-id` / `--remove-event-id` for `roboto collections update <collection_id>`.

## Behavior Changes
  - **BYOB cross-org access now returns `RobotoNotFoundException` (404) instead of `RobotoUnauthorizedException` (401).** With the integrations table now keyed on `(org_id, bucket_name)`, looking up a bucket registered only under another org no longer surfaces that registration's existence; it surfaces as not-found, matching the security posture of the rest of the org-scoped API. Affects `Dataset.get_single_bucket_creds`, `File.import_one`, `File.import_batch`, `File.delete`, `File.get_signed_upload_url`, and `File.get_signed_url`. Callers that switch on exception type (rather than surfacing the message) should add `RobotoNotFoundException` to their cross-org branch.

## Bugs Fixed
  - `get_data` and `get_data_as_df` now return full-resolution image data for topics ingested by the updated `ros_ingestion` action; previously they returned a downsampled, re-encoded version.

# 0.42.0
## Features Added
  - New `AnalysisScope` in `roboto.ai.core` captures a time window (`start_time` / `end_time`, nanoseconds since the Unix epoch) that scopes which data the agent's tools may consider. `AgentSession.start()`, `.send()`, and `.send_text()` accept an `analysis_scope=` kwarg; on `start` it attaches the scope to the session, on `send`/`send_text` an explicit value replaces the session's current scope (omitting the kwarg leaves it untouched). The scope is persisted on the session and delivered to every tool invocation on the server side. The `analyze_topic` tool honors the scope today by clamping topic data to the window; other tools will opt in as they adopt.
  - New `RobotoFeatureNotAvailableException` in `roboto.exceptions`, raised when an API call targets a route gated by a feature flag that is not enabled for the caller.

# 0.41.0
## Breaking Changes
  - **Name swap: `AgentSession` now refers to the wrapper class (previously called `Chat`), not the Pydantic record.** On 0.39.0 `AgentSession` was the record type at `roboto.ai.core.AgentSession`; in this release the record is renamed to `AgentSessionRecord` and `AgentSession` is reused as the wrapper class. Code that followed 0.39.0's guidance and did `AgentSession(session_id=..., messages=...)` will now hit a wrapper-class constructor with a completely different signature. Update to `AgentSessionRecord(...)` when constructing the record directly.
  - Renamed `Chat` to `AgentSession` and dropped all `Chat*` backwards-compatibility aliases on the Python SDK surface. Update imports:
    - `from roboto.ai import AgentSession` (was `Chat`)
    - `from roboto.ai.agent_session import ...` (was `roboto.ai.chat`)
    - `AgentSessionRecord` (was `ChatRecord`)
    - `AgentMessage` / `AgentRole` / `AgentSessionStatus` / ... (was `ChatMessage` / `ChatRole` / `ChatStatus` / ...)
    - `AgentEvent` / `AgentTextDeltaEvent` / ... (was `ChatEvent` / `ChatTextDeltaEvent` / ...)
    - `StartAgentSessionRequest` (was `StartChatRequest`)
    - `AgentToolDetailResponse` (was `ChatToolDetailResponse`)

    The HTTP API is unchanged: URLs still live under `/v1/ai/chats/...` and responses still include `chat_id` for wire compatibility.
  - Consolidated the `AgentSession` control-flow surface down to two methods: `run()` (driver — auto-dispatches registered client-side tools until user turn; takes a single `on_event` callback) and `events()` (observer — yields `AgentEvent` objects until the session pauses, no auto-dispatch). Removed `await_user_turn()`, `stream()`, and `stream_events()` — their behaviors are composable from `run` / `events`.
  - Removed `is_user_turn()`, `is_client_tool_turn()`, and `is_roboto_turn()` inspectors — compare `session.status` against `AgentSessionStatus.XXX` directly when branching is needed.
  - Removed the `chat_id` property on the wrapper class; use `session_id`. (`chat_id` remains on `AgentSessionRecord` as a computed alias for wire compatibility.)

## Features Added
  - `AgentSession.start()` / `send()` / `send_text()` now accept `client_tools=[ClientTool | ClientToolSpec]` to register client-side tools the agent can invoke.
  - New `AgentSession.run()` drives the session until user turn, auto-dispatching registered client-side tools and optionally emitting progress via an `on_event` callback that receives typed `AgentEvent` objects (text deltas, tool uses, tool results, errors).
  - New `AgentSession.events()` yields `AgentEvent` objects as the agent generates, without auto-dispatching; callers observe and handle tool-dispatch manually by calling `submit_client_tool_results()` between `events()` loops.
  - New `ClientTool` class and `@client_tool` decorator wrap a Python callable as a client-side tool; name, description, and JSON Schema are inferred from the function's `__name__`, docstring, and type hints. Per-parameter descriptions are parsed from the docstring's `Args:` section (Google style); `typing.Annotated[T, pydantic.Field(description=...)]` and `param: T = pydantic.Field(description=...)` take precedence over the docstring when both are present. The tool description is the summary/body of the docstring — the `Args:` section is stripped out.
  - New `AgentSession.submit_client_tool_results(results, client_tools=...)` for manual tool-result submission when callers want to drive dispatch themselves.
  - New `AgentSession.unregister_client_tool(name)` removes a previously registered callback; symmetric with `register_client_tool`. The tool remains declared client-side on the session so a subsequent `tool_use` produces an error result rather than being silently skipped.
  - `AgentToolUseEvent` now carries the parsed `input` dict so progress hooks and observers can see the arguments the model chose.
  - `AgentToolResultEvent` now carries the raw `output` dict and `runtime_ms` alongside `success`, so observers can display what a tool actually returned (previously only a success bool was exposed).
  - New `AgentErrorEvent` fires from `events()` when an assistant message carries `AgentErrorContent` (for example, a failed or cancelled generation), so callers observing the event stream can detect failures without inspecting `session.messages` afterward.
  - `AgentSession.start()` validates that every initial message has role `USER` or `ASSISTANT` (seeded history); passing `ROBOTO` or `SYSTEM` raises `ValueError` up front rather than producing an opaque server rejection.

## Bugs Fixed
  - `AgentSession.events()` no longer emits spurious `AgentStartTextEvent` / `AgentTextEndEvent` pairs while a message is still generating across multiple polls. A text span now stays open until the underlying message reaches a terminal status (or a non-text content block arrives within the same message), so a streaming assistant response produces a single `Start → Delta* → End` sequence instead of one per poll.
  - `AgentSession.run()` no longer submits a client-side error `tool_result` for server-issued `tool_use_id`s when a mixed server+client turn lands before the server has mirrored its own tool result. The dispatcher now filters to tool names declared as client-side on the session; server tools are left for the server to answer. Without this filter, two `tool_result`s for the same `tool_use_id` could race, producing a Bedrock-invalid turn.

# 0.40.0
## Breaking Changes
  - Collections no longer support mixed resource types. Adding a resource whose type doesn't match the collection's `resource_type` raises an error.

## Features Added
  - `Collection.create()` now accepts a `resource_type` parameter (`CollectionResourceType.File` or `CollectionResourceType.Dataset`, defaulting to `File`) to declare whether a collection holds files or datasets. Adding a resource whose type doesn't match raises an error. `CollectionRecord` now includes a `resource_type` field.
  - `roboto collections create` now accepts an optional `--resource-type` flag (`file` or `dataset`). The type is inferred from `--file-id` or `--dataset-id` when not provided. Passing both flags together is an error. Omitting both IDs and `--resource-type` defaults to `file` and emits a warning.

## Bugs Fixed
  - Downloading or uploading files whose S3 key contains a `#` character no longer fails with a 403 error. `urllib.parse.urlparse` treats `#` as a URL fragment delimiter and silently truncates the key, causing the request to target a nonexistent object. `FileRecord.key` and `FileRecord.bucket` are now derived correctly.

# 0.39.0
## Internals
  - Removed `MetadataValuesRequest` and `MetadataValuesResponse` from `roboto.query`.
  - Introduced `@experimental` decorator for SDK classes, methods and functions whose functionality is incomplete, preview-only or subject to change or removal without notice.

## Breaking Changes
  - Search and query operations (e.g., `RobotoSearch.find_files()`, `RobotoSearch.find_datasets()`) now use eventually consistent reads for improved performance and scalability. Results may not immediately reflect very recent writes (typically within 1 second). If you create or update data and immediately query for it, you may need to add retry logic. See the [Eventual Consistency Migration Guide](https://docs.roboto.ai/learn/eventual-consistency-migration.html) for complete details, affected endpoints, and code examples.

## Features Added
  - `find_similar_signals` now supports rate-invariant (multi-scale) search via a new `scale` parameter accepting a `Scale` object. Finds a query pattern regardless of how fast or slow it occurs in the target. Each `Match` carries a `scale` field for the matched time-scale factor. Use `Scale(min, max, steps, spacing)` to configure the search grid, or `Scale.any()` for a wide default range. Distances are normalised so existing `max_distance` thresholds apply without adjustment.

## Bugs Fixed
  - Fixed `_derive_session_status` unconditionally returning `CLIENT_TOOL_TURN` for any completed assistant message ending with a tool_use block. Status derivation now requires explicit `client_tool_names` to distinguish client tools from server tools, defaulting to `ROBOTO_TURN` for unrecognised tools.
  - `find_similar_signals` no longer raises when a DataFrame contains non-numeric string values (e.g. header rows). Non-convertible rows are silently dropped and logged at `INFO`; a `ValueError` is raised only if the entire needle or a target topic collapses entirely to non-numeric data.
  - `Condition.matches()` now correctly handles comparing a `datetime` field in the target dictionary to an ISO 8601 timestamp.

# 0.38.0
## Features Added
  - Renamed the `Chat*` type family to `Agent*` across `roboto.ai.core`: `AgentSession`, `AgentMessage`, `AgentRole`, `AgentSessionStatus`, `AgentMessageStatus`, `AgentContentType`, and their content types (`AgentTextContent`, `AgentToolUseContent`, `AgentToolResultContent`, `AgentErrorContent`). The previous `Chat*` names remain as aliases.
  - Added `ClientToolSpec` model for declaring client-side tools.
  - Added `SubmitToolResultsRequest` model for returning client-executed tool results.
  - Added `CLIENT_TOOL_TURN` status to `AgentSessionStatus`, signaling that the session awaits client-side tool execution.
  - Renamed `chat_id` to `session_id` in `AgentSession`, with `chat_id` retained as a backwards-compatible computed alias in API responses.

## Internals
  - Moved canonical type definitions from `roboto.ai.chat` to `roboto.ai.core`. The `roboto.ai.chat` module re-exports all types for backwards compatibility.
  - Renamed the `ChatEvent` streaming event types to `AgentEvent` (`AgentStartTextEvent`, `AgentTextDeltaEvent`, `AgentTextEndEvent`, `AgentToolUseEvent`, `AgentToolResultEvent`). The previous `Chat*` event names remain as aliases.

## Bugs Fixed
  - `RobotoClient` HTTP retry now handles DNS resolution failures on all platforms, bare `ConnectionResetError` during response reads, and additional `ConnectionError` subclasses (`ConnectionRefusedError`, `ConnectionAbortedError`, `BrokenPipeError`) on idempotent requests.

# 0.37.0
## Breaking Changes
 - `File.get_summary()` and `File.generate_summary()` have been removed. `roboto.ai.Chat` should instead be used for the summarization of 1+ files. It offers a superset of the functionality of the old `File`-level summary API.

## Features Added
  - `roboto datasets upload-files` CLI command now accepts an optional `--device-id` flag to associate uploaded files with a specific device.
  - Improved MCAP topic data access performance for high-latency connections. Time-range queries now use HTTP Range requests to fetch only the required byte ranges instead of downloading entire files.
  - Added `ChatToolDetailResponse` model to support retrieving unsanitized tool use details from chat sessions.

## Bugs Fixed
  - Removed `typing_extensions` dependency as Python 3.9 is EOL. (`typing` is part of the standard library for Python 3.10+.)
  - `UpdateUserRequest` now rejects empty strings for `name` and `picture_url` fields, returning a validation error instead of causing a server error.
  - `find_similar_signals` now accepts DataFrames with string-typed numeric columns (e.g. `"1.23"`) for both needle and haystack. Columns are coerced to `float64` before processing; a `ValueError` is raised if any value cannot be converted. DataFrames already containing numeric types are unaffected.
  - `find_similar_signals` now correctly handles DataFrames indexed by `pandas.Timestamp` values.

# 0.36.0
## Breaking Changes
  - `MessagePath.parents()` now requires a `list[str]` (`path_in_schema`) instead of a dot-delimited `str`. This reflects the shift from ambiguous dot-separated paths to explicit schema path components for correct handling of nested and dot-containing field names. If you were calling `MessagePath.parents("pose.position.x")`, update to `MessagePath.parents(["pose", "position", "x"])`. Passing a string now raises a `TypeError` with guidance on how to migrate.
  - `MessagePath.parts()` has been removed. Use `MessagePathRecord.path_in_schema` directly to obtain path components.

## Features Added
  - Introduced `QueryContentMode`, allowing search endpoints to return Roboto entities with or without custom metadata. Initial support is for dataset queries in particular, since datasets can store large amounts of `metadata`, which is known to affect search latency and response size. More entity types will be supported in the future.
  - Improved `Topic.get_data` and `Topic.get_data_as_df` performance for Parquet-backed data.
  - `Topic.create_from_df()` and `File.add_topic()` now support DataFrames containing nested column types (structs, lists, list<struct>). Previously, only top-level primitive columns were fully supported.
  - `AddMessagePathRequest` now accepts a `path_in_schema` field to explicitly specify the field's location in the source data schema as an ordered list of path components. Relatedly, `Topic.add_message_path()` and `Topic.update_message_path()` now accept an optional `path_in_schema` parameter.

## Bugs Fixed
  - Updated behavior to not retry requests when server response exceeds the maximum safe payload size.

# 0.35.2
## Features Added
- Added limit, sort_by and sort_direction parameters to `v1/datasets/<dataset_id>/files/query`

# 0.35.1
### Simplified File Transfer API

File upload and download operations have been simplified. The high-level methods `Dataset.download_files()`, `Dataset.upload_files()`, and `File.download()` remain the recommended interfaces for file transfers. Implementation details that were previously exposed—such as credential management, progress monitoring factories, and upload transaction orchestration—have been moved into internal infrastructure and are no longer part of the public API.

**If you were using the high-level methods**, no changes are required beyond noting that `File.download()` now accepts a simpler `print_progress: bool` parameter instead of `credential_provider` and `progress_monitor_factory`.

**If you were using lower-level utilities directly**, migrate to the high-level methods above, or use `FileService` from `roboto.fs` if you need more control.

**Removed from public API:**

  - `FileDownloader` class: use `Dataset.download_files()`, `File.download()`, or `FileService` directly instead
  - Credential types (`CredentialProvider`, `DatasetCredentials`, `S3Credentials`, `UploadCredentials`)
  - Upload transaction types (`BeginManifestTransactionRequest`, `BeginManifestTransactionResponse`, `ReportTransactionProgressRequest`)
  - `File` static methods (`construct_s3_obj_arn()`, `construct_s3_obj_uri()`, `generate_s3_client()`): internal utilities no longer needed
  - `Dataset` internals (`_complete_manifest_transaction()`, `_create_manifest_transaction()`, `_flush_manifest_item_completions()`, `UPLOAD_REPORTING_BATCH_COUNT`, `UPLOAD_REPORTING_MIN_BATCH_SIZE`)
  - Modules: `roboto.domain.files.file_creds`, `roboto.domain.files.file_downloader`, `roboto.domain.files.file_service`, `roboto.domain.files.progress`

## Features Added
  - Added generic file upload API endpoints (`/v1/files/upload/*`) that support uploading files to any association type (datasets, topics, etc.), replacing the dataset-specific upload endpoints.

## Bugs Fixed
  - CLI version checker now queries GitHub Releases instead of PyPI, ensuring users are only prompted to upgrade to CLI versions that are actually published and available.

# 0.35.0.post1
## Bugs Fixed
  - Added `RobotoApiVersion.v2026_01_02` to support backwards-compatible handling of null vs. unset semantics in dataset update requests.

# 0.35.0
## Breaking Changes
  - `get_data()` now yields `tuple[int | float, dict]` instead of `dict`. The first element of the tuple is the record's timestamp in nanoseconds since Unix epoch, and the record is no longer enriched with a `log_time` field.
  - `get_data_as_df()` now returns a DataFrame with a timezone-aware UTC `DatetimeIndex`. A `log_time` column is no longer added to the DataFrame.

## Features Added
  - Added `--device-id` argument to `roboto datasets create` and `roboto datasets update` CLI commands.
  - DataFrames returned by `get_data_as_df()` can now be passed directly to `File.add_topic()` without specifying `timestamp_column` or `timestamp_unit`.

## Bugs Fixed
  - `Dataset.update()` now supports explicitly clearing `description` and `name` fields by passing `None`. Previously, passing `None` was indistinguishable from omitting the parameter.
  - Removed unused `conditions` parameter from `Dataset.update()` and `UpdateDatasetRequest`.

# 0.34.0
## Features Added
  - Updated `Topic` methods to use ID-based API endpoints for improved consistency and reliability. Removed now unused `Topic::url_quoted_name` property.

# 0.33.1
## Bugs Fixed
  - Added configurable HTTP timeout (default 30 seconds) with automatic retry for idempotent requests to prevent indefinite blocking on network issues.

# 0.33.0
## Features Added
  - Expanded `RobotoLLMContext` to include visualizer state and a misc context block for generic use during experimental feature development.
  - `roboto actions invoke-local` now automatically caches downloaded files between invocations. This eliminates the need to manage workspace state manually when iterating on action development. As such, the `--preserve-workspace` flag is now removed.
  - Added `roboto cache` commands (`where`, `size`, `clear`) to inspect and manage Roboto's local file cache.

## Bugs Fixed
  - Trigger conditions now correctly support substring checks against string-valued fields using `CONTAINS` or `NOT_CONTAINS`, e.g. `dataset.name CONTAINS "foo"`.
  - Added first class `Error` content type to `ChatMessage`, and expand data model to handle errors and cancellations.
  - Fixed an issue where action invocations with multi-dataset input could silently overwrite files when different datasets contained files with the same relative path. Files from multiple datasets are now stored in dataset-specific subdirectories.

# 0.32.0
## Features Added
  - Added `File::add_topic` and `Topic::create_from_df` methods to create topics directly from pandas DataFrames. SDK must be installed with the `"ingestion"` package extra (e.g. `pip install roboto[ingestion]`) to use this feature.

# 0.31.3
## Features Added
  - Internal: Added infrastructure to support file uploads independent of datasets, enabling upcoming features for file and topic management.

# 0.31.2
## Features Added
  - Added `Dataset::set_summary` and `File::set_summary` to enable actions to set a custom summary for a dataset or file.

# 0.31.1
## Features Added
  - Many improvements to `roboto.ai.Chat` and `roboto chat start`
  - Added `TriggerEvaluationCause.FileMetadataUpdate` to enable triggers to fire when file metadata or tags are updated (distinct from `FileIngest` which fires when files are marked as ingested).
  - Trigger conditions now support resource-qualified field paths in RoboQL syntax (e.g., `file.metadata.key`, `dataset.name`), enabling conditions to target specific resource types. This allows per-file triggers to filter based on file-specific properties while per-dataset triggers can reference dataset properties.

## Bugs Fixed
  - `roboto actions init` no longer prompts to delete and re-download a previously cached Action template (if exists). This should always happen to ensure new Actions are making use of the latest template.

# 0.31.0
## Features Added
  - Add `RobotoSearch::from_env` classmethod for convenience and consistency with other Roboto resource factories.

## Bugs Fixed
  - `get_data` and `get_data_as_df` APIs now correctly handle extracting array fields from ROS messages.
  - `get_data` and `get_data_as_df` APIs now correctly handle extracting ROS1 and ROS2 timestamp fields.

# 0.30.0
## Features Added
  - Added an optional `total_count` field to `PaginatedList`

## Bugs Fixed
  - Action parameters passed via `roboto actions invoke --parameter` are now correctly treated as strings, matching the documented behavior.
  - The global `roboto` CLI option `--profile` is now respected when using `roboto actions invoke-local`, enabling switching between Roboto orgs or API keys.
  - `InvocationContext.dataset` now raises a `ActionRuntimeException` when accessed in scenarios where no dataset is associated (e.g., local runs, scheduled triggers, or CLI invocations with query-based input), instead of failing with a `RobotoNotFoundException`.

# 0.29.0
## Features Added
  - Added utilities to initialize an invocation's runtime environment in the SDK to better support action development and local testing.
  - `roboto actions invoke-local` command enables local invocation of actions from either local directories (e.g., actions created with `roboto actions init`) or actions fetched from the Roboto platform.
  - Action invocation from the CLI now supports query-based input specifications (file queries and topic queries) in addition to the legacy dataset+file-paths model. For example: `roboto actions invoke --topic-query "msgpaths[cpuload.load].max > 0.9" <ACTION_NAME>`. See `roboto actions invoke --help` or `roboto actions invoke-local --help` for more details.

## Bugs Fixed
  - Fixed imports in `Org` docstring code examples.
  - Removed dependence on environment variables from `InvocationContext` to better support action development and local testing.

## Chores
  - Move `ActionConfig` (the model used to define and validate file-based Action configuration) from the CLI source tree to `roboto.domain.actions` to better support action development and local testing.

# 0.28.2
## Bugs Fixed
  - Force re-package Python SDK for upload to PyPI.

# 0.28.1
## Bugs Fixed
  - Fix SDK repo synchronization issue that caused a broken release.

# 0.28.0
## Features Added
  - Rename `ActionRuntime` to `InvocationContext` to better reflect that this utility provides context for the current action invocation. For backward compatibility, `ActionRuntime` remains available as a deprecated alias and will be removed in a future release. Update your code to use `InvocationContext.from_env()` instead of `ActionRuntime.from_env()`.
  - `InvocationContext::get_optional_parameter` enables specifying a default value for a parameter instead of raising an `ActionRuntimeException` if the parameter is not provided (as done by `InvocationContext::get_parameter`).
  - `ActionInputResolver` is now available in the SDK to support local testing and debugging of actions. This utility resolves invocation inputs (files, topics) the same way the platform does, enabling developers to test their actions outside of the Roboto runtime environment before deployment.

## Bugs Fixed
  - Added a clarification to the documentation for `Dataset::get_topics` and `Topics::get_by_dataset`

# 0.27.0
## Features Added
  - Added `Secret` to domain, in support of providing API keys and other secrets to actions in a more secure way.

# 0.26.3
## Bugs Fixed
  - `Device::from_id` and others fail when the device_id contains spaces, +, or other characters which need to be URL encoded.

# 0.26.2
## Features Added
  - `Device::create` allows users to provide metadata and tags at creation time
  - `Device::update` and convenience methods allow metadata and tags to be updated after creation
  - Token APIs allow you to specify a set of API scopes to limit the token's permissions

# 0.26.1
## Bugs Fixed
  - Added a docstring for `CreateDatasetIfNotExistsRequest` to fix rendering issue in docs

# 0.26.0
## Features Added
  - Add natural language chat, through `roboto.ai.chat` constructs and `roboto chat start` CLI command

# 0.25.4
## Bugs Fixed
  - Fix Pydantic model validation bug introduced to `roboto.domain.actions.ComputeRequirements` in v0.25.2.

# 0.25.3
## Features Added
  - Added `ActionStatsRecord` + an API to retrieve them for an org within a given time window.
  - Introduced `CanonicalDataType.Categorical` for data that can take a limited, fixed set of values. To be interpreted correctly by Roboto clients, a `MessagePathRecord` with this type must have a `"dictionary"` metadata key containing the list of possible values. This enables Roboto to map categorical values to indices and visualize the data as plots.

# 0.25.2
## Features Added
  - The `storage` and `memory` compute requirements in `action.json` can now be specified with their units for clarity: `storage_GiB`/`storage_gib` and `memory_MiB`/`memory_mib`.

# 0.25.1
## Features Added
  - Allow `device_id' to be specified explicitly when uploading, importing, or updating files.
  - Change `Dataset::upload_file` to return a lazy-resolving `File` handle vs. returning `None`.

# 0.25.0
## Features Added
  - Updates to `README.md` including list of supported formats
  - Add `StreamingAISummary`, and modify existing `get_summary` and `generate_summary` methods to return it.
  - Initial support for invoking actions on a recurring schedule, via `ScheduledTrigger`.
  - Added `InvocationInput::file_query` and `InvocationInput::topic_query` for concisely specifying invocation inputs using RoboQL queries.

## Bugs Fixed
  - Support both single strings and collections of strings for `message_paths_include`/`message_paths_exclude` parameters in `Topic::get_data`, `MessagePath::get_data`, `Event::get_data`, and their `::get_data_as_df` variants.

# 0.24.1
## Features Added
  - Allow `device_id` to be specified explicitly when creating or updating datasets.
  - Extended first-class support for Parquet-based recording data: `Topic::get_data`, `MessagePath::get_data`, `Event::get_data`, and their `::get_data_as_df` variants now work with data ingested from Parquet files (previously raised `NotImplementedError`).
  - Addition of `MessagePathRecord::path_in_schema`, `MessagePathRecord::source_path`, and `MessagePathRecord::parents`
  for use accessing fields on topic data without heuristically assuming all message paths are or can be dot separated.

# 0.23.1
## Features Added
  - Extended `RobotoPrincipal` to include devices + invocations, and added methods to convert to and from a canonical string format.
  - Add `RobotoSearch::for_roboto_client` and `RobotoClient.for_profile` to simplify code snippets for users with multiple profiles.

# 0.23.0
## Features Added
  - Improved help text for various Roboto CLI commands.
  - Add X-Roboto-Api-Version to all SDK requests.

# 0.22.1
## Features Added
  - Added `File::import_one` which automatically looks up the size of S3 files + verifies they exist.

# 0.22.0
## Features Added
  - Added `RobotoPrincipal`, which generalized providing a user or org to various platform APIs.
  - Added `Dataset::create_if_not_exists` to simplify a common pattern from read only BYOB file import scenarios.
  - Added `create_directory` method and docstring to `Dataset`, which allows you to create a directory in a dataset, including intermediate directories.
  - Comprehensive docstring updates for `roboto.domain.topics` module following Google-style format with Examples sections for all public methods, enhanced Args/Returns/Raises documentation, and improved cross-references.
  - Comprehensive docstring updates for `roboto.domain.actions` module following Google-style format with Examples sections for all public methods, detailed Args/Returns/Raises documentation, and improved cross-references. All Action, Invocation, and Trigger classes now have extensive documentation with practical examples.
  - Comprehensive docstring updates for `roboto.domain.users` and `roboto.domain.orgs` modules following Google-style format with Examples sections for all public methods, field docstrings for Pydantic models, and enhanced Args/Returns/Raises documentation. All User, Org, and OrgInvite classes now have extensive documentation with practical examples.
  - Comprehensive docstring updates for `roboto.domain.events` module following Google-style format with Examples sections for all public methods, detailed Args/Returns/Raises documentation, and improved cross-references. All Event classes now have extensive documentation with practical examples using proper Roboto ID conventions.
  - Comprehensive docstring updates for `roboto.domain.devices` module following Google-style format with Examples sections for all public methods, enhanced Args/Returns/Raises documentation, field docstrings for Pydantic models, and improved cross-references. All Device classes now have extensive documentation with practical examples for device registration, token management, and device operations.
  - Comprehensive docstring updates for `roboto.domain.comments` module following Google-style format with Examples sections for all public methods, field docstrings for Pydantic models, and enhanced Args/Returns/Raises documentation. All Comment classes now have extensive documentation with practical examples for creating, retrieving, updating, and deleting comments on platform entities.
  - Added placeholder implementation for working with topic data ingested as Parquet in the SDK. Attempting to fetch Parquet-ingested data currently raises a `NotImplementedError`.
  - Added `roboto datasets import-external-file` CLI command for importing files from customer S3 buckets into Roboto datasets.

# 0.21.0
## Features Added
  - Add `summary_id` and `status` to `AISummary`, in support of new async summary generation.
  - Add rich documentation to many `roboto.domain.*` files
  - Add `get_summary()` and `generate_summary()` to `File`, exposing LLM summaries of files.
  - Add `get_summary_sync()` to `Dataset` and `File`, which allows you to await the completion of a summary.
  - Added an optional `print_progress` flag to all `Dataset::upload_*` methods, which allows the caller to suppress TQDM progress bars printing to STDOUT.
  - Added an optional `upload_destination` argument to `Action::invoke` and `Trigger::invoke`. If provided, it tells the Roboto platform where to upload any outputs produced by the invocation.
  - Added an optional `--output-dataset-id` command-line argument to `roboto actions invoke` to let users set an invocation's upload destination to a Roboto dataset.

# 0.20.1
## Features Added
  - [CLI] Actions that don't take inputs can now be invoked from the command-line by leaving out the arguments `--dataset-id` and `--input-data`. For actions that take inputs, both arguments must be provided as before.
  - Add subset of audit fields to `RepresentationRecord` to enable determination of "latest" representation of topic data.
  - Add ability to pass `caller_org_id` to `File::import_batch`, which is necessary to exercise bring-your-own-bucket file imports for users belonging to multiple orgs.
  - Added a method to Dataset to list directories. Added metadata properties to `DirectoryRecord`. Added the `S3Directory` storage type to `FileStorageType`. Added `fs_type`, `name`, and `parent_id` to `FileRecord`.

# 0.20.0
## Features Added
  - Support has been added for topic inputs to action invocations, via `InvocationInput.topics`. Action writers can access the topics via `ActionInput.topics`.
  - Added the `requires_downloaded_inputs` optional flag to `Action::create` and `Action::update`. It controls whether an action invocation's inputs will be available in its working directory before business logic runs. This is true by default.
  - Added getters to `Action` for `description`, `short_description`, `tags`, `metadata`, `published` and `requires_downloaded_inputs`.
  - `Dataset::get_topics` now has optional arguments to `include` or `exclude` topics by name, similar to `File::get_topics`.
  - Added `FileDownloader` to simplify the task of downloading multiple files, for instance from search results.
  - Added `CanonicalDataType.Timestamp` to support identifying `MessagePath`s that should be interpreted as time elapsed since the Unix epoch.
  - Added `RepresentationStorageFormat.PARQUET` in support of progress towards accepting Parquet files as a first-class ingest-able format (in addition to bag, db3/yaml, mcap, ulg, journalctrl, csv and others).

# 0.19.0
## Breaking Changes
  - The list of tuples returned by `ActionInput::files` now has a `File` as its first element rather than a `FileRecord`. This gives action writers access to more powerful file operations, such as retrieving topics.

# 0.18.0
## Breaking Changes
  - The `input_data` property of `Invocation` now returns an `Optional[InvocationInput]`. It used to return a `list` of file name patterns.

## Features Added
  - Added `extra_headers_provider` param to `HttpClient` which accepts a callback which generates headers on every HTTP request at runtime. This was added so we ourselves can send internal trace IDs.
  - Added getters for `created`, `created_at`, `modified`, `modified_at` to `Dataset`, `File` and other related entities, eliminating the need to access them via `.record`.
  - Enhanced `Dataset::download_files` to return both `FileRecord` objects and their corresponding local save paths.
  - Added `ActionRuntime::get_input` method to inspect resolved input data references during Action execution.
  - Introduced `InvocationInput` - a richer way of specifying inputs to action invocations which will not be limited to dataset file paths. Full platform support will be delivered in stages.
  - Introduced `Layouts` - a way to create a saved arrangement of panels for visualizing data in Roboto.
  - Added `TriggerRecord::causes`, `CreateTriggerRequest::causes`, and `UpdateTriggerRequest::causes` to allow triggers to filter which evaluation causes they respond to.
  - Added `TriggerEvaluationCause::FileIngest` to allow triggers to respond to when a file is marked as `IngestionStatus::Ingested`.

## Bugs Fixed
  - Added dynamic import guard around `roboto.version` in `requester.py` to fix in-IDE tests from Roboto's development environment (before `version.py` is dynamically generated).
  - Don't reject API requests that contain extra fields. This enables backwards-compatibility with outdated SDK builds and forwards-compatibility for adding new fields to the SDK independent of our server release cycle.

# 0.17.0
## Features Added
  - Reduced the scope of `ingestion_status` updates to make the feature more usable in ingestion actions.

# 0.16.0
## Features Added
  - Updated `ingestion_status` to allow a `PartlyIngested` state, and made `ingestion_status` an optional parameter to `file.update` calls.
  - Added `CHANGELOG.md`.
