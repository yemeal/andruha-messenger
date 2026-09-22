# Codex environment

Repository-local helper commands for consistent service setup and verification.

## Python service commands

From the parent repository, use:

```powershell
python scripts/codex-service.py user-profile-service check-tools
python scripts/codex-service.py user-profile-service setup
python scripts/codex-service.py user-profile-service lint
python scripts/codex-service.py user-profile-service unit
python scripts/codex-service.py user-profile-service integration
```

The helper accepts identity-service, messages-dialogues-service, object-storage-service, user-profile-service, and websocket-gateway-service. It uses the selected service as cwd, propagates failures, and never changes dependency declarations or lock files. `setup` runs `uv sync`; use it explicitly in a new checkout/worktree. A compatible Python version must already be installed. Other actions require an existing uv virtual environment (`.venv`) and do not install dependencies automatically.

`lint` runs `prek run --all-files` (covering Ruff lint/format, ty static type checking, lockfile checks, and security/syntax sanity checks). `unit` runs `pytest tests/unit -q`; `integration` runs `pytest tests/integration -q` and may need Docker or configured infrastructure. Check the selected service's README and test fixtures before integration runs. api-gateway has no Python pyproject.toml at the time of setup and is deliberately excluded.

From inside a service, equivalent commands are `uv sync`, `uv run prek install`, `uv run prek run --all-files`, `uv run pytest tests/unit -q`, and `uv run pytest tests/integration -q`.

Use targeted tests during implementation and the repository's required checks before completion. Do not interpret successful collection or tool availability as passing tests.
