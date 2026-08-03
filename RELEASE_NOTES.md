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

