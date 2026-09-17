# Identity / Profile E2E

Run from `services/identity-service`, using its existing Poetry environment:

```powershell
rtk proxy poetry run python ../../scripts/e2e/run.py
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
rtk proxy poetry run python ../../scripts/e2e/identity.py C:/path/to/artifacts --only concurrent_refresh_same_key global_consistency_and_kafka_delivery
```

Selected runs create new users and overwrite `results.json`; copy prior results first. Scenarios using `main_user` require `registration_login_profile` in the selection. Keep a single runner active per test project because failure injection changes shared service availability.
