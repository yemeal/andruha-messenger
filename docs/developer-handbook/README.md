# Andruha Messenger: полное руководство по реализации backend MVP

**Статус:** рабочее техническое задание и учебное руководство

**Аудитория:** владелец проекта, который реализует систему самостоятельно

**Версия:** 1.0

**Дата:** 2026-08-17

## 1. Что получится в результате

После выполнения этого руководства backend Andruha Messenger должен поддерживать
полный согласованный MVP:

1. регистрацию, login, refresh, logout и получение текущей identity;
2. гарантированное событие о регистрации и асинхронное создание профиля;
3. чтение и конкурентно-безопасное редактирование профиля;
4. создание личного диалога 1:1;
5. список диалогов и cursor-based историю сообщений;
6. отправку текстового сообщения через WebSocket и Kafka;
7. realtime-доставку на все активные соединения пользователя;
8. статусы `SENT`, `DELIVERED`, `READ`;
9. временный индикатор `typing`;
10. восстановление пропущенных событий через `/sync`;
11. прямую загрузку медиа в MinIO/S3 через presigned URL;
12. вложения сообщений и аватар профиля;
13. наблюдаемость, health/readiness, тесты и локальный Docker Compose.

Руководство описывает backend, инфраструктуру, контракты и минимальный тестовый
клиент. Полноценный web/mobile интерфейс пока не входит в существующую систему
репозиториев и рассматривается как отдельный том.

## 2. Как пользоваться руководством

Не пытайся реализовать все сервисы параллельно. Один этап должен дать
работающий сквозной результат, пройти тесты и только потом открывать следующий.

Порядок чтения и реализации:

| Порядок | Глава | Результат |
|---:|---|---|
| 0 | [Инженерная база и рабочий цикл](00-foundations.md) | Понимание DDD, hexagonal architecture, транзакций, событий и тестового цикла |
| 1 | [Контракты, JWT и общие правила](01-contracts-and-security.md) | Стабильные HTTP, Kafka, WebSocket, error и cursor-контракты |
| 2 | [Identity outbox и User Profile](02-identity-outbox-and-profile.md) | `register -> event -> profile`, GET/PATCH профиля |
| 3 | [Messages, Dialogues и Cassandra](03-messages-dialogues-cassandra.md) | Диалоги, текстовые сообщения, история, receipts и `/sync` |
| 4 | [WebSocket Gateway и realtime](04-websocket-realtime.md) | Соединения, команды, fan-out, backpressure и typing |
| 5 | [Object Storage, вложения и аватары](05-object-storage.md) | Presigned upload/finalize/download, message attachments и avatar |
| 6 | [Интеграция, эксплуатация и масштабирование](06-testing-operations-scaling.md) | Сквозные тесты, метрики, сбои, нагрузочные проверки и production topology |
| 7 | [Дальнейшее развитие Identity](07-identity-roadmap.md) | Cassandra session store и оставшиеся Auth-задачи после MVP |
| 8 | [Kanban-карточки](08-kanban.md) | Готовая последовательность небольших задач |

Подробные happy path и failure path уже зафиксированы в
[sequence-диаграммах](../mvp-sequence-diagrams.md). Главы этого руководства
объясняют, как превратить эти сценарии в код и тесты.

## 3. Подтверждённое текущее состояние

### Уже реализовано

`services/identity-service` содержит рабочую предметную и инфраструктурную
реализацию:

- регистрацию пользователя;
- cookie login;
- RS256 access token;
- opaque refresh token и session family;
- атомарную ротацию refresh token;
- durable PostgreSQL idempotency fence;
- зашифрованный AES-256-GCM replay-result;
- Valkey как необязательный hot path;
- logout и `/me`;
- PostgreSQL migration, readiness, metrics, unit и integration tests.

Identity пока **не создаёт** событие о регистрации пользователя. Registration
outbox и relay ещё не реализованы. Root-контракт `identity.user_registered.v1`
уже зафиксирован в `contracts/` на `camelCase`; следующий обязательный пробел —
атомарно записать его envelope вместе с user и реализовать relay.

### Пока являются скелетонами

- `services/user-profile-service`;
- `services/messages-dialogues-service`;
- `services/websocket-gateway-service`;
- `services/object-storage-service`.

В них уже есть `create_app`, logging, request ID, health/readiness, Dockerfile,
Poetry lock и CI. Бизнес-моделей, persistence adapters и контрактов пока нет.

### Интеграционный репозиторий

Корневой репозиторий уже содержит NGINX, три изолированных PostgreSQL, две
изолированные Cassandra, Kafka, Valkey и MinIO. Это локальная одноузловая
топология. Она показывает ownership данных, но не является HA-кластером.

## 4. Неподвижные архитектурные правила

| ID | Правило |
|---|---|
| ARCH-001 | Каждый сервис должен владеть своей предметной моделью и своим durable storage. |
| ARCH-002 | Доменный слой не должен импортировать FastAPI, SQLAlchemy, Cassandra driver, Kafka, Valkey или MinIO SDK. |
| ARCH-003 | Направление зависимостей должно оставаться `entrypoints -> application -> domain`; infrastructure реализует application ports. |
| ARCH-004 | API Gateway должен заниматься transport routing, request ID и ограничениями, но не JWT-валидацией, RBAC или membership. |
| ARCH-005 | Сервисы должны локально проверять RS256 access token; обычный запрос не должен синхронно обращаться к Identity. |
| ARCH-006 | Между сервисами запрещены распределённые транзакции. Неоднозначность закрывается outbox, idempotent consumer, operation ID и repairable projection. |
| ARCH-007 | Kafka используется с at-least-once семантикой. В проекте запрещено заявлять Exactly Once. |
| ARCH-008 | Valkey и WebSocket являются ускорителями. Потеря их состояния не должна уничтожать durable message или receipt. |
| ARCH-009 | Все внешние и межсервисные контракты должны версионироваться в корневом `contracts/`. |
| ARCH-010 | Каждый сетевой timeout должен иметь определённое поведение повторной попытки с тем же operation ID. |

## 5. Функциональные требования

| ID | Обязательное наблюдаемое поведение |
|---|---|
| FR-001 | Identity должен атомарно сохранять нового пользователя и outbox-событие `identity.user_registered.v1`. |
| FR-002 | Identity relay должен повторять публикацию события до Kafka ACK; повторная публикация должна быть безопасной. |
| FR-003 | Profile consumer должен создать ровно один профиль для `user_id`, даже если событие доставлено несколько раз. |
| FR-004 | Пользователь должен читать и редактировать только свой профиль с optimistic concurrency через `If-Match`/version. |
| FR-005 | Система должна создавать не более одного личного диалога для одной канонической пары пользователей. |
| FR-006 | Пользователь должен получать список своих диалогов и cursor-based историю конкретного диалога. |
| FR-007 | WebSocket Gateway должен принять `message.send.v1`, опубликовать команду в Kafka и ответить `command.accepted` только после broker ACK. |
| FR-008 | Messages Service должен сохранить сообщение идемпотентно по `(sender_id, client_message_id)` и сообщить отправителю канонический `message_id`. |
| FR-009 | Все активные соединения отправителя и получателя должны получить соответствующее realtime-событие, если они доступны. |
| FR-010 | Получатель должен явно подтверждать доставку и чтение; состояние не должно двигаться назад. |
| FR-011 | `/sync` должен возвращать пропущенные durable-события после сохранённого клиентом cursor. |
| FR-012 | Typing-событие должно быть временным, throttled и автоматически исчезать без durable-записи. |
| FR-013 | Object Storage должен создавать контролируемый upload intent, выдавать presigned URL и переводить объект в `READY` только после finalize-проверки. |
| FR-014 | Messages должен прикреплять только `READY`-объект назначения `message_attachment`, принадлежащий отправителю. |
| FR-015 | Profile должен устанавливать только `READY`-объект назначения `avatar`, принадлежащий пользователю. |
| FR-016 | Download ticket должен выдаваться только после проверки доступа владельцем бизнес-контекста. |

### Трассировка требований

| Требования | Владелец результата | Milestone / gate | Главная acceptance-проверка |
|---|---|---|---|
| FR-001–002 | Identity API + outbox relay | M0 / G0 | регистрация при недоступной Kafka, затем публикация после recovery |
| FR-003–004 | Profile consumer + API | M1 / G1 | duplicate event создаёт один profile; concurrent PATCH имеет одного winner |
| FR-005–006 | Messages and Dialogues | M2 / G2 | concurrent create даёт один dialog; cursor pages без дублей/пропусков |
| FR-007–008 | WS Gateway + Messages worker | M3 / G3 | потерянный ACK и повтор command дают один canonical message |
| FR-009–011 | Messages + WS dispatcher/Gateway | M4 / G4 | online fan-out, offline reconnect и `/sync`, монотонные receipts |
| FR-012 | WS Gateway | M5 / G5 | typing истекает по TTL и не попадает в durable storage |
| FR-013–016 | Object Storage + Profile/Messages | M6 / G6 | upload/finalize/attach/avatar/download и отрицательные ownership tests |
| Сквозные NFR | Все process roles | M7 / G7 | clean bootstrap, E2E, contract/failure/load/restore evidence |

## 6. Основные инварианты

1. `command.accepted` означает только «Kafka приняла команду».
2. `SENT` означает «каноническое сообщение и обязательные проекции подтверждены
   Cassandra».
3. Сетевой push не означает `DELIVERED`; нужен client ACK после локальной
   обработки.
4. `READ` включает `DELIVERED`.
5. Повторный ACK и запоздавший ACK не могут уменьшить status rank или version.
6. Realtime не является историей. Любой разрыв закрывает `/sync`.
7. Один `client_message_id` с другим payload является конфликтом, а не новой
   командой.
8. Kafka offset нельзя подтверждать до обязательного durable effect и
   обязательной публикации результата.
9. Успешный S3 `PUT` не делает объект доступным. Доступен только `READY`.
10. Постоянный публичный URL объекта нигде не хранится.
11. Профиль не владеет email/password/role/status.
12. Messages не владеет WebSocket connections или байтами медиа.

## 7. Порядок вертикальных milestone

### M0 — Registration integration

Сначала реализуются:

1. JSON Schema события `identity.user_registered.v1`;
2. `outbox_messages` в Identity PostgreSQL;
3. запись user + outbox в одной транзакции;
4. отдельный relay с lease, retry, backoff и safe republish;
5. тест Identity при падении Kafka: регистрация успешна, event остаётся pending;
6. тест восстановления: relay публикует сохранённый event после recovery.

До выполнения этих пунктов бизнес-реализация Profile Service не начинается.
Это отдельный обязательный gate, а не первая часть Profile-разработки.

### M1 — Profile text slice

Результат: idempotent consumer `identity.user_registered.v1`, GET/PATCH
собственного профиля, lazy repair, ETag/version conflict, локальная
JWT-проверка, PostgreSQL migration и сквозной тест
`register -> Kafka -> default profile`.

### M2 — Dialogues over HTTP

Результат: создать/получить 1:1 dialog, получить список, проверить membership и
прочитать пустую историю через Cassandra.

### M3 — First durable text message

Результат: один WebSocket client отправляет команду, Kafka принимает её,
Messages сохраняет сообщение, отправитель получает `message.persisted.v1`.

### M4 — Recipient delivery and reconnect

Результат: второй клиент получает `message.created.v1`, подтверждает delivery/read,
а offline-клиент восстанавливает всё через `/sync`.

### M5 — Typing

Результат: временный throttled typing между участниками без durable storage и
без влияния на message flow.

### M6 — Media and avatar

Результат: ticket -> direct upload -> finalize -> attach/download и avatar.

### M7 — Hardening and scale laboratory

Результат: dependency-failure tests, multi-instance WS, Cassandra RF=3 test
environment, Kafka partitions, load profile, dashboards и documented limits.

## 8. Нефункциональные требования MVP

### Надёжность

| ID | Требование |
|---|---|
| REL-001 | Повтор Kafka command или event не должен создавать второй durable business effect. |
| REL-002 | Потеря HTTP/WebSocket ответа после commit должна разрешаться повтором с тем же operation ID или чтением `/sync`. |
| REL-003 | Недоступность Profile не должна блокировать уже завершённую регистрацию. |
| REL-004 | Недоступность WebSocket или Valkey не должна приводить к потере сохранённого сообщения. |
| REL-005 | Все cross-partition Cassandra projections должны иметь детерминированный repair path. |
| REL-006 | Liveness не должен обращаться к зависимостям; readiness должен проверять только обязательные зависимости текущей process role. |

### Безопасность

| ID | Требование |
|---|---|
| SEC-001 | Публичные сервисы должны принимать identity только из проверенного RS256 token, а не из payload пользователя. |
| SEC-002 | NGINX должен перезаписывать входящий `Authorization` доверенным значением из access cookie либо downstream должен самостоятельно читать cookie. Смешивать оба контракта нельзя. |
| SEC-003 | WebSocket handshake должен проверять token и допустимый `Origin`. |
| SEC-004 | Неавторизованный доступ к приватному dialog/message/object должен возвращать скрывающий существование `404`. |
| SEC-005 | Логи, метрики, traces и DLQ metadata не должны содержать token, cookie, password, message text, filename или object bytes. |
| SEC-006 | Object key должен генерироваться сервисом; клиентский filename не должен участвовать в пути без безопасного преобразования. |
| SEC-007 | Production secrets должны монтироваться файлами и не должны попадать в Git или Compose environment values. |

### Производительность и backpressure

| ID | Требование |
|---|---|
| PERF-001 | HTTP list endpoints должны использовать cursor pagination; page-number pagination запрещена. |
| PERF-002 | Cassandra запрос не должен требовать `ALLOW FILTERING`, cluster scan или чтение без полного partition key. |
| PERF-003 | WebSocket connection должен иметь ограниченную outbound queue; медленный клиент должен отключаться, а не расходовать память без границ. |
| PERF-004 | Kafka key должен сохранять нужный порядок: user, dialog или target user согласно контракту. |
| PERF-005 | Все retry loops должны иметь лимит, backoff и jitter; tight retry loop запрещён. |
| PERF-006 | Argon2, синхронный S3 SDK и другие блокирующие операции не должны выполняться напрямую в event loop. |

Исходные 100 млн DAU, 150 тыс. message writes RPS, SLA 99,99% и p99 2 секунды
являются ориентирами для архитектурной лаборатории, а не acceptance threshold
локального MVP. Сначала нужно измерить один узел и пересчитать согласованную
workload model.

### Наблюдаемость

| ID | Требование |
|---|---|
| OBS-001 | Каждый HTTP request, WebSocket command и Kafka message должен иметь correlation/causation context. |
| OBS-002 | Метрики должны иметь низкую cardinality; `user_id`, `message_id`, `dialog_id` и request ID запрещены как labels. |
| OBS-003 | Каждый сервис должен экспортировать `/metrics`, `/health/live` и `/health/ready`. |
| OBS-004 | Для consumer lag, DLQ, outbox backlog, Cassandra timeout, WS queue overflow и orphan upload должны быть отдельные метрики. |

### Локализация

Backend возвращает стабильный `code` и параметры, но не русские/английские
готовые сообщения. Перевод выполняет клиент. `locale` профиля — BCP 47 tag,
например `ru`, `en`, `ru-RU`. Время хранится в UTC и форматируется клиентом.

## 9. Definition of Done для каждой карточки

Карточка закрывается только когда одновременно выполнены все пункты:

- use case и его граница ответственности описаны;
- domain/application код не зависит от adapter framework;
- contract добавлен или обновлён;
- happy path покрыт unit test;
- invalid/unauthorized path покрыт тестом;
- duplicate/concurrency path покрыт тестом, если применимо;
- dependency timeout/recovery покрыт integration test;
- migration/schema проверены на пустом storage;
- readiness отражает реальную обязательную зависимость;
- логи проверены на отсутствие секретов и контента;
- README сервиса объясняет запуск и новые гарантии;
- Ruff, strict Pyright, tests, coverage, audit и Docker smoke проходят;
- фактически не выполненные проверки явно записаны.

## 10. Контролируемые решения и открытые границы

| ID | Базовое решение для руководства | Когда пересмотреть |
|---|---|---|
| TBD-001 | Scope — backend MVP плюс тестовый client, без production frontend | Если владелец добавляет frontend repository |
| TBD-002 | В MVP internal HTTP endpoints доступны только внутри Docker network; production service authentication проектируется отдельно | До первого внешнего deployment |
| TBD-003 | Sync projection хранится 30 дней; более старый cursor требует full resync | После измерения объёма и UX offline-клиентов |
| TBD-004 | Базовые media limits задаются конфигурацией и перечислены в Object Storage главе | До фиксации продуктовых лимитов |
| TBD-005 | Identity sessions остаются в PostgreSQL для функционального MVP | После завершения M7 перед отдельным Cassandra migration |
| TBD-006 | Поиск пользователей не входит в MVP; тестовый клиент создаёт dialog по известному `peer_user_id` | При проектировании discovery/search |
| TBD-007 | `150k` message write RPS и `45k` read RPS считаются отдельными peak-целями, пока не зафиксирована полная workload model | До выбора production partitions/nodes/replicas |

## 11. Что не делать во время MVP

- не добавлять группы, реакции, edit/delete message или поиск;
- не переносить сообщения SSD -> HDD;
- не добавлять mobile push или Notification Service;
- не делать общий database для нескольких сервисов;
- не использовать Valkey как единственную историю;
- не публиковать Kafka event внутри длительной PostgreSQL-транзакции;
- не оборачивать Cassandra multi-partition writes в ложную «транзакцию»;
- не хранить готовые presigned URL;
- не запускать network I/O из domain entity;
- не начинать с нагрузочного кластера до корректного однопроцессного vertical slice.
