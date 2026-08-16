# Andruha Messenger — Repository Skeletons

**Document type:** Agent Implementation Specification  
**Status:** Ready for review  
**Date:** 2026-08-16  
**Audience:** implementation AI agent

## 1. Objective

Create the repository and deployment skeleton for the Andruha Messenger MVP. This stage establishes repository boundaries, empty hexagonal/DDD packages, cross-cutting HTTP infrastructure, Docker build files, and local Docker Compose topology.

This is a **scaffolding-only stage**. Do not implement messenger business logic.

## 2. Source of truth

Use the following PayFlow files as read-only implementation references:

- `C:\Projects\PayFlow\auth_service\src\app\core\logging.py`
- `C:\Projects\PayFlow\auth_service\src\app\entrypoints\http\main.py`
- `C:\Projects\PayFlow\auth_service\src\app\entrypoints\http\routers\health.py`
- `C:\Projects\PayFlow\auth_service\src\app\entrypoints\http\middlewares\request_id.py`
- `C:\Projects\PayFlow\auth_service\src\app\entrypoints\http\middlewares\request_id_policy.py`
- `C:\Projects\PayFlow\auth_service\src\app\entrypoints\http\middlewares\request_lifecycle.py`
- `C:\Projects\PayFlow\auth_service\Dockerfile`
- `C:\Projects\PayFlow\order_service\Dockerfile`
- `C:\Projects\PayFlow\gateway\nginx.conf`
- `C:\Projects\PayFlow\gateway\proxy-common.conf`
- `C:\Projects\PayFlow\docker-compose.yml`

Copy only reusable infrastructure patterns. Do not copy PayFlow domains, use cases, migrations, credentials, secrets, product names, ports, or API routes.

Preserve the existing `docs/mvp-sequence-diagrams.md` file.

## 3. Repository topology

Interpret “the main repository contains links to the services” as a Git superproject with Git submodules under `services/`.

Use the existing `C:\Projects\Andruha` directory as the `andruha-messenger` superproject root. Preserve all pre-existing files unless this specification explicitly asks to modify them. Treat `C:\Projects\PayFlow` as read-only.

| Repository | Local path | Future responsibility | Port |
|---|---|---|---:|
| `andruha-messenger` | repository root | Integration, Compose, docs, contracts | — |
| `andruha-api-gateway` | `services/api-gateway` | NGINX edge routing | 8080 |
| `andruha-identity-service` | `services/identity-service` | Credentials and authentication sessions | 8001 |
| `andruha-user-profile-service` | `services/user-profile-service` | Editable public profile data | 8002 |
| `andruha-messages-dialogues-service` | `services/messages-dialogues-service` | Dialogues, messages, receipts | 8003 |
| `andruha-websocket-gateway-service` | `services/websocket-gateway-service` | Realtime connections and delivery | 8004 |
| `andruha-object-storage-service` | `services/object-storage-service` | Media upload/access boundary | 8005 |

There is no separate Notification Service in this MVP skeleton. Online message events and notifications belong to the WebSocket Gateway boundary; durable message/read state belongs to Messages and Dialogues. Do not implement either behavior now.

### Git constraints

- Initialize every listed repository independently.
- The superproject owns only integration files, documentation, contracts, and submodule pointers; it must not own service source code directly.
- Do not invent remote Git URLs, create remote repositories, commit, push, or publish anything.
- If all remote URLs are supplied, add the repositories as Git submodules and generate `.gitmodules`.
- If remote URLs are missing, complete the local skeletons but stop before submodule wiring. Report the missing URLs as a controlled blocker; do not stage embedded repositories as accidental gitlinks.

## 4. Main repository

Required structure:

```text
andruha-messenger/
├── README.md
├── .env.example
├── .gitignore
├── .gitmodules                 # only when real remote URLs are provided
├── docker-compose.yml
├── contracts/
│   └── README.md
├── docs/
│   ├── README.md
│   ├── mvp-sequence-diagrams.md
│   └── service-skeleton-agent-spec.md
└── services/                   # Git submodule mount points
```

The main `README.md` must contain:

- project purpose and current “skeleton only” status;
- a service table with responsibilities and relative submodule links;
- repository/submodule checkout instructions;
- local topology and Docker Compose commands;
- links to `docs/` and `contracts/`;
- an explicit note that business APIs and dependency bootstrap are not implemented.

`docs/` and `contracts/` exist **only** in the main repository. Service repositories link back to them and must not duplicate them.

## 5. Common Python service skeleton

Create this minimal structure in each of the five Python repositories:

```text
<service>/
├── README.md
├── pyproject.toml
├── Dockerfile
├── docker-entrypoint.sh
├── .dockerignore
├── .gitignore
├── .env.example
├── src/app/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   └── logging.py
│   ├── domain/__init__.py
│   ├── application/
│   │   ├── __init__.py
│   │   ├── ports/__init__.py
│   │   └── services/__init__.py
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   └── di/__init__.py
│   └── entrypoints/
│       ├── __init__.py
│       └── http/
│           ├── __init__.py
│           ├── main.py
│           ├── routers/
│           │   ├── __init__.py
│           │   └── health.py
│           └── middlewares/
│               ├── __init__.py
│               ├── request_id.py
│               ├── request_id_policy.py
│               └── request_lifecycle.py
└── tests/
    ├── unit/.gitkeep
    └── integration/.gitkeep
```

Also create empty package boundaries where applicable:

- Messages and Dialogues: `src/app/entrypoints/messaging/__init__.py`.
- WebSocket Gateway: `src/app/entrypoints/websocket/__init__.py` and `src/app/entrypoints/messaging/__init__.py`.

Do not create placeholder entities, aggregates, commands, handlers, repository interfaces, adapters, database models, event contracts, migrations, or fake implementations.

### Architecture dependency rule

```text
entrypoints -> application -> domain
infrastructure -> application ports -> domain
core = configuration and cross-cutting infrastructure only
```

- `domain` imports no outward layer or framework.
- `application` depends only on `domain` and its own ports.
- `infrastructure` implements application ports later.
- `entrypoints` translate transport input/output and call application services later.
- Do not create a shared Python package in this stage. Separate repositories intentionally own their copies of small bootstrap infrastructure.

## 6. Poetry and dependencies

For each Python service:

1. Run `poetry init --no-interaction` with the repository-specific package name, version `0.1.0`, a short description, and Python constraint `>=3.14,<4.0`.
2. Do not run `poetry add`, `poetry install`, or `poetry lock` on the host.
3. Do not declare runtime or development dependencies yet. The Python constraint is the only allowed dependency-related declaration.
4. Do not create or commit `poetry.lock`, `.venv/`, cache files, or generated artifacts.

The API Gateway is an NGINX repository and is the only repository that does not use Poetry.

If a working Poetry executable is unavailable, do not install it silently and do not handcraft a file while claiming that `poetry init` ran. Stop that step and report the exact blocker.

## 7. Operational HTTP skeleton

Each Python service must expose, through a FastAPI application factory named `create_app`:

- `GET /health/live` — returns `200` when the process is running;
- `GET /health/ready` — returns `200` after application initialization.

At this stage readiness has no external dependency checks because no adapters are wired. Do not add fake PostgreSQL, Cassandra, Kafka, Valkey, or object-storage probes. Add real probes only in a later dependency/adapters task.

Do not create a module-level application singleton. Docker commands must target the factory form.

### Logging

Adapt PayFlow logging configuration with these settings only:

- `SERVICE_NAME`, `APP_VERSION`, `APP_ENVIRONMENT`;
- `HOST`, `PORT`;
- `DEV_LOGS`, `LOG_LEVEL`, `MUTE_LOGGERS`.

Keep structured JSON logs for non-development environments and readable console logs for development. Bind `request_id` through context variables. Never log cookies, authorization headers, tokens, passwords, object contents, or personal profile data.

### Request ID ownership

The edge API Gateway is authoritative for public request IDs:

1. Generate a request ID when the public request enters NGINX.
2. Replace rather than trust an arbitrary client-supplied `X-Request-Id`.
3. Forward the trusted value to every upstream as `X-Request-Id`.
4. Return it in responses, including gateway-generated errors, and include it in access logs.

Each Python HTTP service must still use the adapted PayFlow pure-ASGI middleware to validate/bind the propagated value, generate a safe value for direct/internal calls, attach it to responses, and always clear context variables. Do not use `BaseHTTPMiddleware`.

The API Gateway performs routing and transport concerns only. It must not contain JWT validation, RBAC, session lookups, domain validation, or messenger business logic.

## 8. API Gateway repository

Required files:

```text
api-gateway/
├── README.md
├── Dockerfile
├── .dockerignore
├── nginx.conf
└── proxy-common.conf
```

Prepare upstream routes for the future APIs without implementing those APIs:

- `/api/v1/auth/` -> Identity Service;
- `/api/v1/profiles/` -> User Profile Service;
- `/api/v1/dialogues/` and `/api/v1/messages/` -> Messages and Dialogues Service;
- `/api/v1/objects/` -> Object Storage Service;
- `/ws` -> WebSocket Gateway with HTTP upgrade headers and long-lived connection timeouts.

Expose gateway `GET /health/live` and `GET /health/ready`. Use JSON access logs containing request ID, status, timing, upstream, and upstream timing, without sensitive headers.

Use a multi-stage NGINX Dockerfile: a validation stage must run `nginx -t`; the runtime stage contains only the validated configuration and NGINX runtime.

## 9. Dockerfiles

Every service repository must have a multi-stage Dockerfile. The superproject does not need one.

For Python services, follow the PayFlow shape:

- explicit `python:3.14-slim-bookworm` builder and runtime bases;
- pinned Poetry version in the builder;
- in-project virtual environment;
- builder consumes only `pyproject.toml` because a lock file is forbidden in this stage;
- non-root runtime user with explicit UID/GID;
- `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, `PATH`, and `PYTHONPATH`;
- copy only the virtual environment and application source into runtime;
- small signal-safe `docker-entrypoint.sh` using `exec`;
- factory-form Uvicorn command and the service-specific port;
- no compilers, Poetry installation, migrations, or initialization scripts in runtime.

Do not add Alembic or run database migrations.

Because application dependencies are intentionally absent, Python runtime startup is **not** an acceptance criterion for this stage. Do not hide this by installing undeclared packages or by building a temporary standard-library web server.

## 10. Docker Compose

Create one root `docker-compose.yml` containing:

- all six application/gateway services, built from their submodule paths;
- separate PostgreSQL instances for Identity credentials, User Profile data, and Object Storage metadata;
- separate Cassandra instances for Identity high-write session data and Messages/Dialogs data;
- Kafka in single-node KRaft mode for local event flow;
- Valkey for ephemeral presence, typing state, connection routing, and cache experiments;
- MinIO as the self-hosted S3-compatible object store;
- named volumes and one explicit application network.

Compose requirements:

- only the API Gateway is published to the host by default;
- use explicit, non-`latest` image tags;
- use service names rather than `localhost` for container-to-container addresses;
- add health checks to infrastructure and application containers;
- use `depends_on` health conditions only where a real startup dependency exists;
- place non-secret defaults in `.env.example`, use substitutions in Compose, and never commit `.env` or real secrets;
- do not add database schemas, keyspaces, buckets, Kafka topics, migrations, seed data, or business bootstrap scripts;
- do not claim production HA, Cassandra scaling, Kafka durability, or a production security posture from this local Compose file.

Compose fixes the durable-store ownership boundary: Identity owns its PostgreSQL and session Cassandra; Profile owns its PostgreSQL; Messages owns its Cassandra; Object Storage owns its metadata PostgreSQL and MinIO boundary. Compose availability does not authorize adapters, schemas, keyspaces, or migrations.

## 11. README template for every service repository

Each service `README.md` must include these empty-but-useful sections:

1. Purpose and current status.
2. Responsibility and explicit non-responsibilities.
3. Hexagonal/DDD layer map.
4. Entrypoints.
5. Configuration variables.
6. Liveness and readiness endpoints.
7. Local build/run status, clearly stating that dependency bootstrap is deferred.
8. Links to the main repository's `docs/` and `contracts/`.

Do not describe unimplemented APIs as available.

## 12. Non-goals

The agent must not implement:

- registration, login, refresh, logout, or PayFlow Auth migration;
- profiles, dialogues, messages, receipts, typing, presence, notifications, uploads, avatars, or WebSocket protocols;
- domain models, use cases, storage adapters, event handlers, API/event schemas, or generated clients;
- database/keyspace/bucket/topic creation or migrations;
- authentication/authorization at NGINX;
- Kubernetes, CI/CD, observability backends, load tests, backups, HDD archival, multi-region, or production scaling;
- dependency selection or installation beyond initializing Poetry metadata.

## 13. Acceptance checks

| ID | Check | Expected result |
|---|---|---|
| A-01 | Inspect repository roots | One superproject plus six independent service repositories exist. |
| A-02 | Inspect Git linkage | Real URLs produce valid submodules; absent URLs are reported without accidental embedded-repo staging. |
| A-03 | Inspect trees | All required files/packages exist; no business implementation exists. |
| A-04 | Inspect Poetry files | Five `pyproject.toml` files came from `poetry init`; no declared project/dev dependencies and no lock files. |
| A-05 | Inspect architecture imports | Empty inner layers do not import frameworks or outward layers. |
| A-06 | Inspect HTTP bootstrap | Factory app, health routes, pure-ASGI request ID lifecycle, and logging setup match this specification. |
| A-07 | Inspect gateway config | Routes, WebSocket upgrade, trusted request ID forwarding, safe JSON logs, and gateway health routes exist. |
| A-08 | Run `docker compose config --quiet` | Compose resolves successfully without starting containers. |
| A-09 | Inspect Dockerfiles | All six are multi-stage, use non-root app runtimes where applicable, and contain no migration/bootstrap behavior. |
| A-10 | Inspect secrets/artifacts | No `.env`, credentials, tokens, `.venv`, lock files, caches, or copied PayFlow product data. |
| A-11 | Inspect documentation | Root and service READMEs state exact current scope and link to canonical docs/contracts. |

Do not use `docker compose up`, successful Python imports, health HTTP calls, or application image startup as completion evidence in this dependency-free stage. If the environment has working tools, static Python compilation and `nginx -t`/image build may be reported as optional evidence, never fabricated.

## 14. Completion report

Return a concise report containing:

- repositories and files created;
- whether submodules were wired and which URLs were used;
- commands actually executed and their exact outcomes;
- acceptance checks passed, skipped, or blocked;
- confirmation that no business logic or dependencies were added;
- blockers and the next recommended task: dependency bootstrap plus runnable operational endpoints.

Do not say “complete” or “green” if submodule linkage or any required acceptance check is blocked.
