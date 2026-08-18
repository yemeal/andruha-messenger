# Andruha Messenger Kafka contracts

Этот каталог — source of truth для межсервисных Kafka wire-контрактов MVP.
Сервисы не импортируют его как runtime Python package: producer и consumer хранят собственные DTO и доказывают совместимость со схемами через contract-тесты.

---

## 1. Неподвижные правила wire-format

1. **JSON Schema Draft 2020-12** — стандарт описания схем;
2. **`camelCase`** — все имена JSON-свойств (в DTO допустим `snake_case` при явной сериализации через aliases);
3. **Dot-separated type identifiers** — стабильные имена типов (например, `identity.user_registered.v1`, `receipt.watermark_advanced.v1`);
4. **`additionalProperties: false`** — запрет невалидных, неизвестных и неподдерживаемых полей во всех схемах;
5. **Универсальные базовые конверты** — `command-envelope.v1` и `event-envelope.v1` содержат только общие транспортные и трейсинговые метаданные;
6. **Безопасность идентификации (`userId`)** — `userId` автора действия передается исключительно внутри `payload` команды и проставляется WebSocket Gateway из валидированного JWT (клиент не может подделать автора);
7. **Адресация событий (`targetUserId`)** — события сообщений содержат `targetUserId` (адресат доставки в реальном времени), который одновременно является Kafka partition key для `messaging.events.v1`;
8. **Безопасность данных в ошибках и DLQ** — пароли, токены, email, текст сообщений и имена файлов строго запрещены в диагностических метаданных ошибок и DLQ.

---

## 2. Минимальный набор контрактов MVP

| Контракт | Топик / Partition Key | Producer $\to$ Consumer | Роль и назначение |
|---|---|---|---|
| [`identity.user_registered.v1`](file:///c:/Projects/Andruha/contracts/identity/events/user-registered.v1.schema.json) | `identity.events.v1`<br>`userId` | Identity outbox relay $\to$ Profile consumer | **Событие**. Асинхронно и идемпотентно создает default profile после успешной регистрации. Не содержит учетных данных. |
| [`message.send.v1`](file:///c:/Projects/Andruha/contracts/messaging/commands/message-send.v1.schema.json) | `messaging.commands.v1`<br>`dialogId` | WebSocket Gateway $\to$ Messages worker | **Команда**. Запрос на сохранение текста и/или вложений. `clientMessageId` (UUIDv7) обеспечивает идемпотентность; автор `userId` проставляется шлюзом из JWT. |
| [`receipt.advance.v1`](file:///c:/Projects/Andruha/contracts/messaging/commands/receipt-advance.v1.schema.json) | `messaging.commands.v1`<br>`dialogId` | WebSocket Gateway $\to$ Messages worker | **Команда**. Монотонно продвигает вотермарку `DELIVERED` или `READ` до указанного сообщения `throughMessageId`. Автор `userId` проставляется шлюзом. |
| [`message.persisted.v1`](file:///c:/Projects/Andruha/contracts/messaging/events/message-persisted.v1.schema.json) | `messaging.events.v1`<br>`targetUserId` (отправитель) | Messages worker $\to$ WS dispatcher | **Событие**. Подтверждает автору успешное сохранение в БД, возвращает канонический `messageId` для его `clientMessageId` и переводит сообщение в статус `SENT`. |
| [`message.created.v1`](file:///c:/Projects/Andruha/contracts/messaging/events/message-created.v1.schema.json) | `messaging.events.v1`<br>`targetUserId` (получатель) | Messages worker $\to$ WS dispatcher | **Событие**. Доставляет собеседнику канонический снимок сообщения и вложений в реальном времени. |
| [`message.rejected.v1`](file:///c:/Projects/Andruha/contracts/messaging/events/message-rejected.v1.schema.json) | `messaging.events.v1`<br>`targetUserId` (отправитель) | Messages worker $\to$ WS dispatcher | **Событие**. Сообщает автору о постоянном бизнес-отказе (например, нет прав на диалог). Инфраструктурные сбои сюда не попадают. |
| [`receipt.watermark_advanced.v1`](file:///c:/Projects/Andruha/contracts/messaging/events/receipt-watermark-advanced.v1.schema.json) | `messaging.events.v1`<br>`targetUserId` (отправитель) | Messages worker $\to$ WS dispatcher | **Событие**. Сообщает автору исходных сообщений новый watermark доставки/прочтения и монотонный `statusVersion` для обновления UI. |
| [`dlq-envelope.v1`](file:///c:/Projects/Andruha/contracts/envelope/dlq-envelope.v1.schema.json) | `<topic>.dlq`<br>исходный ключ | Любой consumer $\to$ Оператор / Redrive | **Универсальный DLQ Envelope**. Изолирует поврежденную или неподдерживаемую запись из любого топика, сохраняя сырые исходные байты (`originalValueBase64`) отдельно от диагностических метаданных. |

---

## 3. Партиционирование и адресация (Keys & Routing)

### 3.1. Команды (`messaging.commands.v1`) $\to$ Key = `dialogId`
* Все команды диалога (`message.send.v1` и `receipt.advance.v1`) попадают в одну партицию по `dialogId`.
* Это гарантирует строгий порядок сохранения сообщений и продвижения вотермарок внутри диалога.
* Автор команды передается в `payload.userId` (аутентифицированный пользователь).

### 3.2. События сообщений (`messaging.events.v1`) $\to$ Key = `targetUserId`
* Сервис Messages публикует события, адресованные конкретному пользователю, которому их должен доставить WebSocket Gateway (Dispatcher).
* Поле **`targetUserId`** в `payload` однозначно указывает адресата события в реальном времени и служит **ключом партиции Kafka**:
  * В `message.persisted.v1` $\to$ `targetUserId` = ID отправителя сообщения (подтверждение отправки).
  * В `message.created.v1` $\to$ `targetUserId` = ID получателя (новое входящее сообщение).
  * В `message.rejected.v1` $\to$ `targetUserId` = ID отправителя (уведомление об ошибке).
  * В `receipt.watermark_advanced.v1` $\to$ `targetUserId` = ID автора исходных сообщений (уведомление о прочтении/доставке).
* Партиционирование по `targetUserId` гарантирует строгий порядок доставки событий конкретному пользователю.

---

## 4. Что намеренно не является Kafka-контрактом MVP

* **`typing.started/stopped`** — эфемерные события реального времени с коротким TTL, передаются через WebSocket + Valkey (Redis Pub/Sub);
* **Создание диалога и получение истории сообщений** — синхронные HTTP REST эндпоинты;
* **Редактирование профиля** — HTTP REST с оптимистичной блокировкой версий (`profileVersion`);
* **Загрузка и отдача медиафайлов** — прямые HTTP/S3 потоки в MinIO / Object Storage;
* **Отдельные события `delivered` и `read`** — объединены универсальной вотермаркой `receipt.advance.v1` (команда) и `receipt.watermark_advanced.v1` (событие).

---

## 5. Базовые конверты (Envelopes)

### 5.1. Event Envelope
```json
{
  "eventId": "019c0000-0000-7000-8000-000000000001",
  "eventType": "identity.user_registered.v1",
  "schemaVersion": 1,
  "occurredAt": "2026-08-18T00:10:30.123Z",
  "producer": "andruha-identity-service",
  "correlationId": "019c0000-0000-7000-8000-000000000002",
  "causationId": "019c0000-0000-7000-8000-000000000003",
  "payload": {
    "userId": "019c0000-0000-7000-8000-000000000004",
    "registeredAt": "2026-08-18T00:10:30.120Z"
  }
}
```

### 5.2. Command Envelope
```json
{
  "commandId": "019c1000-0000-7000-8000-000000000001",
  "commandType": "message.send.v1",
  "schemaVersion": 1,
  "issuedAt": "2026-08-18T00:30:00.000Z",
  "producer": "andruha-websocket-gateway-service",
  "correlationId": "019c1000-0000-7000-8000-000000000002",
  "payload": {
    "userId": "019c1000-0000-7000-8000-000000000004",
    "clientMessageId": "019c1000-0000-7000-8000-000000000005",
    "dialogId": "019c1000-0000-7000-8000-000000000006",
    "text": "Привет",
    "attachmentIds": []
  }
}
```

### 5.3. DLQ Envelope
```json
{
  "deadLetterId": "019c7000-0000-7000-8000-000000000001",
  "failedAt": "2026-08-18T01:50:00.000Z",
  "consumer": "andruha-messages-dialogues-service",
  "source": {
    "topic": "messaging.commands.v1",
    "partition": 2,
    "offset": 42,
    "keyBase64": "MDE5YzcwMDAtMDAwMC03MDAwLTgwMDAtMDAwMDAwMDAwMDAy"
  },
  "failure": {
    "code": "messaging.unsupported_contract_version",
    "stage": "UNSUPPORTED_VERSION",
    "retryable": false
  },
  "originalValueBase64": "eyJjb21tYW5kVHlwZSI6Im1lc3NhZ2Uuc2VuZC52MiJ9"
}
```

* `commandId` / `eventId` идентифицируют логическое сообщение и не меняются при ретраях;
* Результирующее событие наследует `correlationId` команды и получает `causationId = commandId`;
* Для команд/событий, порожденных из корневых действий (root-операций, таких как входящий фрейм от клиента), поле `causationId` является **опциональным**;
* Каждый Kafka-топик имеет парный `.dlq` топик (`<topic>.dlq`), куда любой consumer при фатальном сбое (невалидный JSON, неподдерживаемая версия схемы) перенаправляет сообщение в универсальном DLQ envelope.

---

## 6. Версионирование контрактов

* Мажорная версия зафиксирована в суффиксе типа: `.v1`;
* Несовместимые изменения (удаление полей, смена семантики, добавление обязательных полей) требуют создания новой версии схемы (например, `.v2`);
* Все схемы запрещают неизвестные поля (`additionalProperties: false`).

---

## 7. Contract-test suite

Локальный запуск проверки контрактов:

```bash
python -m pip install -r contracts/requirements-dev.txt
python -m unittest discover -s contracts/tests -v
```

Тестовый сьют проверяет:
1. Валидность всех схем и разрешение локальных `$ref` по URN `$id`;
2. Строгое именование свойств в `camelCase`;
3. Успешный прием всех эталонных `valid` примеров;
4. Гарантированное отклонение всех негативных `invalid` примеров;
5. Выполнение contract validation в автоматическом CI-пайплайне.
