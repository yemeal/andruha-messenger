"""Run Messages integration checks on an exclusively owned Cassandra container."""

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    name = "andruha-messages-check-" + uuid.uuid4().hex[:10]
    started = False
    try:
        subprocess.run(
            [
                "docker", "run", "--detach", "--rm", "--name", name,
                "--publish", "127.0.0.1::9042", "--env", "MAX_HEAP_SIZE=512M",
                "--env", "HEAP_NEWSIZE=128M", "cassandra:5.0.8-bookworm",
            ], check=True, stdout=subprocess.DEVNULL,
        )
        started = True
        print(f"Disposable Cassandra: {name}", flush=True)
        deadline = time.monotonic() + 180
        while subprocess.run(
            ["docker", "exec", name, "cqlsh", "-e", "SELECT release_version FROM system.local;"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        ).returncode:
            if time.monotonic() >= deadline:
                raise RuntimeError("Disposable Cassandra startup timed out")
            time.sleep(1)
        port = subprocess.check_output(
            ["docker", "port", name, "9042/tcp"], text=True,
        ).strip().rsplit(":", 1)[1]
        environment = os.environ | {
            "MESSAGES_TEST_CASSANDRA_HOST": "127.0.0.1",
            "MESSAGES_TEST_CASSANDRA_PORT": port,
        }
        environment.pop("VIRTUAL_ENV", None)
        if sys.argv[1:]:
            return subprocess.run(
                ["uv", "run", "pytest", *sys.argv[1:]],
                cwd=ROOT / "services/messages-dialogues-service", env=environment, check=False,
            ).returncode
        return subprocess.run(
            [sys.executable, "scripts/codex-service.py", "messages-dialogues-service", "integration"],
            cwd=ROOT, env=environment, check=False,
        ).returncode
    finally:
        if started:
            subprocess.run(
                ["docker", "rm", "--force", name], check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )


if __name__ == "__main__":
    raise SystemExit(main())
