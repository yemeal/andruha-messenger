# Identity / Profile E2E

Run from `services/identity-service`, using its existing uv environment:

```powershell
rtk proxy uv run python ../../scripts/e2e/run.py --relay-repeats 2
```

Requires Docker Desktop with Linux containers. The runner builds the current working trees, creates a separate Compose project with fresh volumes and keys, applies both Alembic migrations, and runs the scenarios in `identity.py`. No existing database or Docker project is reused. Cleanup removes only the generated project's containers, network and volumes. `--keep` preserves the test project for inspection.

The artifact directory is printed at startup and completion. `results.json` contains scenario outcomes and HTTP status metadata; `consistency.json` contains the final cross-service comparison and Kafka deliveries. The process exits nonzero if any scenario fails. Keys and the private Compose configuration remain in the temporary directory; do not publish that directory wholesale.

## Scope

Real runtime images: Gateway, Identity API, Identity relay, registration reconciler and User Profile. Real infrastructure: separate PostgreSQL databases, Valkey and Kafka. Infrastructure image versions and service definitions come from the root Compose file. The generated configuration explicitly supplies connection settings, JWT keys and service credentials; it is not a verification that the unmodified root Compose file starts by itself.

`profile_proxy.py` forwards provisioning to the real Profile service. It can hold the HTTP response **after the real transaction commits**, or replace the service credential to provoke a real authorization failure. It contains no Profile implementation or mock database. The control endpoint exists only on the separate test network and a loopback port.

Fault scenarios stop/start dependencies and send SIGKILL to test processes. One scenario installs a temporary PostgreSQL trigger that blocks Outbox's success update after Kafka acknowledgment. The trigger is removed in `finally`. This proves the expected duplicate delivery window: the same `event_id` can be delivered more than once.

Success means the tested state converges: every completed registration has exactly one Identity user, Profile, settings record and Outbox row; Kafka contains the corresponding event IDs and payloads; no live claims or unfinished operations remain. HTTP errors and application logs are checked for credential canaries. This does not prove exhaustive failure coverage, multi-node failover, browser CSRF behavior, or exactly-once Kafka delivery.

To rerun selected scenarios on a retained project, pass its artifact directory:

```powershell
rtk proxy uv run python ../../scripts/e2e/identity.py C:/path/to/artifacts --only concurrent_refresh_same_key global_consistency_and_kafka_delivery
```

Selected runs create new users and overwrite `results.json`; copy prior results first. Scenarios using `main_user` require `registration_login_profile` in the selection. Keep a single runner active per test project because failure injection changes shared service availability.

`run.py --custom-identity-credentials` generates disposable Identity PostgreSQL
credentials through the root Compose variable mapping; it does not override
DATABASE_* independently or override the selected Identity event topic.
`--messages-lookup` additionally runs the real Messages HTTP eligibility adapter
against the isolated Identity API. Its log is `messages-identity-lookup.log`.
Pass `--only ...` to `run.py` for a bounded scenario selection. `--relay-repeats 2`
preserves the main report and records two separate automatic recovery reports.

The automatic relay recovery scenario SIGKILLs the worker PID under Docker init
while Kafka is unavailable and never starts the relay manually. Process liveness
and dependency readiness are checked separately. API recovery waits for a safe
anonymous GET to reach the upstream through the gateway after Docker DNS changes.
The Profile readiness scenario proves DB stop/start recovery without restarting
the Profile process. Internal account lookup tests also cover a real Profile-only
registration and Profile BLOCKED lifecycle independently of Identity eligibility.

## Messages Direct/Saved text E2E

From `services/identity-service`, using its existing locked uv environment:

```powershell
rtk proxy uv run python ../../scripts/e2e/run_messages.py
```

The runner additionally builds Messages, starts a private Cassandra, creates its
keyspace and applies all versioned migrations. It registers A/B and an outsider
through real Identity/Profile, logs in through Gateway, and checks one Direct
for A–B/B–A, eight concurrent retries, history snapshot pagination, incremental
sync, dialog activity, Saved, global send-key conflicts and authorization.
It restarts Messages and stops/starts Cassandra, requiring 503 readiness and
business reads during the outage, 200 liveness and successful reconnect/replay.

`messages-results.json` contains safe check names and the Messages image ID.
`cleanup.json` records removal of only the generated project's resources.
`--keep` preserves that project. The private Compose/manifest, key files and
raw service logs stay in the temporary directory and are not public evidence.
No Kafka publication, WebSocket delivery, group messages or media are claimed.
