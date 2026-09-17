"""Run explicit Poetry setup/checks in an Andruha Python service."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

SERVICES = (
    "identity-service",
    "messages-dialogues-service",
    "object-storage-service",
    "user-profile-service",
    "websocket-gateway-service",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=SERVICES)
    parser.add_argument(
        "action", choices=("setup", "check-tools", "lint", "unit", "integration")
    )
    args = parser.parse_args()
    service = Path(__file__).resolve().parents[1] / "services" / args.service
    if not (service / "pyproject.toml").is_file():
        parser.error(f"Missing service pyproject.toml: {service}")
    poetry = shutil.which("poetry")
    if not poetry:
        parser.error("Poetry is not installed or not on PATH")
    if args.action != "setup":
        probe = subprocess.run(
            [poetry, "env", "info", "--path"],
            cwd=service,
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode or not probe.stdout.strip():
            parser.error(
                "No existing Poetry environment. Run this helper with action setup first."
            )
    commands = {
        "setup": [["sync", "--with", "dev"]],
        "check-tools": [
            ["run", "python", "--version"],
            ["run", "ruff", "--version"],
            ["run", "pytest", "--version"],
        ],
        "lint": [
            ["run", "ruff", "check", "."],
            ["run", "ruff", "format", "--check", "."],
        ],
        "unit": [["run", "pytest", "tests/unit", "-q"]],
        "integration": [["run", "pytest", "tests/integration", "-q"]],
    }
    for command in commands[args.action]:
        print(f"[{args.service}] poetry {' '.join(command)}", flush=True)
        result = subprocess.run([poetry, *command], cwd=service, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
