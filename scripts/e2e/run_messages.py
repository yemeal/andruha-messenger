"""Verify registered A/B text messaging on a private Identity/Profile/Messages stack."""

import argparse
import json
import secrets
import subprocess
import uuid

from environment import ROOT, prepare
from identity import Suite


def run(*, keep=False):
    directory = prepare()
    print(f"Messages E2E artifacts: {directory}", flush=True)
    compose_path = directory / "compose.json"
    config = json.loads(compose_path.read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text())
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
    tag = "messages-e2e-" + uuid.uuid4().hex[:10]
    for service in config["services"].values():
        image = service.get("image", "")
        if image.startswith("andruha/"):
            service["image"] = image.rsplit(":", 1)[0] + ":" + tag
    (directory / "cursor.key").write_bytes(secrets.token_bytes(32))
    for name in (
        "messages-cassandra",
        "messages-keyspace",
        "messages-migrate",
        "messages-dialogues-service",
    ):
        service = source["services"][name]
        for field in ("networks", "secrets", "configs", "build", "ports"):
            service.pop(field, None)
        if name in ("messages-migrate", "messages-dialogues-service"):
            service["image"] = f"andruha/messages-dialogues-service:{tag}"
        for volume in service.get("volumes", []):
            config["volumes"][volume["source"]] = {}
        if "healthcheck" in service:
            service["healthcheck"].update(interval="2s", retries=90, start_period="2s")
        if name == "messages-dialogues-service":
            service["environment"].update(
                {
                    "DEV_LOGS": "false",
                    "MESSAGING_ENABLED": "true",
                    "MESSAGING_IDENTITY_SERVICE_TOKEN": manifest[
                        "identity_internal_token"
                    ],
                    "MESSAGING_CURSOR_KEY_FILE": "/run/secrets/messages_cursor_key",
                    "JWT_CLOCK_SKEW_SECONDS": "0",
                }
            )
            service["volumes"] = [
                f"{(directory / 'public.pem').as_posix()}:/run/configs/identity_jwt_public_key:ro",
                f"{(directory / 'cursor.key').as_posix()}:/run/secrets/messages_cursor_key:ro",
            ]
            service["ports"] = ["127.0.0.1::8003"]
            service["init"] = True
        config["services"][name] = service
    compose_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    compose = ["docker", "compose", "-f", str(compose_path)]
    checks = []
    suite = None

    def command(arguments, label, *, timeout=600):
        with (directory / f"{label}.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                arguments,
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=timeout,
            )

    def check(label):
        checks.append(label)
        print(f"PASS {label}", flush=True)
        (directory / "messages-results.json").write_text(
            json.dumps({"passed": len(checks), "checks": checks}, indent=2),
            encoding="utf-8",
        )

    try:
        for service in (
            "identity-service",
            "user-profile-service",
            "api-gateway",
            "messages-dialogues-service",
        ):
            print(f"BUILD {service}", flush=True)
            command(
                [
                    "docker",
                    "build",
                    "--target",
                    "runtime",
                    "-t",
                    f"andruha/{service}:{tag}",
                    str(ROOT / "services" / service),
                ],
                f"build-{service}",
            )
        command(
            [
                *compose,
                "up",
                "-d",
                "--wait",
                "identity-postgres",
                "profile-postgres",
                "valkey",
                "kafka",
                "messages-cassandra",
            ],
            "infrastructure",
        )
        for service in ("identity-service", "user-profile-service"):
            command(
                [
                    *compose,
                    "run",
                    "--rm",
                    "-T",
                    "--no-deps",
                    service,
                    "alembic",
                    "upgrade",
                    "head",
                ],
                f"migrate-{service}",
            )
        command([*compose, "up", "-d", "--wait"], "startup")
        suite = Suite(directory)
        email_a, user_a = suite.new_user("messages-a")
        email_b, user_b = suite.new_user("messages-b")
        email_c, _ = suite.new_user("messages-outsider")
        a, b, c = suite.login(email_a), suite.login(email_b), suite.login(email_c)
        check("A/B registration, durable profiles and Identity login")

        def request(method, path, cookies=a, **kwargs):
            return suite.request(method, path, cookies=cookies, **kwargs)

        created = suite.status(
            request("POST", "/api/v1/dialogues/direct", json={"peerId": user_b}), 201
        ).json()
        dialog = created["dialog"]["dialogId"]
        reverse = suite.status(
            request(
                "POST", "/api/v1/dialogues/direct", cookies=b, json={"peerId": user_a}
            ),
            200,
        ).json()
        assert reverse["dialog"]["dialogId"] == dialog
        check("A-B and B-A create one canonical Direct through Gateway")
        path = f"/api/v1/dialogues/{dialog}/messages"
        send = {
            "clientMessageId": str(uuid.uuid7()),
            "text": "Привет из реального Identity",
        }
        first = suite.status(request("POST", path, json=send), 200).json()
        futures = [
            suite.executor.submit(request, "POST", path, json=send) for _ in range(8)
        ]
        assert all(suite.status(job.result(), 200).json() == first for job in futures)
        assert first["message"]["position"] == 1
        check("Eight concurrent retries keep one message ID and position")
        for index in range(3):
            suite.status(
                request(
                    "POST",
                    path,
                    cookies=b if index % 2 else a,
                    json={
                        "clientMessageId": str(uuid.uuid7()),
                        "text": f"Сообщение {index}",
                    },
                ),
                200,
            )
        page = suite.status(
            request("GET", path, cookies=b, params={"limit": 2}), 200
        ).json()
        old = list(page["items"])
        suite.status(
            request(
                "POST",
                path,
                json={
                    "clientMessageId": str(uuid.uuid7()),
                    "text": "После снимка истории",
                },
            ),
            200,
        )
        while page["nextCursor"]:
            page = suite.status(
                request(
                    "GET",
                    path,
                    cookies=b,
                    params={"limit": 2, "cursor": page["nextCursor"]},
                ),
                200,
            ).json()
            old.extend(page["items"])
        assert [item["position"] for item in old] == [1, 2, 3, 4]
        history = suite.status(request("GET", path, cookies=b), 200).json()["items"]
        assert [item["position"] for item in history] == [1, 2, 3, 4, 5]
        check("History pagination holds its upper position during a concurrent send")
        sync_items = []
        cursor = None
        while True:
            page = suite.status(
                request(
                    "GET",
                    "/api/v1/dialogues/sync",
                    cookies=b,
                    params={"limit": 2, **({"cursor": cursor} if cursor else {})},
                ),
                200,
            ).json()
            sync_items.extend(page["items"])
            cursor = page["cursor"]
            if not page["hasMore"]:
                break
        synced = [item["message"] for item in sync_items if item["message"]]
        assert {item["messageId"] for item in synced} == {
            item["messageId"] for item in history
        }
        assert len(synced) == 5
        assert (
            suite.status(
                request(
                    "GET",
                    "/api/v1/dialogues/sync",
                    cookies=b,
                    params={"cursor": cursor},
                ),
                200,
            ).json()["items"]
            == []
        )
        check(
            "Recipient HTTP sync returns every send once and resumes without duplicates"
        )
        cards = suite.status(
            request("GET", "/api/v1/dialogues/", cookies=b), 200
        ).json()["items"]
        assert [item["dialogId"] for item in cards] == [dialog]
        assert cards[0]["lastPosition"] == 5
        saved = suite.status(request("POST", "/api/v1/dialogues/saved"), 201).json()[
            "dialog"
        ]["dialogId"]
        suite.status(
            request("POST", f"/api/v1/dialogues/{saved}/messages", json=send), 409
        )
        suite.status(
            request(
                "POST",
                f"/api/v1/dialogues/{saved}/messages",
                json={
                    "clientMessageId": str(uuid.uuid7()),
                    "text": "Сохранённая заметка",
                },
            ),
            200,
        )
        check("Dialog card activity, Saved text and cross-dialog send-key conflict")
        suite.status(request("GET", path, cookies=c), 404)
        suite.status(request("GET", path, cookies={}), 401)
        suite.status(request("POST", path, json=send | {"actorId": user_b}), 422)
        suite.status(
            request("GET", "/api/v1/dialogues/sync", params={"cursor": cursor}), 400
        )
        check(
            "Foreign dialog, anonymous request, actor spoof and foreign cursor denied"
        )
        suite.dc("restart", "messages-dialogues-service")
        suite.eventually(
            lambda: (
                suite.request("GET", "/health/ready", service="api-gateway").status_code
                == 200
                and request("GET", path, cookies=b).status_code == 200
            ),
            "Messages restart",
            timeout=90,
        )
        assert suite.status(request("POST", path, json=send), 200).json() == first
        check("Messages process restart preserves the send result")
        # Role readiness must follow Cassandra while process liveness remains up.
        messages_url = (
            "http://" + suite.dc("port", "messages-dialogues-service", "8003").strip()
        )
        suite.dc("stop", "messages-cassandra")
        import httpx

        with httpx.Client(timeout=10, trust_env=False) as client:
            assert client.get(messages_url + "/health/live").status_code == 200
            assert client.get(messages_url + "/health/ready").status_code == 503
        suite.status(request("GET", path, cookies=b), 503)
        suite.dc("start", "messages-cassandra")
        suite.eventually(
            lambda: request("GET", path, cookies=b).status_code == 200,
            "Cassandra reconnect",
            timeout=180,
        )
        assert suite.status(request("POST", path, json=send), 200).json() == first
        check("Cassandra outage gives 503 and recovers without losing accepted text")
        image_id = subprocess.check_output(
            [
                "docker",
                "image",
                "inspect",
                f"andruha/messages-dialogues-service:{tag}",
                "--format",
                "{{.Id}}",
            ],
            text=True,
        ).strip()
        (directory / "messages-results.json").write_text(
            json.dumps(
                {
                    "passed": len(checks),
                    "checks": checks,
                    "messages_image": f"andruha/messages-dialogues-service:{tag}",
                    "messages_image_id": image_id,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return 0
    finally:
        if suite is not None:
            suite.executor.shutdown(wait=True)
        command([*compose, "ps", "--all", "--format", "json"], "containers")
        command([*compose, "logs", "--no-color"], "all-containers")
        if not keep:
            command([*compose, "down", "--volumes"], "cleanup")
            (directory / "cleanup.json").write_text(
                json.dumps({"containers_and_volumes_removed": True})
            )
        print(f"Messages E2E artifacts: {directory}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    raise SystemExit(run(keep=args.keep))
