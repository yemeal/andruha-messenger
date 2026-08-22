# 03. Messages, Dialogues и Cassandra

## Итог этапа

Messages and Dialogues Service должен стать durable source of truth для:

- личных диалогов 1:1;
- membership;
- канонических сообщений;
- query projections списка и истории;
- delivery/read watermarks;
- sync events.

Сервис не держит WebSocket connections и не хранит media bytes.

## 1. Начинай с access patterns

Перед CQL запиши все запросы:

| ID | Запрос | Обязательный partition key |
|---|---|---|
| Q-01 | Найти dialog по канонической паре users | `pair_key` |
| Q-02 | Получить dialog/membership по `dialog_id` | `dialog_id` |
| Q-03 | Получить последние dialog activity пользователя | `(user_id, month_bucket)` |
| Q-04 | Проверить текущую позицию одного dialog в списке | `(user_id, pointer_shard)` + `dialog_id` |
| Q-05 | Получить историю dialog | `(dialog_id, month_bucket)` |
| Q-06 | Найти message для receipt/download | `message_id` |
| Q-07 | Найти idempotency result сообщения | `(sender_id, month_bucket)` + `client_message_id` |
| Q-08 | Получить receipt watermarks dialog | `dialog_id` |
| Q-09 | Получить sync events пользователя | `(user_id, day_bucket)` |

Если новый endpoint нельзя обслужить одной или несколькими заранее известными
partition reads, сначала добавь новую projection table. Не добавляй
`ALLOW FILTERING`.

## 2. Keyspace и consistency

Local Compose с одним узлом:

```sql
CREATE KEYSPACE IF NOT EXISTS andruha_messages
WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'datacenter1': 1
};
```

Production-like laboratory:

```sql
ALTER KEYSPACE andruha_messages
WITH replication = {
    'class': 'NetworkTopologyStrategy',
    'datacenter1': 3
};
```

Baseline:

| Среда | Regular read/write | LWT serial |
|---|---|---|
| Одноузловая local | `LOCAL_ONE` | `LOCAL_SERIAL` |
| RF=3 single-DC | `LOCAL_QUORUM` | `LOCAL_SERIAL` |

Нельзя заявлять quorum/HA по результатам одноузлового Compose.

## 3. Почему используем bucket

Partition с бесконечной историей dialog или user будет расти вечно и создаст
hotspot/repair/compaction проблемы. Поэтому:

- message history bucket — календарный месяц UTC;
- dialog activity bucket — календарный месяц UTC;
- message request bucket — месяц, извлечённый из server-received time;
- sync bucket — день UTC.

Bucket входит в opaque cursor. Переход между bucket выполняет application code.

Стартовый operational guardrail — наблюдать partitions, приближающиеся к
100 000 rows или 100 MiB, и менять bucket до достижения опасной величины. Это
не физический hard limit Cassandra, а ранний сигнал. Cassandra documentation
подчёркивает необходимость bounded «just right» partitions и риск hot
partitions: [CQL data definition](https://cassandra.apache.org/doc/latest/cassandra/developing/cql/ddl.html).

## 4. Идентификаторы и порядок

- публичные business IDs: UUIDv7;
- `client_message_id`: UUIDv7, создаётся client один раз;
- Cassandra ordering position: `timeuuid`, создаётся Messages Service;
- Kafka event ID: UUIDv5/детерминированный UUID от business identity + event
  type + target;
- timestamps: timezone-aware UTC.

`timeuuid` — техническая позиция, а не публичная identity message. Он хранится
в canonical snapshot, чтобы repair не создавал новый порядок.

## 5. CQL schema MVP

### Уникальная пара 1:1

```sql
CREATE TABLE dialog_by_pair (
    pair_key text PRIMARY KEY,
    dialog_id uuid,
    user_low uuid,
    user_high uuid,
    created_at timestamp
);
```

`pair_key = sha256(min(user_id) + ':' + max(user_id))` в lowercase hex.
Создание выполняется `INSERT ... IF NOT EXISTS`.

### Канонический dialog

```sql
CREATE TABLE dialog_by_id (
    dialog_id uuid PRIMARY KEY,
    user_a uuid,
    user_b uuid,
    created_at timestamp
);
```

Вместо Cassandra set храним два явных user fields: MVP допускает только 1:1,
и этот invariant проще проверить.

### Activity list

```sql
CREATE TABLE dialog_activity_by_user_bucket (
    user_id uuid,
    bucket_month date,
    activity_time timeuuid,
    dialog_id uuid,
    projection_version bigint,
    peer_user_id uuid,
    last_message_id uuid,
    last_message_preview text,
    last_message_sender_id uuid,
    last_message_at timestamp,
    PRIMARY KEY ((user_id, bucket_month), activity_time, dialog_id)
) WITH CLUSTERING ORDER BY (activity_time DESC, dialog_id DESC);
```

Clustering key нельзя «обновить». Новая activity создаёт новую строку. Текущую
строку определяет pointer:

```sql
CREATE TABLE dialog_position_by_user_shard (
    user_id uuid,
    pointer_shard tinyint,
    dialog_id uuid,
    bucket_month date,
    activity_time timeuuid,
    projection_version bigint,
    PRIMARY KEY ((user_id, pointer_shard), dialog_id)
);
```

`pointer_shard = stable_hash(dialog_id) % 16`. List query читает activity rows
с запасом, проверяет bounded набор pointers и отбрасывает старые duplicate
positions. Repair удаляет устаревшие rows. Так partial failure не ломает список.

### Message idempotency reservation

```sql
CREATE TABLE message_request_by_sender_bucket (
    sender_id uuid,
    bucket_month date,
    client_message_id uuid,
    payload_hash blob,
    message_id uuid,
    dialog_id uuid,
    message_time timeuuid,
    canonical_payload blob,
    created_at timestamp,
    PRIMARY KEY ((sender_id, bucket_month), client_message_id)
);
```

`canonical_payload` — versioned compact JSON/MessagePack snapshot с text,
validated attachment descriptors, recipient, timestamps, event IDs и sync
positions. Он не является произвольным pickle.

Reservation хранится столько же, сколько message, чтобы старый
`client_message_id` никогда не стал новой операцией.

### History projection

```sql
CREATE TABLE messages_by_dialog_bucket (
    dialog_id uuid,
    bucket_month date,
    message_time timeuuid,
    message_id uuid,
    sender_id uuid,
    recipient_id uuid,
    text text,
    attachment_snapshot blob,
    created_at timestamp,
    PRIMARY KEY ((dialog_id, bucket_month), message_time, message_id)
) WITH CLUSTERING ORDER BY (message_time DESC, message_id DESC);
```

### Lookup by message ID

```sql
CREATE TABLE message_by_id (
    message_id uuid PRIMARY KEY,
    dialog_id uuid,
    bucket_month date,
    message_time timeuuid,
    sender_id uuid,
    recipient_id uuid,
    text text,
    attachment_snapshot blob,
    created_at timestamp
);
```

### Receipt watermarks

```sql
CREATE TABLE receipt_watermark_by_dialog (
    dialog_id uuid,
    recipient_user_id uuid,
    delivered_through_time timeuuid,
    delivered_through_message_id uuid,
    read_through_time timeuuid,
    read_through_message_id uuid,
    status_version bigint,
    updated_at timestamp,
    PRIMARY KEY ((dialog_id), recipient_user_id)
);
```

Одна строка описывает, до какого входящего сообщения конкретный recipient
durably обработал/прочитал dialog. Это масштабируется лучше, чем update каждой
message row при range read.

Effective status для исходящего message:

```text
if message_time <= peer.read_through_time      -> READ
else if message_time <= peer.delivered_through_time -> DELIVERED
else                                            -> SENT
```

Для одинакового timeuuid tie не нужен, но message ID остаётся в cursor/contract.

### Sync projection

```sql
CREATE TABLE sync_events_by_user_bucket (
    user_id uuid,
    bucket_day date,
    sync_time timeuuid,
    event_id uuid,
    event_type text,
    schema_version int,
    payload blob,
    occurred_at timestamp,
    PRIMARY KEY ((user_id, bucket_day), sync_time, event_id)
) WITH CLUSTERING ORDER BY (sync_time ASC, event_id ASC)
  AND default_time_to_live = 2592000;
```

Baseline retention — 30 дней. История messages хранится бессрочно, а старый
sync cursor получает `410 sync.full_resync_required`.

Для time-series TTL projection после измерений рассмотри
`TimeWindowCompactionStrategy`; не применяй её механически к таблицам без TTL.

## 6. Schema management

Cassandra schema должна быть versioned в repository:

```text
cql/
  0001_keyspace.local.cql
  0001_keyspace.production.cql
  0002_dialogues.cql
  0003_messages.cql
  0004_receipts_sync.cql
```

Добавь `schema_migrations(version text PRIMARY KEY, applied_at timestamp,
checksum text)`. Migration runner:

- применяет файлы по порядку;
- проверяет checksum уже применённого файла;
- не делает destructive `DROP` автоматически;
- завершается до старта consumer/API;
- имеет отдельную deployment role при нескольких replicas.

## 7. Cassandra adapter и asyncio

На дату документа официальный `cassandra-driver` 3.30.x проверяет Python 3.14
и Cassandra 5.0. Выбор зафиксируй в собственном Poetry lock:
[Apache driver changelog](https://github.com/apache/cassandra-python-driver/blob/trunk/CHANGELOG.rst).

Driver `execute_async` возвращает callback future, не обычный coroutine. Спрячь
bridge в infrastructure adapter:

```python
import asyncio
from typing import Any

from cassandra.cluster import ResponseFuture, Session


async def await_response(future: ResponseFuture) -> Any:
    loop = asyncio.get_running_loop()
    result: asyncio.Future[Any] = loop.create_future()

    def succeed(value: Any) -> None:
        loop.call_soon_threadsafe(result.set_result, value)

    def fail(error: BaseException) -> None:
        loop.call_soon_threadsafe(result.set_exception, error)

    future.add_callbacks(succeed, fail)
    return await result


class CassandraDialogRepository:
    def __init__(self, session: Session, statements: Statements) -> None:
        self._session = session
        self._statements = statements

    async def get(self, dialog_id: UUID) -> Dialog | None:
        rows = await await_response(
            self._session.execute_async(
                self._statements.get_dialog,
                (dialog_id,),
            )
        )
        row = rows.one()
        return map_dialog(row) if row is not None else None
```

Все hot queries должны быть prepared на startup. Задай execution profiles с
timeout, consistency и idempotent flag. Не retry LWT timeout вслепую: сначала
SERIAL read/resolve.

## 8. Создание dialog 1:1

HTTP contract:

```http
POST /api/v1/dialogues
Content-Type: application/json

{"peer_user_id": "019c..."}
```

Порядок:

1. Проверить JWT, взять caller из `sub`.
2. Отклонить self-dialog.
3. Вызвать internal Profile existence check с коротким timeout.
4. Вычислить pair key.
5. Сгенерировать candidate `dialog_id` и `activity_time`.
6. Выполнить LWT reservation `IF NOT EXISTS`.
7. Если LWT applied — candidate является каноническим.
8. Если not applied — использовать существующий `dialog_id`.
9. При timeout выполнить `SERIAL` read pair row; retry только если состояние
   доказанно отсутствует.
10. Idempotent UPSERT `dialog_by_id`, initial activity и pointers обоих users.
11. Вернуть `201` для нового или `200` для существующего dialog.

Partial projection failure возвращает retryable `503 projection_incomplete`.
Повтор читает pair reservation и ремонтирует те же projections.

Не держи LWT открытым во время Profile HTTP call.

## 9. List/history HTTP contracts

### Dialog list

```text
GET /api/v1/dialogues?cursor=<opaque>&limit=50
```

Baseline `limit`: default 50, min 1, max 100.

Алгоритм:

1. Decode HMAC cursor и проверить `subject=user_id`.
2. Читать current month activity partition после clustering position.
3. Oversample bounded candidates, например `limit * 3`.
4. Проверить current pointers по вычисленным shards.
5. Удалить stale activity rows из результата и duplicate dialog IDs.
6. При недостатке перейти в предыдущий month bucket.
7. Вернуть не более `limit` current summaries и next cursor.
8. Отдельный repair job удаляет stale positions bounded batches.

### Message history

```text
GET /api/v1/dialogues/{dialog_id}/messages?before=<opaque>&limit=50
```

Сначала прочитать `dialog_by_id` и проверить membership. Для non-member вернуть
`404 dialog.not_found`.

History читает month buckets от нового к старому. Cursor содержит `dialog_id`,
bucket и Cassandra clustering position. Page-number запрещён.

Один bounded read receipt watermarks позволяет вычислить statuses всей page
без одного query на message.

## 10. `message.send.v1`

Command payload:

```json
{
  "clientMessageId": "019c...",
  "dialogId": "019c...",
  "text": "Привет",
  "attachmentIds": []
}
```

Input rules:

- `client_message_id` — UUIDv7;
- text после Unicode NFC normalization — максимум 4096 code points;
- line endings нормализуются в `\n`;
- хотя бы text или attachment;
- максимум 4 уникальных attachment IDs;
- порядок attachments сохраняется и входит в fingerprint;
- sender ID берётся из authenticated `userId` в payload команды (формируется WebSocket Gateway).

Application command:

```python
@dataclass(frozen=True, slots=True)
class SendMessage:
    sender_id: UUID
    client_message_id: UUID
    dialog_id: UUID
    text: str | None
    attachment_ids: tuple[UUID, ...]
    correlation_id: UUID
    causation_id: UUID
```

## 11. Durable message handler

Порядок обработки:

1. Валидировать envelope/version.
2. Прочитать dialog и проверить sender membership.
3. Определить recipient.
4. Если есть attachments, синхронно получить immutable descriptors у Object
   Storage **до Cassandra reservation**.
5. Построить semantic payload hash.
6. Сгенерировать message ID, message time, sync positions и deterministic event
   IDs только для первой попытки.
7. LWT insert canonical request snapshot `IF NOT EXISTS`.
8. При существующей row сравнить payload hash.
9. При mismatch опубликовать `message.rejected.v1`, затем ACK command.
10. При safe duplicate загрузить прежний canonical snapshot.
11. UPSERT history, lookup, sender/recipient sync и dialog activity projections.
12. Убедиться, что все обязательные writes подтверждены.
13. Опубликовать target-specific events с IDs из snapshot.
14. ACK Kafka command только после broker ACK событий.

Псевдокод:

```python
async def handle(self, command: SendMessage) -> None:
    dialog = await self._dialogs.get(command.dialog_id)
    membership = dialog.require_member(command.sender_id)
    attachments = await self._objects.validate_for_message(
        owner_id=command.sender_id,
        object_ids=command.attachment_ids,
    )
    fingerprint = fingerprint_message(command, attachments)

    reservation = await self._requests.reserve_or_get(
        identity=MessageRequestIdentity.from_command(command),
        request_hash=fingerprint,
        candidate=CanonicalMessageSnapshot.create(...),
    )
    if reservation.is_conflict:
        await self._events.publish_rejection(...)
        return

    snapshot = reservation.snapshot
    await self._projections.repair_all(snapshot)
    await self._events.publish_all(snapshot.events)
```

Network publish не находится внутри Cassandra LWT.

## 12. Deterministic target events

Один message создаёт минимум два события:

- `message.persisted.v1` target=sender;
- `message.created.v1` target=recipient.

IDs:

```python
from uuid import UUID, uuid5

EVENT_NAMESPACE = UUID("...")  # project constant


def message_event_id(
    message_id: UUID,
    event_type: str,
    target_user_id: UUID,
) -> UUID:
    return uuid5(
        EVENT_NAMESPACE,
        f"{message_id}:{event_type}:{target_user_id}",
    )
```

Event Kafka key — wire-поле `targetUserId`, чтобы dispatcher видел per-user order.

При crash после publish до command ACK command приходит снова, но event IDs те
же. Client и WS Gateway обязаны допускать duplicate event.

## 13. Delivery и read через watermarks

Один command type:

```json
{
  "commandType": "receipt.advance.v1",
  "payload": {
    "dialogId": "019c...",
    "kind": "DELIVERED",
    "throughMessageId": "019c..."
  }
}
```

Для `READ` используется тот же формат с `kind=READ`.

Handler:

1. Прочитать through message по ID.
2. Проверить dialog, recipient и membership.
3. Прочитать current watermark row.
4. Если candidate position не больше current — duplicate no-op.
5. Для READ одновременно продвинуть delivered не ниже read.
6. LWT update `IF status_version=:old_version`.
7. При race перечитать и повторить bounded loop.
8. Записать sender sync event.
9. Опубликовать `receipt.watermark_advanced.v1` target=original sender.
10. ACK command после event broker ACK.

Event содержит `kind`, `throughMessageId`, `throughMessageTime` и
`statusVersion`. Client применяет только большую version.

Преимущество watermark: одно открытие dialog не делает тысячи writes по одной
на message.

## 14. `/sync`

```text
GET /api/v1/sync?cursor=<opaque>&limit=100
```

Cursor привязан к user ID и содержит day bucket + `sync_time` + `event_id`.

Client protocol:

1. Сначала открыть replacement WebSocket.
2. Начать buffer realtime events.
3. Читать `/sync` pages от последнего локально committed cursor.
4. Сохранить page локально транзакционно.
5. Только затем сохранить next cursor.
6. Merge buffered events по wire-полям `eventId`, `messageId`, `statusVersion`.
7. Отправить delivered watermark после локальной durable обработки.

Если cursor старше 30 дней, вернуть `410 sync.full_resync_required`; client
получает dialog list и истории заново.

## 15. Repair jobs

Нужны bounded jobs:

- проверить canonical request snapshot и восстановить missing message
  projections;
- удалить stale dialog activity positions;
- сверить current pointer с activity row;
- измерить orphan canonical requests;
- проверить sync projection lag.

Job принимает bucket/range, continuation cursor и batch limit. Он не выполняет
полный cluster scan в одном запуске.

## 16. Readiness и metrics

### HTTP role

- Cassandra обязательна -> unavailable означает readiness 503;
- Profile internal endpoint не нужен для большинства routes и отражается как
  degraded dependency, но create dialog может вернуть 503;
- Kafka не нужна list/history и не должна блокировать HTTP readiness.

### Consumer role

- Cassandra и Kafka обязательны;
- Object Storage обязательна только для commands с attachments;
- при Cassandra outage consumer перестаёт коммитить offsets.

Metrics:

- command total/outcome/latency by command type;
- Cassandra latency/timeouts by operation name, без IDs;
- LWT applied/not-applied/unknown;
- projection repair attempts/results;
- Kafka consumer lag/rebalances;
- sync page size/lag/expired cursor;
- receipt advance/no-op/conflict.

## 17. Tests

### Schema/query tests

- каждый repository query содержит полный partition key;
- код не содержит `ALLOW FILTERING`;
- clustering order соответствует cursor;
- local migration применима повторно;
- production keyspace template имеет RF=3.

### Dialog tests

- self-dialog rejected;
- unknown peer rejected;
- concurrent pair LWT возвращает один dialog ID;
- LWT timeout разрешается SERIAL read;
- crash после reservation ремонтирует projections;
- non-member получает hidden 404.

### Message tests

- first command создаёт один canonical message;
- same ID/same payload ремонтирует и републикует те же event IDs;
- same ID/different payload rejected;
- non-member rejected без reservation;
- Cassandra timeout не коммитит Kafka offset;
- event publish failure вызывает redelivery и safe republish;
- history пересекает month boundary без duplicate/skip;
- concurrent newer insert не ломает older cursor page.

### Receipt/sync tests

- DELIVERED advance;
- READ напрямую из SENT;
- late DELIVERED после READ — no-op;
- duplicate range — no-op с current state;
- foreign message/recipient скрыт;
- status version monotonic;
- realtime event во время sync корректно merge-ится;
- client crash до cursor commit повторяет page безопасно;
- expired cursor -> 410.

## 18. Acceptance

Этап завершён, когда через реальные Kafka и Cassandra:

1. два users создают один dialog;
2. duplicate create возвращает тот же dialog ID;
3. message command сохраняется один раз;
4. sender и recipient получают durable sync projections;
5. history возвращает message;
6. receipt watermarks дают `DELIVERED`, затем `READ` без обратного перехода;
7. process crash/redelivery не создают другой message/event identity;
8. Cassandra outage не приводит к ACK command;
9. `/sync` восстанавливает данные без участия WebSocket.
