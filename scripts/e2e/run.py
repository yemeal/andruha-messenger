"""Build, migrate, test and clean up a separate Identity/Profile Docker stack."""

import argparse
import json
import os
import shutil
import subprocess

from environment import IMAGE_TAG, ROOT, prepare
from identity import Suite


def main(
    keep,
    *,
    custom_identity_credentials=False,
    only=None,
    relay_repeats=0,
    messages_lookup=False,
):
    directory = prepare(custom_identity_credentials=custom_identity_credentials)
    print(f"E2E artifacts: {directory}", flush=True)
    compose = ["docker", "compose", "-f", str(directory / "compose.json")]

    def command(args, label, *, cwd=ROOT, env=None):
        with (directory / f"{label}.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                args, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True
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
        result = Suite(directory).run(only=only)
        shutil.copy2(directory / "results.json", directory / "results-main.json")
        if messages_lookup:
            suite = Suite(directory)
            lookup_environment = os.environ | {
                "ANDRUHA_TEST_IDENTITY_URL": suite.urls["identity-service"],
                "ANDRUHA_TEST_IDENTITY_INTERNAL_TOKEN": suite.manifest["identity_internal_token"],
            }
            lookup_environment.pop("VIRTUAL_ENV", None)
            command(
                [
                    "uv",
                    "run",
                    "pytest",
                    "tests/e2e/test_identity_lookup.py",
                    "-q",
                    "--tb=short",
                    "--show-capture=no",
                ],
                "messages-identity-lookup",
                cwd=ROOT / "services/messages-dialogues-service",
                env=lookup_environment,
            )
            suite.executor.shutdown()
        for attempt in range(1, relay_repeats + 1):
            repeated = Suite(directory).run(
                only=["relay_automatic_bootstrap_and_claim_recovery"]
            )
            shutil.copy2(
                directory / "results.json",
                directory / f"results-relay-repeat-{attempt}.json",
            )
            result = result or repeated
        shutil.copy2(directory / "results-main.json", directory / "results.json")
        return result
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
    parser.add_argument("--custom-identity-credentials", action="store_true")
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--relay-repeats", type=int, default=0)
    parser.add_argument("--messages-lookup", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        main(
            args.keep,
            custom_identity_credentials=args.custom_identity_credentials,
            only=args.only,
            relay_repeats=args.relay_repeats,
            messages_lookup=args.messages_lookup,
        )
    )
