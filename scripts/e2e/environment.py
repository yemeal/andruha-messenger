"""Create a private Docker Compose project from the repository's service definitions."""

import argparse
import base64
import json
import secrets
import subprocess
import tempfile
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[2]
IMAGE_TAG = "e2e-20260916"
SERVICES = (
    "api-gateway",
    "identity-service",
    "identity-relay",
    "identity-registration-reconciler",
    "user-profile-service",
    "identity-postgres",
    "profile-postgres",
    "valkey",
    "kafka",
)


def prepare():
    directory = Path(tempfile.mkdtemp(prefix="andruha-identity-e2e-"))
    project = "andruha-e2e-" + uuid.uuid4().hex[:10]
    source = json.loads(
        subprocess.check_output(
            [
                "docker",
                "compose",
                "-f",
                str(ROOT / "docker-compose.yml"),
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        )
    )
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (directory / "private.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    (directory / "public.pem").write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    (directory / "replay.key").write_text(
        base64.b64encode(secrets.token_bytes(32)).decode()
    )
    config = {"name": project, "services": {}, "volumes": {}}
    token = secrets.token_hex(24)
    for name in SERVICES:
        service = source["services"][name]
        for field in ("networks", "depends_on", "secrets", "configs", "build", "ports"):
            service.pop(field, None)
        if name in {"api-gateway", "identity-service", "user-profile-service"}:
            service["image"] = f"andruha/{name}:{IMAGE_TAG}"
        elif name.startswith("identity-") and name != "identity-postgres":
            service["image"] = f"andruha/identity-service:{IMAGE_TAG}"
        for volume in service.get("volumes", []):
            config["volumes"][volume["source"]] = {}
        if "healthcheck" in service:
            service["healthcheck"].update(interval="2s", retries=45, start_period="2s")
        env = service.setdefault("environment", {})
        if name.startswith("identity-") and name != "identity-postgres":
            env.update(
                {
                    "DEV_LOGS": "false",
                    "RUN_MIGRATIONS": "false",
                    "DATABASE_HOST": "identity-postgres",
                    "DATABASE_USER": "andruha_identity",
                    "DATABASE_PASSWORD": "identity-e2e-only",
                    "DATABASE_NAME": "andruha_identity",
                    "PROFILE_SERVICE_URL": "http://profile-proxy:8010",
                    "PROFILE_SERVICE_TOKEN": token,
                    "PROFILE_SERVICE_TIMEOUT_SECONDS": "3",
                    "PROFILE_SERVICE_CB_RECOVERY_SECONDS": "2",
                    "REGISTRATION_CLAIM_LEASE_SECONDS": "12",
                    "REGISTRATION_POLL_INTERVAL_SECONDS": "0.3",
                    "REGISTRATION_RETRY_INITIAL_SECONDS": "0.3",
                    "REGISTRATION_RETRY_MAX_SECONDS": "1",
                    "REGISTRATION_RETRY_JITTER_RATIO": "0",
                    "REGISTRATION_RETRY_MAX_ATTEMPTS": "50",
                    "IDEMPOTENCY_CB_RECOVERY_SECONDS": "2",
                    "IDEMPOTENCY_LEASE_SECONDS": "5",
                    "OUTBOX_POLL_INTERVAL_SECONDS": "0.3",
                    "OUTBOX_RETRY_MAX_ATTEMPTS": "50",
                    "OUTBOX_CLAIM_LEASE_SECONDS": "5",
                    "OUTBOX_RETRY_MAX_SECONDS": "2",
                    "AUTH_COOKIE_SECURE": "false",
                    "JWT_CLOCK_SKEW_SECONDS": "0",
                    "KAFKA_USER_REGISTERED_TOPIC": "identity.events.v1",
                }
            )
            service["volumes"] = [
                f"{(directory / 'private.pem').as_posix()}:/run/secrets/identity_jwt_private_key:ro",
                f"{(directory / 'public.pem').as_posix()}:/run/configs/identity_jwt_public_key:ro",
                f"{(directory / 'replay.key').as_posix()}:/run/secrets/identity_replay_key:ro",
            ]
        if name == "identity-postgres":
            env.update(
                POSTGRES_USER="andruha_identity",
                POSTGRES_DB="andruha_identity",
                POSTGRES_PASSWORD="identity-e2e-only",
            )
        if name == "profile-postgres":
            env.update(
                POSTGRES_USER="andruha_profile",
                POSTGRES_DB="andruha_profile",
                POSTGRES_PASSWORD="profile-e2e-only",
            )
        if name == "user-profile-service":
            env.update(
                {
                    "PROFILE_POSTGRES_HOST": "profile-postgres",
                    "PROFILE_POSTGRES_PORT": "5432",
                    "PROFILE_POSTGRES_USER": "andruha_profile",
                    "PROFILE_POSTGRES_PASSWORD": "profile-e2e-only",
                    "PROFILE_POSTGRES_DB": "andruha_profile",
                    "PROFILE_REDIS_HOST": "valkey",
                    "PROFILE_REDIS_PORT": "6379",
                    "PROFILE_REDIS_DB": "1",
                    "POSTGRES_HOST": "profile-postgres",
                    "POSTGRES_PORT": "5432",
                    "POSTGRES_USER": "andruha_profile",
                    "POSTGRES_PASSWORD": "profile-e2e-only",
                    "POSTGRES_DB": "andruha_profile",
                    "REDIS_HOST": "valkey",
                    "REDIS_PORT": "6379",
                    "REDIS_DB": "1",
                    "INTERNAL_API_TOKEN": token,
                    "JWT_PUBLIC_KEYS": '{"identity-v1":"/run/configs/identity_jwt_public_key"}',
                    "JWT_CLOCK_SKEW_SECONDS": "0",
                    "DEV_LOGS": "false",
                    "IDEMPOTENCY_CB_RECOVERY_SECONDS": "2",
                }
            )
            service["volumes"] = [
                f"{(directory / 'public.pem').as_posix()}:/run/configs/identity_jwt_public_key:ro"
            ]
        if name in {"api-gateway", "identity-service", "user-profile-service"}:
            port = {
                "api-gateway": 8080,
                "identity-service": 8001,
                "user-profile-service": 8002,
            }[name]
            service["ports"] = [f"127.0.0.1::{port}"]
        config["services"][name] = service
    config["services"]["profile-proxy"] = {
        "image": f"andruha/identity-service:{IMAGE_TAG}",
        "entrypoint": ["python", "/e2e/profile_proxy.py"],
        "volumes": [f"{(ROOT / 'scripts/e2e').as_posix()}:/e2e:ro"],
        "ports": ["127.0.0.1::8010"],
    }
    (directory / "compose.json").write_text(
        json.dumps(config, indent=2), encoding="utf-8"
    )
    (directory / "manifest.json").write_text(
        json.dumps({"project": project, "service_token": token})
    )
    return directory


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(prepare(), flush=True)
