# Contracts Changelog

## 1.0.0 — 2026-08-18

Первый greenfield baseline межсервисных Kafka wire-контрактов для Andruha Messenger MVP.

### Added

- **Универсальные базовые конверты**:
  - `command-envelope.v1` — базовый конверт для команд (`commandId`, `commandType`, `schemaVersion`, `issuedAt`, `producer`, `correlationId`, опциональный `causationId`, `payload`);
  - `event-envelope.v1` — базовый конверт для событий (`eventId`, `eventType`, `schemaVersion`, `occurredAt`, `producer`, `correlationId`, опциональный `causationId`, `payload`).
- **События Identity**:
  - `identity.user_registered.v1` — триггер создания дефолтного профиля после регистрации.
- **Команды Messaging**:
  - `message.send.v1` — сохранение сообщения в диалоге с идемпотентностью по `clientMessageId` (UUIDv7) и `userId` автора в payload;
  - `receipt.advance.v1` — монотонное продвижение вотермарки доставки (`DELIVERED`) или прочтения (`READ`).
- **События Messaging**:
  - `message.persisted.v1` — подтверждение успешного сохранения сообщения для отправителя (`SENT`);
  - `message.created.v1` — доставка снимка нового сообщения получателю в реальном времени;
  - `message.rejected.v1` — сообщение отправителю о постоянном бизнес-отказе;
  - `receipt.watermark_advanced.v1` — уведомление автора о продвижении статуса прочтения/доставки с монотонным `statusVersion`.
- **Канонические модели и DLQ**:
  - `message.v1 (definition)` — общая схема неизменяемого снимка сообщения и вложений;
  - `dlq-envelope.v1` — универсальный operational envelope для изолирования поврежденных/неподдерживаемых сообщений любого топика с сохранением сырых байтов `originalValueBase64`.
- **Тесты и фикстуры**:
  - Valid и targeted invalid фикстуры для каждого контракта (включая root-команды без `causationId`);
  - Набор автоматических тестов `contracts/tests/test_contracts.py` с интеграцией в CI workflow (`.github/workflows/integration.yml`).

### Architectural Decisions

1. **`camelCase` для JSON**: все имена свойств в wire-format используют строгий `camelCase`. Идентификаторы типов остаются dot-separated (`identity.user_registered.v1`).
2. **Универсальные конверты**: базовые конверты команд (`command-envelope.v1`), событий (`event-envelope.v1`) и DLQ (`dlq-envelope.v1`) универсальны для всей системы.
3. **Безопасность идентификации (`userId`)**: автор команды передается внутри `payload.userId` и заполняется шлюзом исключительно из проверенного JWT токена.
4. **Адресация событий и партиционирование (`targetUserId`)**:
   - В топике команд `messaging.commands.v1` ключом партиционирования является `dialogId` (сохраняет порядок команд внутри диалога).
   - В топике событий `messaging.events.v1` ключом партиционирования и адресатом реального времени является `targetUserId` (пользователь, которому WebSocket Gateway доставляет событие).
5. **Опциональный `causationId`**: для операций, инициированных напрямую клиентом/шлюзом (root-операции), `causationId` не требуется.
6. **Универсальный DLQ для каждого топика**: каждый топик использует парную Dead Letter Queue (`<topic>.dlq`) со стандартным `dlq-envelope.v1`.
7. **Вотермарки вместо дискретных событий**: доставка и прочтение объединены в модель вотермарки (`receipt.advance.v1` и `receipt.watermark_advanced.v1`), предотвращая write-storm.
8. **Strict Validation**: все схемы используют `additionalProperties: false` для защиты от опечаток и передачи несанкционированных полей.
