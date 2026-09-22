"""Run explicit uv setup/checks in an Andruha Python service."""

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
    uv = shutil.which("uv")
    if not uv:
        parser.error("uv is not installed or not on PATH")
    if args.action != "setup":
        venv = service / ".venv"
        if not venv.is_dir():
            parser.error(
                "No existing virtual environment (.venv). Run this helper with action setup first."
            )
    commands = {
        "setup": [["sync"]],
        "check-tools": [
            ["run", "python", "--version"],
            ["run", "ruff", "--version"],
            ["run", "ty", "--version"],
            ["run", "pytest", "--version"],
            ["run", "prek", "--version"],
        ],
        "lint": [
            ["run", "prek", "run", "--all-files"],
        ],
        "unit": [["run", "pytest", "tests/unit", "-q"]],
        "integration": [["run", "pytest", "tests/integration", "-q"]],
    }
    for command in commands[args.action]:
        print(f"[{args.service}] uv {' '.join(command)}", flush=True)
        result = subprocess.run([uv, *command], cwd=service, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
