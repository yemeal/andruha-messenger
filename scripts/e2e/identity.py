"""Exercise running Identity/Profile containers and inspect durable state after faults."""

import argparse
import json
import subprocess
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import httpx
import jwt


class Suite:
    def __init__(self, directory):
        self.directory = directory.resolve()
        self.manifest = json.loads((directory / "manifest.json").read_text())
        if not self.manifest["project"].startswith("andruha-e2e-"):
            raise ValueError("Only an isolated E2E project can be tested")
        self.compose = ["docker", "compose", "-f", str(directory / "compose.json")]
        self.urls = {
            name: "http://" + self.dc("port", name, str(port)).strip()
            for name, port in {
                "api-gateway": 8080,
                "identity-service": 8001,
                "user-profile-service": 8002,
                "profile-proxy": 8010,
            }.items()
        }
        self.results = []
        self.responses = []
        self.secrets = {self.manifest["service_token"]}
        self.password = "E2E-password-canary-" + uuid.uuid4().hex
        self.secrets.add(self.password)
        self.prefix = uuid.uuid4().hex[:10]
        self.executor = ThreadPoolExecutor(max_workers=10)

    def dc(self, *args, input=None, timeout=90, check=True):
        process = subprocess.run(
            self.compose + list(args),
            input=input,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
        if check and process.returncode:
            raise RuntimeError(
                f"Compose {args[:3]} exited {process.returncode}: {process.stderr[-1000:]}"
            )
        return process.stdout + process.stderr if args[0] == "logs" else process.stdout

    def sql(self, service, query):
        user = (
            "andruha_identity" if service == "identity-postgres" else "andruha_profile"
        )
        output = self.dc(
            "exec",
            "-T",
            service,
            "psql",
            "-X",
            "-qAt",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            user,
            "-d",
            user,
            input=query,
        )
        return output.strip()

    def rows(self, service, query):
        return json.loads(
            self.sql(service, f"SELECT coalesce(json_agg(r), '[]') FROM ({query}) r;")
        )

    def request(self, method, path, *, service="api-gateway", cookies=None, **kwargs):
        with httpx.Client(timeout=20, trust_env=False, cookies=cookies or {}) as client:
            response = client.request(method, self.urls[service] + path, **kwargs)
        self.responses.append(
            {
                "method": method,
                "path": path,
                "status": response.status_code,
                "service": service,
            }
        )
        for cookie in response.cookies.jar:
            if cookie.value:
                self.secrets.add(cookie.value)
        if response.status_code >= 400:
            assert self.password not in response.text, (
                "Password leaked into error response"
            )
            assert not any(
                word in response.text
                for word in ("Traceback", "$argon2", "asyncpg", "sqlalchemy")
            ), "Internal error leaked"
        return response

    @staticmethod
    def status(response, *expected):
        assert response.status_code in expected, (
            f"HTTP {response.status_code}, expected {expected} on {response.request.url.path}"
        )
        return response

    @staticmethod
    def eventually(predicate, description, timeout=45):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            result = predicate()
            if result:
                return result
            time.sleep(0.3)
        raise AssertionError(f"Timed out: {description}")

    def case(self, name, action):
        start = time.monotonic()
        print(f"RUN {name}", flush=True)
        try:
            action()
        except Exception as error:  # noqa: BLE001 - collect independent scenario failures
            result = {
                "name": name,
                "status": "FAIL",
                "error": str(error),
                "traceback": traceback.format_exc(),
            }
        else:
            result = {"name": name, "status": "PASS"}
        result["seconds"] = round(time.monotonic() - start, 2)
        self.results.append(result)
        print(f"{result['status']} {name}: {result.get('error', '')}", flush=True)
        self.save()

    def save(self):
        (self.directory / "results.json").write_text(
            json.dumps({"cases": self.results, "http": self.responses}, indent=2),
            encoding="utf-8",
        )

    def key(self):
        return str(uuid.uuid4())

    def email(self, label):
        return f"e2e-{self.prefix}-{label}@example.com"

    def register(self, email, key, password=None):
        return self.request(
            "POST",
            "/api/v1/auth/register",
            json={"email": email, "password": password or self.password},
            headers={"Idempotency-Key": key},
        )

    def operation(self, email):
        rows = self.rows(
            "identity-postgres",
            f"SELECT id, user_id, status, attempts, claim_token, password_hash IS NULL AS scrubbed, redrive_count, created_at FROM registration_operations WHERE email='{email.lower()}'",
        )
        return rows[0] if rows else None

    def complete(self, email, key):
        operation = self.eventually(
            lambda: (
                op
                if (op := self.operation(email)) and op["status"] == "COMPLETED"
                else None
            ),
            "registration completes",
        )
        result = self.status(self.register(email, key), 201)
        assert result.json()["userId"] == operation["user_id"]
        self.check_user(operation["user_id"])
        return operation["user_id"]

    def new_user(self, label):
        email, key = self.email(label), self.key()
        response = self.status(self.register(email, key), 201, 202)
        user = self.complete(email, key)
        assert response.json()["userId"] == user
        return email, user

    def login(self, email):
        response = self.status(
            self.request(
                "POST",
                "/api/v1/auth/login",
                json={"email": email, "password": self.password},
            ),
            204,
        )
        assert not response.content
        assert response.headers["cache-control"] == "no-store"
        cookies = dict(response.cookies)
        assert set(cookies) == {"access_token", "refresh_token"}
        assert all(
            "HttpOnly" in value for value in response.headers.get_list("set-cookie")
        )
        return cookies

    def refresh(self, cookies, key=None):
        return self.request(
            "POST",
            "/api/v1/auth/refresh",
            cookies=cookies,
            headers={"Idempotency-Key": key or self.key()},
        )

    def sessions(self, user):
        return self.rows(
            "identity-postgres",
            f"SELECT s.id, s.revoked_at, s.idle_expires_at, count(t.id) AS tokens, count(t.id) FILTER (WHERE t.used_at IS NULL) AS unused FROM auth_sessions s JOIN refresh_tokens t ON t.session_id=s.id WHERE s.user_id='{user}' GROUP BY s.id",
        )

    def check_user(self, user):
        identity = self.rows(
            "identity-postgres", f"SELECT id, created_at FROM users WHERE id='{user}'"
        )
        profile = self.rows(
            "profile-postgres",
            f"SELECT user_id, created_at FROM profiles WHERE user_id='{user}'",
        )
        settings = self.rows(
            "profile-postgres",
            f"SELECT user_id, created_at FROM user_settings WHERE user_id='{user}'",
        )
        assert len(identity) == len(profile) == len(settings) == 1, (
            "Identity/Profile/Settings cardinality mismatch"
        )
        timestamps = {
            datetime.fromisoformat(row["created_at"])
            for row in (identity[0], profile[0], settings[0])
        }
        assert len(timestamps) == 1, "Registration timestamps differ"
        events = self.rows(
            "identity-postgres", f"SELECT id FROM outbox WHERE key='{user}'"
        )
        assert len(events) == 1, "Registration must produce exactly one Outbox row"

    def wait_ready(self, service):
        port = {"identity-service": 8001, "user-profile-service": 8002}[service]
        self.urls[service] = "http://" + self.dc("port", service, str(port)).strip()

        def ready():
            try:
                return (
                    self.request("GET", "/health/ready", service=service).status_code
                    == 200
                )
            except httpx.TransportError:
                return False

        self.eventually(ready, f"{service} ready")

    @contextmanager
    def stopped(self, *services):
        self.dc("stop", "-t", "2", *services)
        try:
            yield
        finally:
            self.dc("start", *services)
            for service in services:
                if service in {"identity-service", "user-profile-service"}:
                    self.wait_ready(service)

    def proxy(self, mode):
        self.status(
            self.request(
                "POST", "/control", service="profile-proxy", json={"mode": mode}
            ),
            200,
        )

    def normal_registration(self):
        self.main_email, self.main_user = self.new_user("main")
        self.main_cookies = self.login(self.main_email)
        response = self.status(
            self.request("GET", "/api/v1/auth/me", cookies=self.main_cookies), 200
        )
        assert response.json()["id"] == self.main_user
        assert "password_hash" not in response.text
        self.status(
            self.request("GET", "/api/v1/profiles/me", cookies=self.main_cookies), 200
        )

    def registration_validation(self):
        before = self.sql(
            "identity-postgres", "SELECT count(*) FROM registration_operations;"
        )
        for body, headers in [
            (
                {"email": "invalid", "password": self.password},
                {"Idempotency-Key": self.key()},
            ),
            (
                {"email": self.email("short"), "password": "short"},
                {"Idempotency-Key": self.key()},
            ),
            (
                {"email": self.email("long"), "password": "x" * 129},
                {"Idempotency-Key": self.key()},
            ),
            ({"email": self.email("no-key"), "password": self.password}, {}),
        ]:
            self.status(
                self.request(
                    "POST", "/api/v1/auth/register", json=body, headers=headers
                ),
                422,
            )
        assert before == self.sql(
            "identity-postgres", "SELECT count(*) FROM registration_operations;"
        )

    def registration_replay(self):
        email, key = self.email("replay"), self.key()
        first = self.status(self.register(email, key), 201)
        assert (
            self.status(self.register(email.upper(), key), 201).json() == first.json()
        )
        self.status(self.register(email, key, self.password + "other"), 409)
        self.status(self.register(self.email("conflict"), key), 409)
        self.status(self.register(email, self.key()), 409)
        self.check_user(first.json()["userId"])

    def registration_race(self, same_key):
        email, key = self.email("same-key" if same_key else "same-email"), self.key()
        futures = [
            self.executor.submit(
                self.register,
                email,
                key if same_key else (key if i == 0 else self.key()),
            )
            for i in range(8)
        ]
        replies = [future.result() for future in futures]
        for response in replies:
            self.status(response, *((201, 202) if same_key else (201, 202, 409)))
        successes = [
            response for response in replies if response.status_code in {201, 202}
        ]
        assert len({r.json()["userId"] for r in successes}) == 1
        if not same_key:
            assert len(successes) == 1
        op = self.eventually(
            lambda: (
                o
                if (o := self.operation(email)) and o["status"] == "COMPLETED"
                else None
            ),
            "race completes",
        )
        self.check_user(op["user_id"])

    def invalid_login(self):
        before = self.sql("identity-postgres", "SELECT count(*) FROM auth_sessions;")
        for email, password in [
            (self.main_email, "incorrect-password"),
            (self.email("absent"), self.password),
        ]:
            self.status(
                self.request(
                    "POST",
                    "/api/v1/auth/login",
                    json={"email": email, "password": password},
                ),
                401,
            )
        assert before == self.sql(
            "identity-postgres", "SELECT count(*) FROM auth_sessions;"
        )
        self.status(self.request("GET", "/api/v1/auth/me"), 401)
        self.status(
            self.request(
                "POST",
                "/api/v1/auth/login/test",
                json={"email": self.main_email, "password": self.password},
            ),
            404,
        )

    def token_validation(self):
        claims = jwt.decode(
            self.main_cookies["access_token"], options={"verify_signature": False}
        )
        private = (self.directory / "private.pem").read_bytes()
        for changed, kid in [
            ({"exp": 1}, "identity-v1"),
            ({"aud": "wrong-audience"}, "identity-v1"),
            ({"iss": "wrong-issuer"}, "identity-v1"),
            ({}, "unknown-key"),
        ]:
            token = jwt.encode(
                {**claims, **changed}, private, algorithm="RS256", headers={"kid": kid}
            )
            for path in ("/api/v1/auth/me", "/api/v1/profiles/me"):
                self.status(
                    self.request("GET", path, cookies={"access_token": token}), 401
                )
        for path in ("/api/v1/auth/me", "/api/v1/profiles/me"):
            self.status(
                self.request("GET", path, cookies={"access_token": "malformed-token"}),
                401,
            )
        self.status(
            self.request(
                "GET",
                "/api/v1/auth/me",
                headers={
                    "Authorization": "Bearer " + self.main_cookies["access_token"]
                },
            ),
            401,
        )

    def rotation_replay(self):
        email, user = self.new_user("rotation")
        original, key = self.login(email), self.key()
        first = self.status(self.refresh(original, key), 204)
        replacement = dict(first.cookies)
        assert original["refresh_token"] != replacement["refresh_token"]
        assert (
            dict(self.status(self.refresh(original, key), 204).cookies) == replacement
        )
        self.status(self.refresh(replacement, key), 409)
        next_pair = dict(self.status(self.refresh(replacement), 204).cookies)
        self.status(self.refresh(original, key), 401)
        self.status(self.refresh(original), 401)
        self.status(self.refresh(next_pair), 401)
        session = self.sessions(user)[0]
        assert session["tokens"] == 3 and session["revoked_at"] is not None

    def refresh_race(self, same_key):
        email, user = self.new_user("refresh-same" if same_key else "refresh-different")
        original, key = self.login(email), self.key()
        replies = list(
            self.executor.map(
                lambda i: self.refresh(original, key if same_key else self.key()),
                range(8),
            )
        )
        for response in replies:
            self.status(response, *((204, 423) if same_key else (204, 401)))
        session = self.sessions(user)[0]
        assert session["tokens"] == 2 and session["unused"] == 1
        if same_key:
            winner = dict(self.status(self.refresh(original, key), 204).cookies)
            assert all(
                dict(r.cookies) == winner for r in replies if r.status_code == 204
            )
            assert session["revoked_at"] is None
        else:
            assert session["revoked_at"] is not None

    def logout(self):
        email, user = self.new_user("logout")
        cookies = self.login(email)
        for supplied in (cookies, cookies, {}, {"refresh_token": "unknown-refresh"}):
            response = self.status(
                self.request("POST", "/api/v1/auth/logout", cookies=supplied), 204
            )
            assert "Max-Age=0" in response.headers["set-cookie"]
        self.status(self.refresh(cookies), 401)
        assert self.sessions(user)[0]["revoked_at"] is not None

    def logout_race(self):
        email, user = self.new_user("logout-race")
        original = self.login(email)
        rotating = self.executor.submit(self.refresh, original)
        self.status(self.request("POST", "/api/v1/auth/logout", cookies=original), 204)
        rotated = self.status(rotating.result(), 204, 401)
        if rotated.status_code == 204:
            self.status(self.refresh(dict(rotated.cookies)), 401)
        assert self.sessions(user)[0]["revoked_at"] is not None

    def missing_refresh(self):
        self.status(self.refresh({}), 401)
        self.status(self.refresh({"refresh_token": "unknown"}), 401)
        self.status(
            self.request("POST", "/api/v1/auth/refresh", cookies=self.main_cookies), 422
        )

    def disabled_user(self):
        email, user = self.new_user("disabled")
        cookies = self.login(email)
        self.sql(
            "identity-postgres",
            f"UPDATE users SET status='DISABLED' WHERE id='{user}';",
        )
        try:
            self.status(
                self.request(
                    "POST",
                    "/api/v1/auth/login",
                    json={"email": email, "password": self.password},
                ),
                401,
            )
            self.status(self.request("GET", "/api/v1/auth/me", cookies=cookies), 401)
            self.status(self.refresh(cookies), 401)
            assert self.sessions(user)[0]["revoked_at"] is not None
        finally:
            self.sql(
                "identity-postgres",
                f"UPDATE users SET status='ACTIVE' WHERE id='{user}';",
            )

    def expired_session(self):
        email, user = self.new_user("expired")
        cookies = self.login(email)
        self.sql(
            "identity-postgres",
            f"UPDATE auth_sessions SET idle_expires_at=clock_timestamp()+interval '0.1 seconds' WHERE user_id='{user}';",
        )
        time.sleep(0.2)
        self.status(self.refresh(cookies), 401)
        assert self.sessions(user)[0]["tokens"] == 1

    def profile_contracts(self):
        response = self.status(
            self.request("GET", "/api/v1/profiles/me", cookies=self.main_cookies), 200
        )
        before = response.json()
        key = self.key()
        args = {
            "cookies": self.main_cookies,
            "json": {"display_name": "E2E User", "username": "e2e_" + self.prefix},
            "headers": {"If-Match": response.headers["etag"], "Idempotency-Key": key},
        }
        changed = self.status(self.request("PATCH", "/api/v1/profiles/me", **args), 200)
        replay = self.status(self.request("PATCH", "/api/v1/profiles/me", **args), 200)
        assert replay.json() == changed.json()
        assert changed.json()["version"] == before["version"] + 1
        args["headers"] = {**args["headers"], "Idempotency-Key": self.key()}
        self.status(self.request("PATCH", "/api/v1/profiles/me", **args), 409)

    def gateway_settings(self):
        self.status(
            self.request("GET", "/api/v1/settings/me", cookies=self.main_cookies), 200
        )

    def gateway_anonymous_profile(self):
        self.status(self.request("GET", f"/api/v1/profiles/{self.main_user}"), 200)

    def gateway_profile_search(self):
        username = self.rows(
            "profile-postgres",
            "SELECT username FROM profiles WHERE username IS NOT NULL LIMIT 1",
        )[0]["username"]
        params = {"username": username}
        self.status(
            self.request(
                "GET", "/api/v1/profiles", service="user-profile-service", params=params
            ),
            200,
        )
        response = self.request("GET", "/api/v1/profiles", params=params)
        if response.status_code == 301:
            redirected = self.request("GET", "/api/v1/profiles/", params=params)
            assert redirected.status_code != 307, (
                "Gateway redirects /profiles to /profiles/ (301), Profile redirects back (307)"
            )
        self.status(response, 200)

    def internal_boundary(self):
        path = f"/internal/v1/profiles/{self.main_user}"
        self.status(self.request("HEAD", path), 404)
        operation = self.operation(self.main_email)
        body = {"registered_at": operation["created_at"]}
        self.status(
            self.request("PUT", path, service="user-profile-service", json=body), 401
        )
        before = self.sql(
            "profile-postgres", "SELECT count(*) FROM idempotency_records;"
        )
        for _ in range(2):
            self.status(
                self.request(
                    "PUT",
                    path,
                    service="user-profile-service",
                    json=body,
                    headers={"X-Service-Token": self.manifest["service_token"]},
                ),
                204,
            )
        assert before == self.sql(
            "profile-postgres", "SELECT count(*) FROM idempotency_records;"
        )
        self.check_user(self.main_user)

    def outage_registration(self, dependency, label):
        email, key = self.email(label), self.key()
        with (
            self.stopped("identity-registration-reconciler"),
            self.stopped(dependency),
        ):
            response = self.status(self.register(email, key), 202)
            assert int(response.headers["retry-after"]) > 0
            operation = self.operation(email)
            assert operation["status"] == "PENDING"
            assert (
                self.sql(
                    "identity-postgres",
                    f"SELECT count(*) FROM users WHERE id='{operation['user_id']}';",
                )
                == "0"
            )
            assert (
                self.sql(
                    "identity-postgres",
                    f"SELECT count(*) FROM outbox WHERE key='{operation['user_id']}';",
                )
                == "0"
            )
            self.status(
                self.request(
                    "POST",
                    "/api/v1/auth/login",
                    json={"email": email, "password": self.password},
                ),
                401,
            )
        self.complete(email, key)

    def identity_database_outage(self):
        email, key = self.email("identity-db"), self.key()
        with self.stopped(
            "identity-registration-reconciler", "identity-relay", "identity-postgres"
        ):
            self.status(self.register(email, key), 500, 503)
            self.status(
                self.request(
                    "POST",
                    "/api/v1/auth/login",
                    json={"email": self.main_email, "password": self.password},
                ),
                500,
                503,
            )
        self.wait_ready("identity-service")
        self.status(self.register(email, key), 201, 202)
        self.complete(email, key)

    def valkey_outage(self):
        email, user = self.new_user("valkey")
        original, key = self.login(email), self.key()
        with self.stopped("valkey"):
            first = self.status(self.refresh(original, key), 204)
            assert dict(self.status(self.refresh(original, key), 204).cookies) == dict(
                first.cookies
            )
            self.new_user("valkey-register")
        assert dict(self.status(self.refresh(original, key), 204).cookies) == dict(
            first.cookies
        )
        assert self.sessions(user)[0]["tokens"] == 2

    def cache_loss(self):
        email, user = self.new_user("cache-loss")
        cookies, key = self.login(email), self.key()
        first = self.status(self.refresh(cookies, key), 204)
        self.dc("exec", "-T", "valkey", "valkey-cli", "FLUSHALL")
        assert dict(self.status(self.refresh(cookies, key), 204).cookies) == dict(
            first.cookies
        )
        self.check_user(user)

    def blocked_redrive(self):
        email, key = self.email("blocked"), self.key()
        self.proxy("wrong_service_token")
        try:
            self.status(self.register(email, key), 503)
            operation = self.operation(email)
            assert operation["status"] == "BLOCKED"
            assert (
                self.sql(
                    "profile-postgres",
                    f"SELECT count(*) FROM profiles WHERE user_id='{operation['user_id']}';",
                )
                == "0"
            )
            self.status(self.register(email, key), 503)
        finally:
            self.proxy("forward")
        self.dc(
            "exec",
            "-T",
            "identity-service",
            "python",
            "-m",
            "app.entrypoints.maintenance.registration_reconciler",
            "--redrive",
            operation["id"],
        )
        self.complete(email, key)
        assert self.operation(email)["redrive_count"] == 1

    def crash_after_profile(self):
        email, key = self.email("crash"), self.key()
        with self.stopped("identity-registration-reconciler"):
            self.proxy("hold_after_commit")
            pending = self.executor.submit(self.register, email, key)
            try:
                self.eventually(
                    lambda: (
                        self.request("GET", "/control", service="profile-proxy").json()[
                            "completed"
                        ]
                        > 0
                    ),
                    "Profile commit reached",
                )
                operation = self.operation(email)
                assert (
                    self.sql(
                        "profile-postgres",
                        f"SELECT count(*) FROM profiles WHERE user_id='{operation['user_id']}';",
                    )
                    == "1"
                )
                assert (
                    self.sql(
                        "identity-postgres",
                        f"SELECT count(*) FROM users WHERE id='{operation['user_id']}';",
                    )
                    == "0"
                )
                self.dc("kill", "-s", "SIGKILL", "identity-service")
            finally:
                self.proxy("forward")
                self.dc("start", "identity-service")
                self.wait_ready("identity-service")
            try:
                pending.result()
            except httpx.TransportError:
                pass
        self.complete(email, key)
        assert self.operation(email)["scrubbed"]

    def lost_profile_response(self):
        email, key = self.email("lost-response"), self.key()
        with self.stopped("identity-registration-reconciler"):
            self.proxy("hold_after_commit")
            try:
                self.status(self.register(email, key), 202)
                operation = self.operation(email)
                assert operation["status"] == "PENDING"
                assert (
                    self.sql(
                        "profile-postgres",
                        f"SELECT count(*) FROM profiles WHERE user_id='{operation['user_id']}';",
                    )
                    == "1"
                )
            finally:
                self.proxy("forward")
        self.complete(email, key)

    def kafka_outage(self):
        with self.stopped("kafka"):
            _email, user = self.new_user("kafka")
            self.eventually(
                lambda: (
                    self.sql(
                        "identity-postgres",
                        f"SELECT status FROM outbox WHERE key='{user}';",
                    )
                    == "CLAIMED"
                ),
                "relay claims unavailable-broker event",
            )
            assert (
                self.sql(
                    "identity-postgres",
                    f"SELECT status FROM outbox WHERE key='{user}';",
                )
                != "SUCCESS"
            )
        self.eventually(
            lambda: (
                self.sql(
                    "identity-postgres",
                    f"SELECT status FROM outbox WHERE key='{user}';",
                )
                == "SUCCESS"
            ),
            "Kafka recovery",
            timeout=90,
        )
        self.check_user(user)

    def relay_crash(self):
        with self.stopped("kafka"):
            _email, user = self.new_user("relay-crash")
            self.eventually(
                lambda: (
                    self.sql(
                        "identity-postgres",
                        f"SELECT status FROM outbox WHERE key='{user}';",
                    )
                    == "CLAIMED"
                ),
                "relay claim before kill",
            )
            self.dc("kill", "-s", "SIGKILL", "identity-relay")
        self.dc("start", "identity-relay")
        self.eventually(
            lambda: (
                self.sql(
                    "identity-postgres",
                    f"SELECT status FROM outbox WHERE key='{user}';",
                )
                == "SUCCESS"
            ),
            "relay claim recovered",
            timeout=90,
        )

    def restart_replay(self):
        email, user = self.new_user("restart")
        original, key = self.login(email), self.key()
        first = self.status(self.refresh(original, key), 204)
        self.dc("restart", "identity-service", "user-profile-service")
        self.wait_ready("identity-service")
        self.wait_ready("user-profile-service")
        assert dict(self.status(self.refresh(original, key), 204).cookies) == dict(
            first.cookies
        )
        self.check_user(user)

    def profile_settings_direct(self):
        headers = {"Authorization": "Bearer " + self.main_cookies["access_token"]}
        response = self.status(
            self.request(
                "GET",
                "/api/v1/settings/me",
                service="user-profile-service",
                headers=headers,
            ),
            200,
        )
        updated = self.status(
            self.request(
                "PATCH",
                "/api/v1/settings/me",
                service="user-profile-service",
                headers={
                    **headers,
                    "If-Match": response.headers["etag"],
                    "Idempotency-Key": self.key(),
                },
                json={"theme": "dark"},
            ),
            200,
        )
        assert updated.json()["theme"] == "dark"
        self.status(
            self.request(
                "GET",
                f"/api/v1/profiles/{self.main_user}",
                service="user-profile-service",
            ),
            200,
        )

    def multiple_reconcilers(self):
        with (
            self.stopped("identity-registration-reconciler"),
            self.stopped("user-profile-service"),
        ):
            inputs = [(self.email(f"batch-{i}"), self.key()) for i in range(6)]
            for email, key in inputs:
                self.status(self.register(email, key), 202)
        try:
            self.dc(
                "up",
                "-d",
                "--scale",
                "identity-registration-reconciler=2",
                "identity-registration-reconciler",
            )
            for email, key in inputs:
                self.complete(email, key)
        finally:
            self.dc(
                "up",
                "-d",
                "--scale",
                "identity-registration-reconciler=1",
                "identity-registration-reconciler",
            )

    def reconciler_crash(self):
        email, key = self.email("reconciler-crash"), self.key()
        with self.stopped("identity-registration-reconciler"):
            with self.stopped("user-profile-service"):
                self.status(self.register(email, key), 202)
            self.proxy("hold_after_commit")
        try:
            self.eventually(
                lambda: (
                    self.request("GET", "/control", service="profile-proxy").json()[
                        "completed"
                    ]
                    > 0
                ),
                "reconciler reached Profile commit",
            )
            operation = self.operation(email)
            assert operation["status"] == "CLAIMED"
            assert (
                self.sql(
                    "identity-postgres",
                    f"SELECT count(*) FROM users WHERE id='{operation['user_id']}';",
                )
                == "0"
            )
            self.dc("kill", "-s", "SIGKILL", "identity-registration-reconciler")
        finally:
            self.proxy("forward")
            self.dc("start", "identity-registration-reconciler")
        self.complete(email, key)

    def retry_exhaustion(self):
        email, key = self.email("retry-limit"), self.key()
        with (
            self.stopped("identity-registration-reconciler"),
            self.stopped("user-profile-service"),
        ):
            self.status(self.register(email, key), 202)
            worker = self.dc(
                "run",
                "--rm",
                "-d",
                "--no-deps",
                "-e",
                "REGISTRATION_RETRY_MAX_ATTEMPTS=2",
                "identity-registration-reconciler",
            ).strip()
            try:
                operation = self.eventually(
                    lambda: (
                        op
                        if (op := self.operation(email)) and op["status"] == "BLOCKED"
                        else None
                    ),
                    "registration retry limit reached",
                )
                assert operation["attempts"] == 2
                assert (
                    self.sql(
                        "identity-postgres",
                        f"SELECT count(*) FROM users WHERE id='{operation['user_id']}';",
                    )
                    == "0"
                )
            finally:
                subprocess.run(
                    ["docker", "stop", "-t", "2", worker],
                    check=True,
                    capture_output=True,
                )
        self.status(self.register(email, key), 503)
        self.dc(
            "exec",
            "-T",
            "identity-service",
            "python",
            "-m",
            "app.entrypoints.maintenance.registration_reconciler",
            "--redrive",
            operation["id"],
        )
        self.complete(email, key)
        assert self.operation(email)["redrive_count"] == 1

    def replay_key_unavailable(self):
        import base64
        import secrets

        email, user = self.new_user("key-unavailable")
        original, key = self.login(email), self.key()
        first = self.status(self.refresh(original, key), 204)
        key_path = self.directory / "replay.key"
        previous = key_path.read_bytes()
        try:
            key_path.write_bytes(base64.b64encode(secrets.token_bytes(32)))
            self.dc("restart", "identity-service")
            self.wait_ready("identity-service")
            self.status(self.refresh(original, key), 503)
            assert self.sessions(user)[0]["tokens"] == 2
        finally:
            key_path.write_bytes(previous)
            self.dc("restart", "identity-service")
            self.wait_ready("identity-service")
        assert dict(self.status(self.refresh(original, key), 204).cookies) == dict(
            first.cookies
        )

    def relay_crash_after_publish(self):
        # Block the SUCCESS update after Kafka acknowledges the event, then kill the relay.
        with self.stopped("identity-relay"):
            _email, user = self.new_user("publish-before-commit")
            self.sql(
                "identity-postgres",
                f"""
                CREATE FUNCTION e2e_hold_outbox_success() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    IF NEW.key = '{user}' AND NEW.status = 'SUCCESS' THEN
                        PERFORM pg_advisory_xact_lock(19716001);
                    END IF;
                    RETURN NEW;
                END $$;
                CREATE TRIGGER e2e_hold_outbox_success BEFORE UPDATE ON outbox
                FOR EACH ROW EXECUTE FUNCTION e2e_hold_outbox_success();
            """,
            )
            holder = self.executor.submit(
                self.sql,
                "identity-postgres",
                "SET application_name='e2e-outbox-holder'; BEGIN; SELECT pg_advisory_xact_lock(19716001); SELECT pg_sleep(80); COMMIT;",
            )
            self.eventually(
                lambda: (
                    self.sql(
                        "identity-postgres",
                        "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=19716001 AND granted;",
                    )
                    == "1"
                ),
                "test transaction holds advisory lock",
            )
        try:
            self.eventually(
                lambda: (
                    self.sql(
                        "identity-postgres",
                        "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND objid=19716001 AND NOT granted;",
                    )
                    == "1"
                ),
                "relay waits after successful publish",
            )
            event_id = self.sql(
                "identity-postgres", f"SELECT id FROM outbox WHERE key='{user}';"
            )
            events = self.kafka_events()
            assert any(event["headers"]["event_id"] == event_id for event in events)
            assert (
                self.sql(
                    "identity-postgres",
                    f"SELECT status FROM outbox WHERE key='{user}';",
                )
                == "CLAIMED"
            )
            self.dc("kill", "-s", "SIGKILL", "identity-relay")
        finally:
            self.sql(
                "identity-postgres",
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE application_name='e2e-outbox-holder';",
            )
            try:
                holder.result()
            except RuntimeError:
                pass
            self.sql(
                "identity-postgres",
                "DROP TRIGGER e2e_hold_outbox_success ON outbox; DROP FUNCTION e2e_hold_outbox_success();",
            )
            self.dc("start", "identity-relay")
        self.eventually(
            lambda: (
                self.sql(
                    "identity-postgres",
                    f"SELECT status FROM outbox WHERE key='{user}';",
                )
                == "SUCCESS"
            ),
            "redelivery completes",
        )
        events = [
            event
            for event in self.kafka_events()
            if event["headers"]["event_id"] == event_id
        ]
        assert len(events) >= 2, "Expected redelivery of the same event ID"
        assert all(event["value"] == events[0]["value"] for event in events)
        self.check_user(user)

    def kafka_events(self):
        script = """import asyncio, json
from aiokafka import AIOKafkaConsumer
async def main():
    consumer = AIOKafkaConsumer("identity.events.v1", bootstrap_servers="kafka:29092", auto_offset_reset="earliest", enable_auto_commit=False)
    await consumer.start()
    result = []
    try:
        for _ in range(5):
            batches = await consumer.getmany(timeout_ms=1000)
            for messages in batches.values():
                for m in messages:
                    result.append({"key": m.key.decode(), "value": json.loads(m.value), "headers": {k: v.decode() for k,v in m.headers}})
            if result and not batches: break
    finally: await consumer.stop()
    print(json.dumps(result))
asyncio.run(main())
"""
        return json.loads(
            self.dc("exec", "-T", "identity-service", "python", "-", input=script)
        )

    def final_consistency(self):
        self.eventually(
            lambda: (
                self.sql(
                    "identity-postgres",
                    "SELECT count(*) FROM registration_operations WHERE status <> 'COMPLETED';",
                )
                == "0"
            ),
            "all registrations settle",
            timeout=60,
        )
        self.eventually(
            lambda: (
                self.sql(
                    "identity-postgres",
                    "SELECT count(*) FROM outbox WHERE status <> 'SUCCESS';",
                )
                == "0"
            ),
            "outbox drains",
            timeout=90,
        )
        users = self.rows(
            "identity-postgres", "SELECT id, email, created_at FROM users"
        )
        profiles = self.rows(
            "profile-postgres", "SELECT user_id, created_at FROM profiles"
        )
        settings = self.rows(
            "profile-postgres", "SELECT user_id, created_at FROM user_settings"
        )
        registrations = self.rows(
            "identity-postgres",
            "SELECT id, user_id, status, claim_token, claim_expires_at, password_hash IS NULL AS scrubbed FROM registration_operations",
        )
        outbox = self.rows(
            "identity-postgres",
            "SELECT id, key, topic, payload, status, claim_token, claim_expires_at FROM outbox",
        )
        users_by_id = {u["id"]: u for u in users}
        ids = set(users_by_id)
        assert (
            ids
            == {p["user_id"] for p in profiles}
            == {s["user_id"] for s in settings}
            == {r["user_id"] for r in registrations}
            == {e["key"] for e in outbox}
        ), "Cross-service ID sets differ"
        assert (
            len(users)
            == len(profiles)
            == len(settings)
            == len(registrations)
            == len(outbox)
        )
        assert all(
            r["scrubbed"] and r["claim_token"] is None and r["claim_expires_at"] is None
            for r in registrations
        )
        assert all(
            e["claim_token"] is None and e["claim_expires_at"] is None for e in outbox
        )
        for profile in profiles + settings:
            assert datetime.fromisoformat(
                profile["created_at"]
            ) == datetime.fromisoformat(users_by_id[profile["user_id"]]["created_at"])
        assert (
            self.sql(
                "identity-postgres",
                "SELECT count(*) FROM auth_sessions s LEFT JOIN users u ON u.id=s.user_id WHERE u.id IS NULL;",
            )
            == "0"
        )
        assert (
            self.sql(
                "identity-postgres",
                "SELECT count(*) FROM refresh_tokens t LEFT JOIN auth_sessions s ON s.id=t.session_id WHERE s.id IS NULL;",
            )
            == "0"
        )
        assert (
            self.sql(
                "identity-postgres",
                "SELECT count(*) FROM (SELECT s.id FROM auth_sessions s JOIN refresh_tokens t ON t.session_id=s.id WHERE s.revoked_at IS NULL AND s.idle_expires_at>now() GROUP BY s.id HAVING count(*) FILTER (WHERE t.used_at IS NULL)<>1) invalid;",
            )
            == "0"
        )
        records = self.rows(
            "identity-postgres",
            "SELECT result_type, result_payload, resource_id FROM idempotency_records",
        )
        serialized = json.dumps(records)
        assert not any(
            secret in serialized for secret in self.secrets if len(secret) > 10
        ), "Raw credential in replay storage"
        events = self.kafka_events()
        by_id = {e["id"]: e for e in outbox}
        assert {e["headers"]["event_id"] for e in events} == set(by_id), (
            "Kafka event IDs differ from Outbox"
        )
        for event in events:
            row = by_id[event["headers"]["event_id"]]
            assert row["key"] == event["key"] and row["payload"] == event["value"], (
                "Kafka payload differs"
            )
        snapshot = {
            "users": users,
            "profiles": profiles,
            "settings": settings,
            "registrations": registrations,
            "outbox": outbox,
            "kafka_events": events,
            "sessions": self.rows(
                "identity-postgres",
                "SELECT id, user_id, revoked_at, idle_expires_at FROM auth_sessions",
            ),
            "replay_records": len(records),
            "kafka_duplicate_deliveries": len(events) - len(by_id),
        }
        (self.directory / "consistency.json").write_text(
            json.dumps(snapshot, indent=2), encoding="utf-8"
        )
        print(
            f"CONSISTENT users={len(users)} profiles={len(profiles)} settings={len(settings)} outbox={len(outbox)} kafka={len(events)}",
            flush=True,
        )

    def log_safety(self):
        for service in (
            "identity-service",
            "identity-relay",
            "identity-registration-reconciler",
            "user-profile-service",
            "api-gateway",
        ):
            logs = self.dc("logs", "--no-color", service)
            leaked = [secret for secret in self.secrets if secret in logs]
            assert not leaked, (
                f"Credential canary found in {service} logs ({len(leaked)})"
            )
        print("Credential canaries absent from application logs", flush=True)

    def run(self, only=None):
        cases = [
            ("registration_login_profile", self.normal_registration),
            ("invalid_registration_has_no_effects", self.registration_validation),
            ("registration_replay_and_conflict", self.registration_replay),
            ("concurrent_registration_same_key", lambda: self.registration_race(True)),
            (
                "concurrent_registration_same_email",
                lambda: self.registration_race(False),
            ),
            ("invalid_login_and_disabled_test_endpoint", self.invalid_login),
            ("jwt_validation_and_gateway_header_boundary", self.token_validation),
            ("refresh_rotation_replay_and_reuse", self.rotation_replay),
            ("concurrent_refresh_same_key", lambda: self.refresh_race(True)),
            ("concurrent_refresh_different_keys", lambda: self.refresh_race(False)),
            ("logout_idempotency_and_revocation", self.logout),
            ("concurrent_logout_refresh", self.logout_race),
            ("invalid_refresh_inputs", self.missing_refresh),
            ("disabled_user_rejected", self.disabled_user),
            ("expired_session_rejected", self.expired_session),
            ("profile_update_replay_and_version_conflict", self.profile_contracts),
            ("gateway_settings_route", self.gateway_settings),
            ("gateway_anonymous_public_profile", self.gateway_anonymous_profile),
            ("gateway_profile_search_route", self.gateway_profile_search),
            ("internal_provisioning_auth_and_replay", self.internal_boundary),
            (
                "profile_process_outage_recovery",
                lambda: self.outage_registration(
                    "user-profile-service", "profile-down"
                ),
            ),
            (
                "profile_database_outage_recovery",
                lambda: self.outage_registration("profile-postgres", "profile-db-down"),
            ),
            ("identity_database_outage_recovery", self.identity_database_outage),
            ("valkey_outage_durable_fallback", self.valkey_outage),
            ("cache_loss_replays_durable_result", self.cache_loss),
            ("permanent_profile_auth_failure_redrive", self.blocked_redrive),
            ("identity_crash_after_profile_commit", self.crash_after_profile),
            ("lost_profile_response_recovery", self.lost_profile_response),
            ("kafka_outage_recovery", self.kafka_outage),
            ("relay_crash_claim_recovery", self.relay_crash),
            ("service_restart_preserves_replay", self.restart_replay),
            ("profile_settings_and_public_read_direct", self.profile_settings_direct),
            ("two_reconcilers_drain_pending_registrations", self.multiple_reconcilers),
            ("reconciler_crash_after_profile_commit", self.reconciler_crash),
            ("replay_key_unavailable_then_restored", self.replay_key_unavailable),
            ("registration_retry_exhaustion_and_redrive", self.retry_exhaustion),
            ("relay_crash_after_publish_before_commit", self.relay_crash_after_publish),
            ("global_consistency_and_kafka_delivery", self.final_consistency),
            ("credential_canaries_absent_from_logs", self.log_safety),
        ]
        if only:
            unknown = set(only) - {name for name, _ in cases}
            if unknown:
                raise ValueError(f"Unknown scenarios: {sorted(unknown)}")
            cases = [(name, action) for name, action in cases if name in only]
        for name, action in cases:
            self.case(name, action)
        self.executor.shutdown()
        self.save()
        failures = sum(result["status"] == "FAIL" for result in self.results)
        print(
            f"TOTAL {len(self.results) - failures} passed, {failures} failed",
            flush=True,
        )
        return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--only", nargs="+")
    args = parser.parse_args()
    raise SystemExit(Suite(args.directory).run(args.only))
