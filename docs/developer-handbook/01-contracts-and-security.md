# 01. Контракты, JWT и общие правила

## Результат главы

До бизнес-интеграций должны быть зафиксированы форматы HTTP errors, Kafka
envelope, WebSocket frames, pagination cursor и authenticated principal.
Producer и consumer не должны одновременно придумывать контракт в коде.

## 1. Где находится источник истины

Корневой `contracts/` должен содержать:

```text
contracts/
  envelope/
    event-metadata.v1.schema.json
    command-metadata.v1.schema.json
    error.v1.schema.json
  identity/
    user-registered.v1.schema.json
  messaging/
    message-send.v1.schema.json
    message-persisted.v1.schema.json
    message-created.v1.schema.json
    message-rejected.v1.schema.json
    receipt-advance.v1.schema.json
    receipt-watermark-advanced.v1.schema.json
    dlq-envelope.v1.schema.json
  websocket/
    client-frame.v1.schema.json
    server-frame.v1.schema.json
  objects/
    descriptor.v1.schema.json
  examples/
    ...valid and invalid fixtures...
```

Service repositories хранят свои Pydantic DTO, но contract tests проверяют их
против root JSON Schema. Общий runtime Python package между repositories не
нужен: он связал бы независимые releases.

## 2. Правило версионирования

Имена commands/events содержат major version:

```text
identity.user_registered.v1
message.send.v1
message.created.v1
receipt.advance.v1
```

Совместимое добавление optional field не меняет major version. Удаление поля,
изменение смысла, типа или обязательности создаёт `.v2` и период совместимости.

Consumer обязан:

- принять только явно поддержанную версию;
- не трактовать `.v2` как `.v1`;
- отправить неизвестную/повреждённую версию в DLQ с безопасной metadata;
- не помещать пользовательский контент в текст ошибки DLQ.

## 3. Kafka event envelope

Базовый envelope:

```json
{
  "event_id": "019c...",
  "event_type": "identity.user_registered.v1",
  "schema_version": 1,
  "occurred_at": "2026-08-17T10:15:30.123Z",
  "producer": "andruha-identity-service",
  "correlation_id": "019c...",
  "causation_id": "019c...",
  "payload": {
    "user_id": "019c...",
    "registered_at": "2026-08-17T10:15:30.120Z"
  }
}
```

Поля:

| Поле | Смысл |
|---|---|
| `event_id` | Уникальная identity события; для repair-публикаций может быть детерминированной |
| `event_type` | Полное имя и major version |
| `schema_version` | Версия envelope payload contract; не заменяет `event_type` |
| `occurred_at` | Время бизнес-события в UTC, не время каждой повторной публикации |
| `producer` | Стабильное service name |
| `correlation_id` | Сквозная операция пользователя |
| `causation_id` | ID command/event, который вызвал текущее событие |
| `payload` | Versioned business data |

Не добавляй `retry_count` в immutable business envelope. Transport attempt
metadata относится к Kafka headers или DLQ wrapper.

Пример Pydantic envelope:

```python
from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class EventEnvelope(BaseModel, Generic[PayloadT]):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: UUID
    event_type: str
    schema_version: Literal[1]
    occurred_at: datetime
    producer: str
    correlation_id: UUID
    causation_id: UUID
    payload: PayloadT
```

`extra="forbid"` полезен для command: опечатка не должна молча исчезать.
Для event consumer во время rolling upgrade допустимость unknown optional fields
должна быть осознанным contract-решением, а не случайным default Pydantic.

## 4. Kafka topics и keys

Для MVP рекомендуется небольшой стабильный набор:

| Topic | Key | Producer | Consumer |
|---|---|---|---|
| `identity.events.v1` | `user_id` | Identity outbox relay | Profile consumer |
| `messaging.commands.v1` | `dialog_id` | WebSocket Gateway | Messages worker |
| `messaging.events.v1` | `target_user_id` | Messages worker | WS dispatcher |
| `messaging.commands.dlq.v1` | исходный key | Messages worker | operator/manual redrive |

`message.send`, `receipt.delivered` и `receipt.read` лучше держать в одном
`messaging.commands.v1`, потому что один topic + `dialog_id` key сохраняет
порядок command внутри dialog. Разделение на разные topics лишило бы систему
порядка между message и receipt.

Kafka гарантирует порядок только внутри одной topic partition, а одинаковый key
попадает в одну partition. См. [официальное описание Kafka](https://kafka.apache.org/documentation/).

Producer baseline:

- `acks=all`;
- idempotent producer включён;
- ограниченное число retries с backoff;
- compression `lz4` или `zstd` после измерения;
- key задаётся явно;
- broker ACK обязателен перед `command.accepted`.

Idempotent Kafka producer предотвращает часть дублей в log, но не заменяет
business idempotency consumer после process crash.

## 5. WebSocket frame envelope

Client frame:

```json
{
  "type": "message.send.v1",
  "request_id": "019c...",
  "sent_at": "2026-08-17T10:15:30.123Z",
  "payload": {
    "client_message_id": "019c...",
    "dialog_id": "019c...",
    "text": "Привет",
    "attachment_ids": []
  }
}
```

Server result:

```json
{
  "type": "command.accepted.v1",
  "request_id": "019c...",
  "server_time": "2026-08-17T10:15:30.140Z",
  "payload": {
    "client_message_id": "019c..."
  }
}
```

Server error:

```json
{
  "type": "error.v1",
  "request_id": "019c...",
  "server_time": "2026-08-17T10:15:30.140Z",
  "payload": {
    "code": "message.payload_too_large",
    "retryable": false,
    "retry_after_ms": null,
    "parameters": {"max_bytes": 16384}
  }
}
```

Нельзя включать exception text, stack trace или внутреннее имя dependency.

Pydantic discriminated union:

```python
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class MessageSendFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["message.send.v1"]
    request_id: UUID
    payload: MessageSendPayload


class TypingStartedFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: Literal["typing.started.v1"]
    request_id: UUID
    payload: TypingPayload


ClientFrame = Annotated[
    MessageSendFrame | TypingStartedFrame,
    Field(discriminator="type"),
]
```

## 6. HTTP error envelope

Все сервисы возвращают одну форму:

```json
{
  "code": "profile.version_conflict",
  "detail": "request cannot be completed",
  "request_id": "019c...",
  "parameters": {
    "current_version": 7
  }
}
```

`detail` не локализуется и не должен раскрывать внутренности. UI переводит
`code` и безопасные `parameters`.

Status baseline:

| Status | Когда использовать |
|---:|---|
| 400 | malformed cursor или protocol-level invalid request |
| 401 | token отсутствует, истёк или невалиден |
| 404 | resource отсутствует либо private resource скрыт от caller |
| 409 | version/idempotency/state conflict |
| 413 | превышен byte size |
| 415 | media type не поддерживается |
| 422 | форма корректна, но значения нарушают validation/business input rules |
| 423 | тот же idempotent operation обрабатывается другим owner |
| 429 | quota/rate limit, обязательно `Retry-After` |
| 503 | обязательная dependency не позволяет доказать безопасный результат |

## 7. Access token contract

Identity уже выпускает RS256 JWT с:

- `iss`;
- `sub`;
- `aud`;
- `iat`;
- `exp`;
- `jti`;
- `role`;
- header `typ=at+jwt` и `kid`.

Перед подключением остальных сервисов Identity configuration должна включать
audience каждого verifier:

```text
andruha-identity-service
andruha-user-profile-service
andruha-messages-dialogues-service
andruha-websocket-gateway-service
andruha-object-storage-service
```

`andruha-api-gateway` не обязан быть audience, пока NGINX не валидирует token.

Каждый service загружает только public key и проверяет фиксированные:

- algorithm `RS256`;
- trusted `kid` key ring;
- issuer `andruha-identity-service`;
- собственный audience;
- `exp` и допустимый clock skew;
- `typ=at+jwt`;
- UUID `sub`;
- известную role.

Не копируй verifier вручную с расхождениями. Перенеси проверенный паттерн из
`services/identity-service/src/app/infrastructure/security/`, адаптируй
audience и сохрани отдельные tests в каждом repository.

## 8. Cookie -> principal на HTTP и WebSocket

Браузер автоматически отправляет HttpOnly `access_token` cookie, но не может
прочитать её JavaScript-кодом.

Текущий Identity `/me` ожидает trusted Bearer token, а NGINX пока не создаёт
его из cookie. До Profile milestone нужно выбрать и реализовать один контракт.
Для текущей архитектуры принят transport mapping в Gateway:

```nginx
# Client Authorization intentionally ignored and overwritten.
proxy_set_header Authorization "Bearer $cookie_access_token";
```

Требования:

1. client-supplied `Authorization` не должен проходить как доверенный;
2. access cookie продолжает передаваться upstream для Identity refresh/logout;
3. downstream всё равно криптографически проверяет Bearer token;
4. Gateway не читает claims и не принимает RBAC-решения;
5. integration test должен доказать cookie-only доступ и невозможность подмены
   через client `Authorization`.

Для WebSocket browser cookie доступна во время handshake. Gateway Service
извлекает cookie через FastAPI dependency и проверяет token до `accept()`.
FastAPI поддерживает Cookie/Depends в WebSocket endpoint:
[официальная документация](https://fastapi.tiangolo.com/advanced/websockets/).

## 9. Origin, CORS и CSRF

Cookie authentication требует явной browser policy:

- production `Secure=true`;
- точный список trusted origins;
- `Access-Control-Allow-Origin` не может быть `*` с credentials;
- WebSocket handshake отклоняет неизвестный `Origin`;
- unsafe HTTP methods проверяют CSRF token либо строгую комбинацию Origin,
  Fetch Metadata и SameSite policy;
- login/refresh/logout не должны становиться исключением без threat review.

Для локального same-origin клиента API Gateway может обслуживать UI с того же
origin. До публикации в интернет нужно реализовать double-submit CSRF:

1. server выдаёт отдельный случайный `csrf_token` cookie без `HttpOnly`;
2. client копирует значение в `X-CSRF-Token`;
3. Gateway или service сравнивает значения constant-time;
4. CORS разрешает header только trusted origins;
5. token не является access token и может ротироваться отдельно.

## 10. Request, correlation и causation IDs

| ID | Жизненный цикл |
|---|---|
| `request_id` | Один HTTP request или один WS frame |
| `correlation_id` | Вся пользовательская операция через services |
| `causation_id` | Непосредственный command/event-родитель |

NGINX создаёт доверенный `X-Request-Id` для HTTP. WS client присылает
`request_id`, Gateway валидирует UUID и создаёт новый, если политика требует
server-owned ID. При публикации command:

```text
correlation_id = исходная пользовательская операция
causation_id = WS request_id
```

При создании result event:

```text
correlation_id = command.correlation_id
causation_id = command_id
```

IDs можно писать в logs, но нельзя использовать как Prometheus labels.

## 11. Opaque cursor

Cursor не должен быть обычным page number или доверенным JSON от клиента.
Он кодирует query position и привязывается к user/query:

```json
{
  "v": 1,
  "kind": "sync",
  "subject": "user-uuid",
  "bucket": "2026-08-17",
  "occurred_at": "2026-08-17T10:15:30.123Z",
  "event_id": "019c..."
}
```

Минимальный HMAC codec:

```python
import base64
import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any


def encode_cursor(payload: Mapping[str, Any], key: bytes) -> str:
    body = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = hmac.digest(key, body, "sha256")
    return base64.urlsafe_b64encode(body + signature).rstrip(b"=").decode()


def decode_cursor(raw: str, key: bytes) -> dict[str, Any]:
    padded = raw + "=" * (-len(raw) % 4)
    packed = base64.urlsafe_b64decode(padded)
    if len(packed) <= 32:
        raise InvalidCursorError()
    body, supplied = packed[:-32], packed[-32:]
    expected = hmac.digest(key, body, "sha256")
    if not hmac.compare_digest(supplied, expected):
        raise InvalidCursorError()
    return json.loads(body)
```

Production codec также ограничивает длину input, version, `kind`, `subject`,
типы полей и допустимое временное окно. HMAC key монтируется как secret file.

## 12. Contract test workflow

Для каждого нового contract:

1. Добавить JSON Schema draft 2020-12.
2. Добавить минимум один valid example.
3. Добавить invalid examples: missing field, unknown type/version, wrong UUID,
   extra secret-like field.
4. Проверить schemas отдельным root test.
5. В producer test сериализовать реальный DTO и провалидировать schema.
6. В consumer test прочитать valid fixture и проверить typed command.
7. Проверить rolling compatibility для optional field.
8. Обновить `contracts/README.md` и changelog.

## 13. Acceptance этой главы

- NGINX cookie-to-Bearer mapping имеет integration test;
- Identity выдаёт audience всех текущих verifying services;
- public keys доступны каждому service через read-only secret mount;
- root contracts содержат envelope/error/WS базовые schemas;
- schema tests выполняются воспроизводимой командой;
- request/correlation/causation policy описана в root docs;
- CSRF/Origin policy имеет safe local defaults и fail-closed production
  validation;
- неизвестная Kafka/WS version отклоняется детерминированно.
