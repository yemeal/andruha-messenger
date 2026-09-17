"""Build, migrate, test and clean up a separate Identity/Profile Docker stack."""

import argparse
import json
import subprocess

from environment import IMAGE_TAG, ROOT, prepare
from identity import Suite


def main(keep):
    directory = prepare()
    print(f"E2E artifacts: {directory}", flush=True)
    compose = ["docker", "compose", "-f", str(directory / "compose.json")]

    def command(args, label):
        with (directory / f"{label}.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True
            )

    try:
        for service in ("identity-service", "user-profile-service", "api-gateway"):
            print(f"BUILD {service}", flush=True)
            command(
                [
                    "docker",
                    "build",
                    "--target",
                    "runtime",
                    "-t",
                    f"andruha/{service}:{IMAGE_TAG}",
                    str(ROOT / "services" / service),
                ],
                f"build-{service}",
            )
        command(
            compose
            + [
                "up",
                "-d",
                "--wait",
                "identity-postgres",
                "profile-postgres",
                "valkey",
                "kafka",
            ],
            "infrastructure",
        )
        for service in ("identity-service", "user-profile-service"):
            command(
                compose + ["run", "--rm", "-T", service, "alembic", "upgrade", "head"],
                f"migrate-{service}",
            )
        command(compose + ["up", "-d", "--wait"], "startup")
        return Suite(directory).run()
    finally:
        command(compose + ["ps", "--all", "--format", "json"], "containers")
        if not keep:
            command(compose + ["down", "--volumes"], "cleanup")
            (directory / "cleanup.json").write_text(
                json.dumps({"containers_and_volumes_removed": True})
            )
        print(f"E2E artifacts: {directory}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep", action="store_true", help="Keep this E2E project for inspection"
    )
    args = parser.parse_args()
    raise SystemExit(main(args.keep))
