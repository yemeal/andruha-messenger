"""Run Profile checks against privately owned disposable Docker dependencies."""

import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    prefix = "andruha-profile-check-" + uuid.uuid4().hex[:10]
    postgres = prefix + "-postgres"
    valkey = prefix + "-valkey"
    password = secrets.token_hex(24)
    owned: list[str] = []

    def docker(*args: str) -> str:
        return subprocess.check_output(
            ["docker", *args], text=True, encoding="utf-8", stderr=subprocess.PIPE
        ).strip()

    try:
        docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            postgres,
            "--publish",
            "127.0.0.1::5432",
            "--env",
            "POSTGRES_USER=profile_test",
            "--env",
            "POSTGRES_DB=profile_test",
            "--env",
            f"POSTGRES_PASSWORD={password}",
            "postgres:18-alpine",
        )
        owned.append(postgres)
        docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            valkey,
            "--publish",
            "127.0.0.1::6379",
            "valkey/valkey:8.1-alpine",
        )
        owned.append(valkey)
        deadline = time.monotonic() + 45
        while subprocess.run(
            ["docker", "exec", postgres, "pg_isready", "-U", "profile_test"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode:
            if time.monotonic() >= deadline:
                raise RuntimeError("Disposable PostgreSQL startup timed out")
            time.sleep(0.5)
        pg_port = docker("port", postgres, "5432/tcp").rsplit(":", 1)[1]
        redis_port = docker("port", valkey, "6379/tcp").rsplit(":", 1)[1]
        dsn = f"postgresql+asyncpg://profile_test:{password}@127.0.0.1:{pg_port}/profile_test"
        environment = os.environ | {
            "TEST_PROFILE_POSTGRES_DSN": dsn,
            "TEST_IDEMPOTENCY_POSTGRES_DSN": dsn,
            "TEST_IDEMPOTENCY_REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
            "REQUIRE_INFRASTRUCTURE_TESTS": "1",
        }
        print(f"Disposable Profile resources: {prefix}", flush=True)
        if sys.argv[1:]:
            return subprocess.run(
                ["uv", "run", "pytest", *sys.argv[1:]],
                cwd=ROOT / "services/user-profile-service",
                env=environment,
            ).returncode
        return subprocess.run(
            [
                sys.executable,
                "scripts/codex-service.py",
                "user-profile-service",
                "integration",
            ],
            cwd=ROOT,
            env=environment,
        ).returncode
    finally:
        for name in reversed(owned):
            subprocess.run(
                ["docker", "rm", "--force", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


if __name__ == "__main__":
    raise SystemExit(main())
