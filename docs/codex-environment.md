# Codex environment

Repository-local helper commands for consistent service setup and verification.

## Python service commands

From the parent repository, use:

```powershell
rtk proxy py -3 scripts/codex-service.py user-profile-service check-tools
rtk proxy py -3 scripts/codex-service.py user-profile-service setup
rtk proxy py -3 scripts/codex-service.py user-profile-service lint
rtk proxy py -3 scripts/codex-service.py user-profile-service unit
rtk proxy py -3 scripts/codex-service.py user-profile-service integration
```

The helper accepts identity-service, messages-dialogues-service, object-storage-service, user-profile-service, and websocket-gateway-service. It uses the selected service as cwd, propagates failures, and never changes dependency declarations or lock files. `setup` runs `poetry sync --with dev`; use it explicitly in a new checkout/worktree. A compatible Python version must already be installed. Other actions require an existing Poetry environment and do not install dependencies automatically.

`lint` runs Ruff check and format check without applying fixes. `unit` runs tests/unit; `integration` runs tests/integration and may need Docker or configured infrastructure. Check the selected service's README and test fixtures before integration runs. api-gateway has no Python pyproject.toml at the time of setup and is deliberately excluded.

From inside a service, equivalent commands are `poetry run ruff check .`, `poetry run ruff format --check .`, `poetry run pytest tests/unit -q`, and `poetry run pytest tests/integration -q`.

Use targeted tests during implementation and the repository's required checks before completion. Do not interpret successful collection or tool availability as passing tests.
