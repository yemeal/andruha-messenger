# 02. Identity outbox и User Profile Service

## Итог этапа

Регистрация синхронно создаёт профиль и настройки. Identity возвращает `201`
только после подтверждения User Profile и собственного commit. Доступность
Profile теперь необходима для регистрации; доступность Kafka по-прежнему нет.

```text
Identity Tx A -> INSERT durable RegistrationOperation + claim -> COMMIT
  -> PUT User Profile /internal/v1/profiles/{user_id} (outside SQL transaction)
     -> Profile CommandBus -> COMMIT profile + settings + completion -> 204
  -> Identity Tx B -> INSERT user + outbox + COMPLETE operation -> COMMIT -> 201
  -> relay -> Kafka (notification for other consumers)
```

Решение от 2026-09-11 заменяет асинхронное provisioning и lazy repair.
Описание ниже сохраняет outbox/relay как механизм уведомления. SQL и примеры
из первоначального плана иллюстративны; текущие migrations и application-порты
в сервисах являются источником истины.

## 1. Синхронный контракт регистрации

Identity вызывает application-порт `ProfileProvisionerProtocol`; HTTP-адаптер
находится в infrastructure, настройки — в `core/settings`, сборка — в Dishka.

```text
PUT /internal/v1/profiles/{user_id}
X-Service-Token: <shared secret>
{"registered_at": "2026-09-11T10:15:30.120Z"}
```

Только `204` подтверждает создание профиля и настроек. При сетевом или временном
отказе Identity повторяет запрос один раз с теми же UUID и timestamp. Если обе
попытки не подтверждены, Identity возвращает `202` с `Retry-After`: операция
сохранена, но зарегистрированного `User` ещё нет. Повтор выполняется с тем же
`Idempotency-Key`; recovery worker также подберёт операцию после `available_at`.

Вызов защищён отдельным application-scoped circuit breaker. Transport errors и
retryable `5xx` учитываются как сбой зависимости; постоянные `4xx`, включая
`409`, не открывают circuit и не повторяются. Для `423`/`429` учитывается
`Retry-After`, ограниченный `PROFILE_SERVICE_RETRY_MAX_DELAY_SECONDS`. После
порога `PROFILE_SERVICE_CB_FAILURES` новые регистрации завершаются fail-fast;
после `PROFILE_SERVICE_CB_RECOVERY_SECONDS` допускается один HALF_OPEN probe.

Это две короткие локальные транзакции с сетевым вызовом между ними. Потерянный
ответ Profile или ошибка второй Identity-транзакции может временно оставить профиль
без аккаунта, но durable operation сохраняет `user_id`, timestamp и credential data,
необходимые для идемпотентного завершения. Recovery использует `FOR UPDATE SKIP LOCKED`,
lease и fencing token. После исчерпания retry либо постоянного отказа операция
переходит в `BLOCKED` и требует явного redrive. Повтор после потерянного `201` с тем
же ключом возвращает сохранённый успешный результат.

Гарантия относится к новым успешным регистрациям на момент ответа. Старым
аккаунтам без профилей требуется отдельный backfill. Удаление данных вручную
или независимое восстановление БД не исправляется через пользовательский GET.

## 2. Контракт `identity.user_registered.v1`

Для v1 payload должен быть минимальным:

```json
{
  "eventId": "019c...",
  "eventType": "identity.user_registered.v1",
  "schemaVersion": 1,
  "occurredAt": "2026-08-17T10:15:30.123Z",
  "producer": "andruha-identity-service",
  "correlationId": "019c...",
  "causationId": "019c...",
  "payload": {
    "userId": "019c...",
    "registeredAt": "2026-08-17T10:15:30.120Z"
  }
}
```

Email, password hash, role, account status и token в event запрещены. Profile
не должен получать credentials.

Начальная locale в v1 устанавливается настройкой Profile Service. Если продукт
позже должен выбирать locale прямо при регистрации, это отдельное совместимое
расширение contract и registration request. Identity не должен сохранять
locale как credential field.

Kafka topic: `identity.events.v1`; key: wire-поле `userId`.

## 3. Identity outbox model

Добавь в существующую greenfield migration новую таблицу, пока данные не
развёрнуты production. Если migration уже применена в разделяемом окружении,
создай новую revision вместо переписывания baseline.

Рекомендуемая PostgreSQL schema:

```sql
CREATE TABLE outbox_messages (
    id uuid PRIMARY KEY,
    topic varchar(200) NOT NULL,
    message_key varchar(200) NOT NULL,
    event_type varchar(200) NOT NULL,
    payload jsonb NOT NULL,
    status varchar(20) NOT NULL,
    attempts integer NOT NULL DEFAULT 0,
    available_at timestamptz NOT NULL,
    locked_by varchar(200),
    locked_until timestamptz,
    last_error_code varchar(100),
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    published_at timestamptz,
    CONSTRAINT ck_outbox_status
        CHECK (status IN ('PENDING', 'PROCESSING', 'RETRY', 'SUCCESS', 'QUARANTINED')),
    CONSTRAINT ck_outbox_attempts CHECK (attempts >= 0),
    CONSTRAINT ck_outbox_lock_pair CHECK (
        (locked_by IS NULL) = (locked_until IS NULL)
    )
);

CREATE INDEX ix_outbox_due
    ON outbox_messages (available_at, created_at)
    WHERE status IN ('PENDING', 'RETRY');

CREATE INDEX ix_outbox_expired_processing
    ON outbox_messages (locked_until)
    WHERE status = 'PROCESSING';
```

`payload` хранит готовый versioned envelope. Relay не должен заново собирать
business event и менять `event_id`/`occurred_at` при retry.

## 4. Durable registration process

Регистрация вынесена из `AuthService` в отдельный application use case.
`RegistrationOperation` является process manager, а не доменным `User`.
Hash password остаётся вне transaction и очищается из operation после completion.

```python
password_hash = await password_hasher.hash(password)

async with transaction_a:
    operation = await registrations.try_create_claimed(
        user_id=uuid7(),
        email=normalized_email,
        password_hash=password_hash,
        key_hash=sha256(idempotency_key),
    )

await profile_provisioner.create_profile(
    operation.user_id,
    operation.created_at,
)

async with transaction_b:
    await registrations.complete(operation.id, owner_token=claim_token)
    user = await users.create_if_absent(operation.to_user())
    await events.publish(UserRegisteredEvent.from_user(user))
```

Проверяемый invariant: не существует committed user, созданного новым кодом,
без подтверждённого Profile и соответствующей outbox row. Временный Profile без
User имеет durable operation и автоматически завершается после восстановления.

Тест commit failure должен доказать отсутствие обеих строк.

## 5. Outbox relay

Relay — отдельная process role того же Identity repository:

```text
app.entrypoints.messaging.relay:main
```

Не запускай бесконечный background task внутри каждого HTTP worker: несколько
Uvicorn workers создадут неочевидное количество relays и смешают readiness.

### Claim transaction

```sql
WITH due AS (
    SELECT id
    FROM outbox_messages
    WHERE (
        status IN ('PENDING', 'RETRY')
        AND available_at <= now()
    ) OR (
        status = 'PROCESSING'
        AND locked_until < now()
    )
    ORDER BY available_at, created_at
    FOR UPDATE SKIP LOCKED
    LIMIT :batch_size
)
UPDATE outbox_messages AS o
SET status = 'PROCESSING',
    locked_by = :worker_id,
    locked_until = now() + :lease,
    attempts = attempts + 1,
    updated_at = now()
FROM due
WHERE o.id = due.id
RETURNING o.*;
```

Claim transaction должна завершиться до Kafka publish.

### Publish и finalize

Псевдокод:

```python
async def run_once(self) -> int:
    claimed = await self._repository.claim_due(
        worker_id=self._worker_id,
        limit=self._batch_size,
        lease=self._lease,
    )
    for message in claimed:
        try:
            await self._publisher.publish(
                topic=message.topic,
                key=message.message_key.encode(),
                value=message.payload_bytes(),
                headers=message.safe_headers(),
            )
        except TransientPublishError as error:
            await self._repository.schedule_retry(
                message.id,
                worker_id=self._worker_id,
                error_code=type(error).__name__,
            )
        except PermanentContractError as error:
            await self._repository.quarantine(
                message.id,
                worker_id=self._worker_id,
                error_code=type(error).__name__,
            )
        else:
            await self._repository.mark_success(
                message.id,
                worker_id=self._worker_id,
            )
    return len(claimed)
```

Finalize update должен включать `WHERE locked_by=:worker_id AND
status='PROCESSING'`. Старый worker после lease expiry не должен завершить
запись, уже захваченную новым owner.

Backoff baseline:

```text
delay = min(60 seconds, 0.5 * 2^(attempt-1)) + random jitter 0..250 ms
```

После настроенного числа permanent failures запись становится `QUARANTINED`.
Kafka outage сам по себе не является permanent failure.

### Crash cases

| Момент crash | Recovery |
|---|---|
| До Tx A | Нет operation, user и event |
| После Tx A до Profile | Lease истекает, reconciler повторяет Profile PUT |
| После Profile 204 до Tx B | Reconciler повторяет идемпотентный PUT и завершает Tx B |
| После Tx B до HTTP 201 | Повтор с тем же Idempotency-Key возвращает `201` |
| После claim до publish | Lease истекает, другой relay повторяет |
| После Kafka ACK до SUCCESS | Event публикуется повторно |
| После SUCCESS | Больше не claim-ится |

## 6. Relay readiness и metrics

HTTP Identity readiness не зависит от Kafka или relay backlog. Registration
может безопасно писать outbox при недоступном broker.

Relay role:

- live: process/event loop жив;
- ready: PostgreSQL доступен и Kafka metadata/publish path доступен;
- при Kafka outage остаётся запущенным и retry-ит, но readiness `503`;
- metrics доступны только внутри Docker network.

Минимальные metrics:

- `identity_outbox_claimed_total{event_type}`;
- `identity_outbox_publish_total{outcome}`;
- `identity_outbox_backlog`;
- `identity_outbox_oldest_pending_seconds`;
- `identity_outbox_quarantined_total{event_type}`.

Нельзя добавлять event ID/user ID в labels.

## 7. Profile PostgreSQL model

```sql
CREATE TABLE profiles (
    user_id uuid PRIMARY KEY,
    display_name varchar(64) NOT NULL,
    bio varchar(500),
    locale varchar(35) NOT NULL,
    avatar_object_id uuid,
    version bigint NOT NULL DEFAULT 1,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT ck_profile_version CHECK (version > 0),
    CONSTRAINT ck_display_name_nonblank CHECK (length(trim(display_name)) > 0)
);

CREATE TABLE processed_events (
    consumer varchar(200) NOT NULL,
    event_id uuid NOT NULL,
    event_type varchar(200) NOT NULL,
    processed_at timestamptz NOT NULL,
    PRIMARY KEY (consumer, event_id)
);
```

Profile fields:

| Поле | Правило MVP |
|---|---|
| `display_name` | 1..64 Unicode code points после whitespace normalization |
| `bio` | `null` либо 0..500 code points; HTML не интерпретируется |
| `locale` | нормализованный BCP 47 tag, baseline `ru` |
| `avatar_object_id` | nullable UUID; проверяется через Object Storage на avatar этапе |
| `version` | увеличивается ровно на 1 при реальном изменении |

Не используй email как default display name: он раскрывает credential-side PII.
Безопасный default — `Пользователь` или локализуемый client placeholder.

## 8. Идемпотентное создание Profile через HTTP

Внутренний PUT вызывает существующий `CreateDefaultProfileCommand` через
CommandBus с `HOT_DURABLE` и `COMPLETION_ONLY`. Ключ — `user_id`, scope —
`identity:profile-provisioning`. Повтор должен содержать тот же `registered_at`.
Профиль, настройки и durable completion фиксируются одной транзакцией Profile.
`create_default_if_absent` сохраняет пользовательские изменения при повторах.
Новый Inbox и consumer для provisioning не нужны.

Отсутствующий/неверный `X-Service-Token` даёт `401`, ненастроенный
`INTERNAL_API_TOKEN` — `503`. Gateway не публикует `/internal`.

## 9. Чтение без восстановления

GET `/api/v1/profiles/me` и `/api/v1/settings` только читают данные.
Отсутствующие данные владельца возвращают `404`. `EnsureOwnProfile` и
`application/services` удалены. Подтверждённый completion не следует использовать
как способ повторного восстановления вручную удалённых записей.

## 10. Profile HTTP API

### `GET /api/v1/profiles/me`

Result `200`:

```json
{
  "user_id": "019c...",
  "display_name": "Алекс",
  "bio": null,
  "locale": "ru",
  "avatar_object_id": null,
  "version": 3
}
```

Headers:

```text
ETag: "3"
Cache-Control: private, no-cache
```

`no-cache` разрешает private browser cache с обязательной revalidation. Если
хочется проще, используй `no-store`, но не public cache.

### `PATCH /api/v1/profiles/me`

Request:

```http
If-Match: "3"
Content-Type: application/json

{
  "display_name": "Алекс",
  "bio": "Изучаю распределённые системы",
  "locale": "ru"
}
```

Правила:

- отсутствующий `If-Match` -> `428 profile.precondition_required`;
- malformed ETag -> `400 profile.invalid_version`;
- stale version -> `409 profile.version_conflict` с `current_version`;
- пустой patch -> `422`;
- credential fields -> `422` из-за `extra="forbid"`;
- реальное update -> `200`, новый ETag/version;
- повтор assignment тех же значений MAY вернуть существующую version без write.

SQL optimistic update:

```sql
UPDATE profiles
SET display_name = :display_name,
    bio = :bio,
    locale = :locale,
    version = version + 1,
    updated_at = :now
WHERE user_id = :user_id
  AND version = :expected_version
RETURNING *;
```

### `GET /api/v1/profiles/{user_id}`

Возвращает только public fields: `user_id`, display name, bio, locale, avatar
reference/version. Не возвращает email, role или account status.

### `POST /api/v1/profiles/batch`

Нужен клиенту для dialog list без N+1:

```json
{"user_ids": ["...", "..."]}
```

Baseline: максимум 100 уникальных IDs. Response сохраняет requested order либо
явно возвращает map. Missing private profile не раскрывает Identity state.

### Internal existence check

```text
HEAD /internal/v1/profiles/{user_id}
```

Используется только при создании dialog. Gateway этот path не публикует.
Локальная Docker network не является достаточной production authentication;
service-to-service authentication остаётся `TBD-002`.

## 11. Domain model

```python
@dataclass(slots=True)
class Profile:
    user_id: UUID
    display_name: DisplayName
    bio: Bio | None
    locale: Locale
    avatar_object_id: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime

    def apply_patch(
        self,
        *,
        display_name: str | None,
        bio: str | None,
        locale: str | None,
        now: datetime,
    ) -> bool:
        changed = False
        if display_name is not None:
            candidate = DisplayName(display_name)
            changed |= candidate != self.display_name
            self.display_name = candidate
        if bio is not None:
            candidate_bio = Bio.from_input(bio)
            changed |= candidate_bio != self.bio
            self.bio = candidate_bio
        if locale is not None:
            candidate_locale = Locale(locale)
            changed |= candidate_locale != self.locale
            self.locale = candidate_locale
        if changed:
            self.updated_at = now
        return changed
```

Не увеличивай version внутри entity до того, как optimistic update подтвердил
database winner, либо возвращай новый экземпляр после repository result.

## 12. DI и process roles

Profile обслуживает чтение и provisioning через HTTP:

```text
HTTP API:
  FastAPI -> query handlers / CommandBus -> PostgreSQL
```

Dishka собирает зависимости; каждый command dispatch получает собственный UoW.

Runtime dependencies добавляй только когда вводишь adapter:

- Pydantic/settings;
- Dishka;
- SQLAlchemy async + asyncpg;
- Alembic;
- PyJWT/cryptography для local access verification;
- Prometheus client;
- testcontainers PostgreSQL/Kafka для integration tests.

Не копируй `poetry.lock` из Identity. Добавь зависимости в Profile и создай его
собственный lock.

## 13. Compose changes

### Identity

Добавь Kafka settings и отдельный `identity-outbox-relay` service, используя тот
же image, но другую command/entrypoint. HTTP Identity не должен зависеть от
Kafka health.

### Profile

Добавь:

- `DATABASE_*` на `profile-postgres`;
- `INTERNAL_API_TOKEN` совпадает с Identity `PROFILE_SERVICE_TOKEN`;
- Identity public-key secret mount;
- service audience;
- `profile-service` depends on healthy PostgreSQL;
- migration execution без гонки нескольких replicas.

Для локального MVP один container может выполнить Alembic перед startup. Для
масштабирования migration становится отдельной deployment job.

## 14. Реализация по маленьким карточкам

### IDO-01 — Event contract

- добавить schema + fixtures;
- добавить producer/consumer model tests;
- обновить contract changelog.

### IDO-02 — Identity outbox persistence

- ORM/domain/port/repository;
- migration;
- user+event atomic registration;
- rollback/race tests.

### IDO-03 — Relay

- claim lease;
- publish outside transaction;
- success/retry/quarantine;
- internal health/metrics;
- crash-window integration tests.

### PROF-01 — Profile schema and default creation

- entity/value objects;
- PostgreSQL migration;
- repositories/UoW;
- внутренний PUT и существующий durable CommandBus.

### PROF-02 — Own profile HTTP

- JWT verifier;
- GET без побочных эффектов;
- PATCH optimistic concurrency;
- error/ETag contract.

### PROF-03 — Public/batch/internal reads

- privacy-safe public response;
- batch limit;
- internal HEAD;
- authorization/network tests.

## 15. Обязательные tests

### Identity

- duplicate email не создаёт outbox;
- register commit failure не создаёт user/outbox;
- successful register создаёт ровно одну event row;
- Kafka down не меняет `201` registration;
- два relay workers не публикуют одну claim одновременно;
- crash after ACK приводит к duplicate event с тем же `event_id`;
- expired lease забирается новым worker;
- raw email отсутствует в event/log/metric labels.

### Profile provisioning

- первый PUT атомарно создаёт профиль, настройки и completion;
- повторный/конкурентный PUT не дублирует данные;
- rollback не оставляет частично созданный профиль;
- повтор сохраняет пользовательские изменения;
- неверный service token не выполняет команду;
- отказ Profile не оставляет Identity user/outbox.

### Profile HTTP

- cookie через Gateway превращается в verified principal;
- caller payload не может подменить `user_id`;
- missing/invalid token -> 401;
- invalid fields -> 422;
- missing `If-Match` -> 428;
- stale version -> 409 и не меняет row;
- concurrent PATCH имеет одного winner;
- PostgreSQL down -> readiness 503 и safe error;
- public response не содержит credential fields.

### Сквозной acceptance

Given Identity, Profile и PostgreSQL запущены,
when новый пользователь регистрируется,
then registration возвращает `201`, и Profile API сразу возвращает профиль
и настройки с тем же `user_id`.

Given Kafka недоступна во время регистрации,
when пользователь успешно зарегистрирован,
then профиль уже существует, user и pending outbox остаются committed;
после восстановления Kafka relay публикует уведомление.

Given Profile недоступен во время регистрации,
then Identity возвращает `202`, user/outbox не фиксируются, login невозможен,
а durable operation повторяется reconciler-ом с backoff через тот же порт и circuit breaker.
