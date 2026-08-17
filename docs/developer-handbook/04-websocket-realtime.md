# 04. WebSocket Gateway и realtime

## Итог этапа

WebSocket Gateway должен:

- аутентифицировать долгоживущее соединение;
- поддерживать несколько connections одного user;
- принимать versioned commands;
- публиковать durable commands в Kafka;
- доставлять Kafka events на нужные gateway nodes;
- применять backpressure;
- передавать ephemeral typing;
- безопасно переживать disconnect/crash.

Gateway не решает membership и не хранит message history.

## 1. Process roles

В одном repository нужны две независимые роли:

```text
WS server
  client sockets
  local connection manager
  Valkey node subscription
  Kafka command producer

Event dispatcher
  Kafka messaging.events.v1 consumer group
  Valkey connection registry lookup
  Valkey publish to target gateway channels
```

Kafka event должен быть обработан одним dispatcher consumer, а затем доставлен
на все gateway nodes, где есть connections target user.

Если каждый WS server будет отдельной consumer group, каждый event придёт на
каждый node и создаст лишний broadcast. Если все WS servers находятся в одной
group без routing layer, event может попасть на node без нужной connection.

## 2. Connection state

```python
@dataclass(slots=True)
class Connection:
    connection_id: UUID
    user_id: UUID
    token_expires_at: datetime
    websocket: WebSocket
    outbound: asyncio.Queue[ServerFrame]
    closed: asyncio.Event
```

Local manager indexes:

```text
connection_id -> Connection
user_id -> set[connection_id]
```

Изменения защищаются коротким `asyncio.Lock`, но network send никогда не
выполняется под этим lock.

## 3. Handshake

Порядок `GET /ws`:

1. Проверить `Origin` по exact allowlist.
2. Извлечь HttpOnly `access_token` cookie.
3. Локально проверить RS256 claims и WebSocket audience.
4. Не принимать `user_id` из query/payload.
5. Создать connection ID и bounded outbound queue.
6. Зарегистрировать route в Valkey с TTL.
7. Только после успешной registration принять socket.
8. Отправить `connection.ready.v1`.

При invalid token отправь handshake denial `401`, если ASGI server поддерживает
WebSocket Denial Response. Starlette предоставляет
`send_denial_response`; это нужно проверить Docker smoke test:
[Starlette WebSockets](https://www.starlette.io/websockets/).

Если extension недоступно, contract fallback — принять и немедленно закрыть
application code `4401`. Не допускай различного поведения между replicas.

Valkey registration failure закрывает connect с retryable `1013`: без registry
межузловая доставка недоказуема. Уже сохранённые messages при этом не теряются.

## 4. Valkey connection registry

Не храни socket object в Valkey. Нужна только routing metadata.

Keys:

```text
andruha:ws:v1:connection:{connection_id}
  HASH user_id, gateway_id, connected_at
  TTL 75 seconds

andruha:ws:v1:user:{user_id}:gateways
  SET gateway_id
  TTL refreshed while at least one local connection exists

andruha:ws:v1:gateway:{gateway_id}:users
  SET user_id
  operational cleanup index
```

Registration/heartbeat/delete должны использовать Lua, чтобы связанные keys и
TTL менялись согласованно. Stale records всё равно безопасны: publish на node
без connection превращается в no-op, а `/sync` закрывает gap.

Gateway ID должен быть уникален для process instance, например pod/container
identity + random boot ID. После restart старый ID не переиспользуется.

## 5. Local connection manager и один writer

Несколько coroutines не должны одновременно вызывать `send_json` одного socket.
Каждая connection имеет один writer task:

```python
class ConnectionWriter:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    async def run(self) -> None:
        try:
            while True:
                frame = await self._connection.outbound.get()
                await self._connection.websocket.send_json(
                    frame.model_dump(mode="json")
                )
        except (WebSocketDisconnect, RuntimeError):
            self._connection.closed.set()
```

Enqueue не ждёт бесконечно:

```python
def enqueue(connection: Connection, frame: ServerFrame) -> bool:
    try:
        connection.outbound.put_nowait(frame)
    except asyncio.QueueFull:
        return False
    return True
```

Baseline:

- max inbound frame: 16 KiB;
- Uvicorn inbound queue: bounded;
- application outbound queue: 256 frames;
- optional byte budget: 1 MiB per connection;
- queue overflow: close `1013 slow_consumer`;
- durable events будут восстановлены через `/sync`.

Uvicorn имеет отдельные `ws-max-size`, `ws-max-queue`, ping interval и timeout:
[официальные settings](https://www.uvicorn.org/settings/). Application queue
остаётся нужна, потому что server incoming queue не ограничивает fan-out output.

## 6. Reader loop и frame dispatch

```python
async def read_loop(
    connection: Connection,
    parser: ClientFrameParser,
    dispatcher: ClientCommandDispatcher,
) -> None:
    async for raw in connection.websocket.iter_text():
        if len(raw.encode("utf-8")) > MAX_FRAME_BYTES:
            await send_error(connection, "ws.frame_too_large")
            continue
        try:
            frame = parser.parse(raw)
        except InvalidFrameError as error:
            await send_safe_frame_error(connection, error)
            continue
        await dispatcher.dispatch(connection, frame)
```

Frame handler получает authenticated `connection.user_id` отдельно от payload.
Поля `sender_id`/`recipient_id` в client payload запрещены.

## 7. Heartbeat и token expiry

Можно использовать protocol-level ping Uvicorn, но application всё равно должен
обновлять Valkey TTL только при подтверждённо живой connection.

Понятный MVP contract:

- каждые 25 секунд server отправляет `system.ping.v1` с nonce;
- client отвечает `system.pong.v1`;
- timeout 10 секунд;
- успешный pong обновляет route TTL до 75 секунд;
- token за 60 секунд до `exp` вызывает `auth.expiring.v1`;
- при `exp` socket закрывается `4401 auth.token_expired`;
- client сначала делает HTTP refresh, открывает replacement socket и только
  после `connection.ready` закрывает старый.

Token проверяется при handshake. Для MVP не нужен Identity call на каждый
heartbeat.

## 8. Приём `message.send.v1`

Gateway выполняет только:

1. frame/version/size validation;
2. UUID и content-shape validation;
3. per-connection/per-user rate limit;
4. создание authenticated Kafka command envelope;
5. publish `messaging.commands.v1` с key=`dialog_id`;
6. `command.accepted.v1` только после broker ACK.

Membership проверяет Messages Service.

```python
async def handle_message_send(
    connection: Connection,
    frame: MessageSendFrame,
) -> None:
    quota = await limiter.consume(
        user_id=connection.user_id,
        connection_id=connection.connection_id,
        operation="message.send",
    )
    if not quota.allowed:
        await enqueue_error(
            connection,
            frame.request_id,
            code="rate_limited",
            retry_after_ms=quota.retry_after_ms,
        )
        return

    command = MessageSendEnvelope.from_frame(
        frame=frame,
        authenticated_sender_id=connection.user_id,
        correlation_id=frame.request_id,
    )
    await producer.publish(
        topic="messaging.commands.v1",
        key=str(frame.payload.dialog_id).encode(),
        value=command.model_dump_json().encode(),
    )
    await connection.outbound.put(
        CommandAccepted.for_message(frame)
    )
```

Kafka publish timeout может иметь неоднозначный результат. Gateway отвечает
retryable error, а client повторяет **тот же** `client_message_id`. Messages
idempotency делает оба исхода безопасными.

## 9. Rate limiting

Message command fail-closed при недоступном limiter, чтобы Valkey outage не
превратился в unlimited Kafka flood.

Baseline development limits, настраиваемые environment:

- 20 message commands за 10 секунд на user;
- burst 10 на connection;
- 5 concurrent in-flight publishes на connection;
- exact production values определяются load/abuse tests.

Используй atomic Lua token bucket/sliding window. TTL удаляет inactive keys.
Не создавай Prometheus label на user ID.

## 10. Kafka event dispatcher

Dispatcher consumer получает target-specific event:

```json
{
  "event_id": "...",
  "event_type": "message.created.v1",
  "payload": {
    "target_user_id": "...",
    "message": {}
  }
}
```

Порядок:

1. Validate contract/version.
2. Получить `gateway_id` set target user из Valkey.
3. Если set пуст — ACK event: durable `/sync` уже существует.
4. Publish envelope на каждый `andruha:ws:v1:gateway:{gateway_id}` channel.
5. После bounded routing attempt ACK Kafka event.

Valkey Pub/Sub имеет at-most-once semantics и не хранит сообщения. Это
официально зафиксировано в [Valkey Pub/Sub docs](https://valkey.io/topics/pubsub/).
Поэтому Pub/Sub нельзя использовать вместо sync projection.

При Valkey outage:

- выполнить несколько bounded retries с jitter;
- увеличить `realtime_routing_dropped_total{reason="registry_unavailable"}`;
- ACK event после исчерпания realtime budget;
- client восстановит event через `/sync`.

Бесконечный NACK заблокировал бы partition ради необязательной realtime
оптимизации.

## 11. Gateway node subscriber

Каждый WS server подписан только на свой node channel. Получив event:

1. Validate internal envelope.
2. Найти все local connections target user.
3. Enqueue frame каждой connection.
4. Duplicate event допускается.
5. Queue overflow закрывает только медленную connection.

Не нужно хранить глобальный `event_id` dedupe set в Valkey: это создаст новый
durable-like state. Client обязан dedupe; локальный короткий LRU cache можно
добавить как optimization после измерения.

## 12. Typing

Typing не идёт через Kafka и Cassandra.

Client frames:

```text
typing.started.v1 {dialog_id}
typing.stopped.v1 {dialog_id}
```

Server event:

```text
typing.changed.v1 {dialog_id, user_id, state, expires_at}
```

Порядок:

1. Throttle одну connection+dialog, baseline один STARTED в секунду.
2. Проверить positive membership cache.
3. При miss вызвать internal Messages membership endpoint.
4. Cache positive и short negative result bounded TTL.
5. Publish typing на node channels peer через Valkey.
6. Client очищает indicator в `expires_at`, baseline 5 секунд.

При Messages/Valkey timeout typing quietly dropped и возвращает
`typing.dropped.v1`; socket и message send продолжают работать.

Cache miss никогда не означает «разрешено».

## 13. Graceful shutdown

При SIGTERM:

1. readiness становится 503;
2. новые handshakes отклоняются;
3. connections получают `system.reconnect.v1` с jitter range;
4. Kafka producer прекращает принимать новые commands и flush-ит bounded time;
5. registry records удаляются best-effort;
6. sockets закрываются code 1012/1013;
7. оставшиеся records исчезают по TTL.

Shutdown имеет общий deadline. Нельзя ждать медленного client бесконечно.

## 14. Client state machine

Минимальный test client хранит:

```text
DISCONNECTED
CONNECTING
SYNCING
READY
REFRESHING
BACKOFF
```

Message local states:

```text
PENDING_LOCAL
QUEUED          # command.accepted
SENT            # message.persisted.v1
DELIVERED
READ
REJECTED
```

После reconnect client:

1. открывает socket;
2. получает `connection.ready`;
3. буферизует realtime;
4. вызывает `/sync`;
5. merge events;
6. становится READY.

Этот reference client можно сделать как CLI/pytest helper; production UI не
обязателен для backend acceptance.

## 15. NGINX

Существующий `/ws` route уже передаёт Upgrade/Connection headers. Проверь:

- proxy HTTP 1.1;
- read timeout больше heartbeat interval;
- buffering выключен для WebSocket;
- client/body/frame limits не дают ложного ощущения — frame ограничивает app/
  Uvicorn;
- request ID для handshake;
- access logs не содержат cookie/query token;
- неизвестный Origin не проходит до accepted connection.

## 16. Readiness и metrics

### WS server readiness

Обязательные:

- event loop принимает connections;
- Valkey registry доступен;
- Kafka producer может получить metadata/publish path.

Kafka outage означает, что message commands не принимаются, поэтому readiness
может быть 503. Уже установленные sockets могут оставаться для drain/typing,
но orchestrator не направляет новые.

### Dispatcher readiness

- Kafka consumer assignment/metadata;
- Valkey publish/registry.

Metrics:

- active connections/gateways;
- handshake outcome;
- connection duration;
- inbound frame outcome/type;
- Kafka publish latency/outcome;
- outbound queue depth/overflow;
- realtime routed/dropped;
- heartbeat timeout;
- typing accepted/coalesced/dropped;
- registry latency/failures.

## 17. Tests

### Connection

- missing/invalid/expired token denied;
- wrong Origin denied;
- valid cookie establishes connection;
- registry unavailable -> retryable close;
- multiple connections одного user;
- heartbeat refreshes TTL;
- missing pong closes socket;
- token expiry sends warning and closes;
- crash leaves only expiring registry records.

### Commands

- malformed/unknown version never reaches Kafka;
- payload cannot spoof sender;
- broker ACK precedes `command.accepted`;
- publish timeout returns retryable error;
- duplicate retry keeps client message ID;
- rate limit and limiter outage behavior;
- one writer prevents concurrent socket send.

### Fan-out/backpressure

- event reaches every local connection target user;
- target across two gateway nodes receives event;
- offline target causes no failure;
- duplicate event safe;
- Valkey Pub/Sub loss recovered through `/sync` E2E;
- slow client queue overflow closes only that client;
- bounded shutdown finishes without task leak.

### Typing

- member allowed;
- non-member denied;
- cache miss calls Messages;
- service/Valkey outage drops typing only;
- repeated STARTED coalesced;
- missing STOPPED clears by client expiry.

## 18. Acceptance

Этап завершён, когда два Gateway instances и два test clients демонстрируют:

1. multi-connection registration;
2. send command -> Kafka ACK -> `command.accepted`;
3. Messages event -> cross-node realtime delivery;
4. offline delivery через `/sync`;
5. duplicate event без duplicate local message;
6. slow consumer disconnect без роста памяти;
7. typing с TTL;
8. Gateway/Valkey crash с reconnect и восстановлением.
