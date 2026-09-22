# Andruha workspace

- Before modifying a service, inspect its Git status and any instructions inside that service. Services are independent Git repositories/submodules; preserve existing changes in both the parent and service repositories.
- Keep changes within the requested service and its public contracts. Cross-service changes require an explicit task scope.
- Domain behavior belongs in domain/application code; keep transport and persistence details in adapters. Verify actual implementation before claiming architectural guarantees.
- For environment setup or verification, read `docs/codex-environment.md` and use `scripts/codex-service.py` from the parent repository. When working directly inside a service, use its uv commands with that service as the working directory.
- In an audit, report findings and an approval-ready plan before changing implementation. Directly requested implementation work may proceed within its authorized scope.
- Distinguish unit tests, integration tests, and checks that were not run. Keep intentional failing TDD exercises when requested.
