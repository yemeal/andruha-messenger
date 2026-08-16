# Andruha Messenger

Andruha Messenger is an MVP messenger split into independently versioned service repositories. The current repository contains integration scaffolding only: repository boundaries, empty hexagonal/DDD packages, operational HTTP bootstrap code, Docker build definitions, and a local Docker Compose topology.

No messenger business API or dependency bootstrap is implemented yet.

## Repositories

| Repository | Local path | Responsibility |
|---|---|---|
| API Gateway | [`services/api-gateway`](services/api-gateway) | NGINX edge routing and transport concerns |
| Identity Service | [`services/identity-service`](services/identity-service) | Credentials and authentication sessions |
| User Profile Service | [`services/user-profile-service`](services/user-profile-service) | Editable public profile data |
| Messages and Dialogues Service | [`services/messages-dialogues-service`](services/messages-dialogues-service) | Dialogues, messages, and receipts |
| WebSocket Gateway Service | [`services/websocket-gateway-service`](services/websocket-gateway-service) | Realtime connections and delivery |
| Object Storage Service | [`services/object-storage-service`](services/object-storage-service) | Media upload and access boundary |

There is no Notification Service in the MVP skeleton. Online delivery belongs to the WebSocket Gateway boundary; durable message and read state belongs to Messages and Dialogues.

## Checkout and submodules

The directories under `services/` are independent repositories wired into this integration repository as Git submodules. Clone the complete project with:

```bash
git clone --recurse-submodules https://github.com/yemeal/andruha-messenger.git
cd andruha-messenger
git submodule update --init --recursive
```

For an existing checkout, synchronize configured URLs before updating:

```bash
git submodule sync --recursive
git submodule update --init --recursive
```

## Local topology

The local Compose topology includes the six application services, three PostgreSQL instances (Identity, Profile, and Object Storage metadata), two isolated Cassandra instances (Identity sessions and Messages), Kafka in single-node KRaft mode, Valkey, and MinIO. Only the API Gateway is published to the host, on port `8080` by default.

Configuration can be rendered now:

```powershell
Copy-Item .env.example .env
docker compose config --quiet
```

After the dependency-bootstrap task adds declared runtime dependencies and lock files, the intended runtime commands are:

```powershell
docker compose build
docker compose up -d
docker compose down
```

Application image startup is intentionally unavailable at this stage because FastAPI, Uvicorn, Structlog, and related dependencies have not been declared. No temporary server or undeclared dependency is included to hide that boundary.

## Canonical project material

- [Project vision and MVP architecture (Russian)](docs/project-overview.md)
- [Architecture and implementation documents](docs/)
- [Cross-service contracts](contracts/)

Business APIs, event contracts, data schemas, storage adapters, migrations, topics, buckets, and dependency installation are outside the current skeleton-only scope.
