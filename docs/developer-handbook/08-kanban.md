# 8. Kanban: карточки в правильном порядке

## Как перенести на доску

Создайте колонки:

```text
BACKLOG -> READY -> THEORY -> IMPLEMENTATION -> VERIFICATION -> DONE
```

WIP-limit для одного разработчика:

- одновременно одна карточка в `IMPLEMENTATION`;
- одна дополнительная карточка может ждать в `VERIFICATION`;
- новая бизнес-фича не начинается, пока красный обязательный test предыдущей не классифицирован.

Не оценивайте карточки часами. Если карточку нельзя завершить одним небольшим осмысленным изменением, разделите её по слоям: contract → domain/application → adapter → transport → integration test.

## Шаблон карточки

```markdown
# [M?.??] Короткий измеримый результат

## Зачем
Одно предложение о пользовательской или архитектурной ценности.

## Перед началом
- [ ] зависимости DONE
- [ ] прочитана указанная теория

## Сделать
- [ ] ...

## Проверить
- [ ] конкретная команда/test/scenario

## Готово, когда
- [ ] измеримый acceptance criterion
- [ ] docs/contracts обновлены
- [ ] нет секретов и чувствительных данных в логах
```

Каждая карточка ниже уже содержит зависимость и критерий. Создавайте их все в `BACKLOG`, а в `READY` сначала перенесите только `M0.01`.

---

# M0 — Identity registration event

> Блокирует весь Profile. Не начинайте `M1`, пока `M0.11` не DONE.

## M0.01 — Зафиксировать контракт `identity.user_registered.v1`

**Теория:** transactional outbox и event envelope из глав 0–2.

**Зависит от:** ничего.

- [x] добавить JSON Schema в root `contracts/identity/events/`;
- [x] camelCase envelope: `eventId`, `eventType`, `schemaVersion`, `occurredAt`, `producer`, `correlationId`, `causationId`, `payload.userId`, `payload.registeredAt`;
- [x] Kafka record key=`userId`; source — то же canonical wire-поле payload;
- [x] добавить valid/invalid examples;
- [x] валидировать schema в CI.

**Готово:** root schema и fixtures зафиксированы, проходят локальные contract
tests и автоматический CI gate.

## M0.02 — Добавить outbox migration в Identity

**Зависит от:** M0.01.

- [x] таблица, индексы, lease/retry/quarantine fields;
- [x] upgrade/downgrade;
- [x] constraint на event ID и валидные состояния;
- [x] integration test migration.

**Готово:** migration накатывается на чистую и текущую DB, откат проверен в test environment.

## M0.03 — Ввести domain/application outbox port

**Зависит от:** M0.01.

- [x] immutable `OutboxMessage`;
- [x] `OutboxRepositoryProtocol`;
- [x] clock/ID generator через ports;
- [x] application слой не импортирует SQLAlchemy/Kafka.

**Готово:** unit tests проверяют построение event и отсутствие transport types.

## M0.04 — Сохранить User и event одной транзакцией

**Зависит от:** M0.02, M0.03.

- [x] расширить Identity UoW;
- [x] при реальном первом создании пользователя добавить outbox row;
- [x] rollback откатывает обе записи;
- [x] duplicate/replay не создаёт новый logical event.

**Готово:** integration test доказывает `user+event` или `ничего`.

## M0.05 — Реализовать outbox claim/lease repository

**Зависит от:** M0.02.

- [x] `FOR UPDATE SKIP LOCKED` маленькими batches;
- [x] lease expiry позволяет подобрать запись после crash;
- [x] exponential backoff + jitter;
- [x] quarantine после configurable attempts.

**Готово:** два relay instance не обрабатывают одну lease одновременно; просроченная lease восстанавливается.

## M0.06 — Реализовать Kafka producer adapter

**Зависит от:** M0.01, M0.03.

- [x] topic `identity.events.v1`;
- [x] key=`user_id`;
- [x] `acks=all` в production config;
- [x] bounded send timeout;
- [x] error translation без raw payload/token в логе.

**Готово:** integration test получает schema-valid event из настоящей Kafka.

## M0.07 — Добавить отдельный relay entrypoint

**Зависит от:** M0.05, M0.06.

- [x] отдельная команда процесса и DI composition root;
- [x] graceful stop;
- [x] publish выполняется вне DB-транзакции;
- [x] mark-published только после broker ACK;
- [x] internal live/ready/metrics без host-published порта.

**Готово:** контейнер relay запускается отдельно от API и обрабатывает backlog.

## M0.08 — Наблюдаемость relay

**Зависит от:** M0.07.

- [x] oldest pending age;
- [x] pending/quarantined count;
- [x] publish duration/result;
- [x] structured logs с event/correlation ID;
- [x] alert thresholds документированы как baseline.

**Готово:** остановка Kafka видна по readiness, lag metric и логам.

## M0.09 — Добавить relay в Compose и CI

**Зависит от:** M0.07.

- [x] service role в root Compose;
- [x] health dependencies без циклического `depends_on`;
- [x] CI поднимает Kafka и Identity DB;
- [x] container smoke.

**Готово:** чистый bootstrap запускает API и relay из одного Identity image.

## M0.10 — Failure-path тест outbox

**Зависит от:** M0.09.

- [x] зарегистрировать user при недоступной Kafka;
- [x] доказать наличие user+pending outbox;
- [x] вернуть Kafka;
- [x] получить ровно один logical event, допускается transport duplicate;
- [x] повтор HTTP не создаёт второго user/event.

**Готово:** тест автоматизирован и стабилен.

## M0.11 — Закрыть Gate G0

**Зависит от:** M0.01–M0.10.

- [x] code/docs/contracts review;
- [x] `git diff --check`;
- [x] unit/integration/contract/container tests;
- [x] event sample сохранён как acceptance evidence;
- [x] известные ограничения записаны.

**Готово:** Profile может полагаться на событие регистрации. Только теперь `M1.01` переводится в `READY`.

---

# M0.5 — Сквозная аутентификация

Эти карточки можно делать после M0 и до первого публичного Profile endpoint.

## M0.5.01 — Расширить Identity JWT audiences

- [x] добавить аудитории Profile, Messages, WS и Storage;
- [x] обновить `.env.example` и docs;
- [x] unit test issuer;
- [x] negative tests wrong audience/issuer/algorithm.

**Готово:** каждый service verifier принимает только свой audience.

## M0.5.02 — Реализовать cookie-to-Bearer в Gateway

**Зависит от:** M0.5.01.

- [x] удалить внешний `Authorization`;
- [x] извлечь `access_token` cookie;
- [x] установить internal Bearer;
- [x] прокинуть/сгенерировать `X-Request-Id`;
- [x] не логировать credential;
- [x] integration tests spoofing/missing/expired token.

**Готово:** browser cookie успешно авторизует `/me` и Profile через Gateway, spoofed header не проходит.

---

# M1 — User Profile text slice

## M1.01 — Создать Profile domain model

**Зависит от:** M0.11.

- [ ] `UserProfile`, `DisplayName`, `Bio`, `Locale`, `ProfileVersion`;
- [ ] правила длины/Unicode/locale;
- [ ] change methods вместо публичной мутации;
- [ ] unit tests.

**Готово:** domain не импортирует FastAPI/Pydantic/SQLAlchemy.

## M1.02 — Создать Profile PostgreSQL schema

- [ ] `profiles` и `processed_events`;
- [ ] version/check constraints;
- [ ] migrations и integration tests;
- [ ] profile DB user не имеет доступа к Identity DB.

**Готово:** schema создаётся с нуля и защищает основные инварианты.

## M1.03 — Реализовать idempotent registration consumer

**Зависит от:** M1.01, M1.02.

- [ ] Kafka adapter;
- [ ] schema validation;
- [ ] inbox fence + profile insert в одной transaction;
- [ ] offset commit после DB commit;
- [ ] retry/quarantine malformed/poison messages.

**Готово:** 100 доставок одного `event_id` создают один profile.

## M1.04 — Добавить Profile consumer process

**Зависит от:** M1.03.

- [ ] отдельный entrypoint/container role;
- [ ] readiness PostgreSQL+Kafka;
- [ ] lag/retry metrics;
- [ ] graceful rebalance/shutdown.

**Готово:** Compose поднимает API и consumer независимо.

## M1.05 — Реализовать GET собственного профиля

**Зависит от:** M1.02, M0.5.02.

- [ ] JWT subject from trusted auth context;
- [ ] repository port/adapter;
- [ ] ETag/version response;
- [ ] no cross-service DB read.

**Готово:** новый user после event получает default profile через Gateway.

## M1.06 — Реализовать PATCH собственного профиля

**Зависит от:** M1.05.

- [ ] partial update DTO;
- [ ] обязательный `If-Match`;
- [ ] CAS `WHERE version=expected`;
- [ ] `428` без precondition, `409/412` при конфликте согласно зафиксированному contract;
- [ ] localization-safe error codes.

**Готово:** две конкурирующие правки не теряют обновление.

## M1.07 — Реализовать public/batch Profile reads

**Зависит от:** M1.05.

- [ ] минимальный публичный DTO без credentials;
- [ ] batch internal endpoint для Messages;
- [ ] лимит batch size;
- [ ] order/missing semantics зафиксированы.

**Готово:** Messages может обогатить список диалогов без N+1.

## M1.08 — Lazy repair profile

**Зависит от:** M1.03, M1.05.

- [ ] если auth user валиден, а profile отсутствует, `INSERT ... ON CONFLICT DO NOTHING`;
- [ ] метрика repair;
- [ ] repair не заменяет consumer и не читает Identity DB.

**Готово:** потерянная до появления consumer локальная запись чинится безопасно.

## M1.09 — Закрыть Gate G1

- [ ] register → event → profile E2E;
- [ ] duplicate/redelivery test;
- [ ] concurrent PATCH test;
- [ ] auth negative tests;
- [ ] docs/OpenAPI/readiness.

---

# M2 — Dialogues по HTTP

## M2.01 — Зафиксировать dialogue contracts

- [ ] create direct dialogue request/response;
- [ ] list dialogues cursor;
- [ ] get history cursor;
- [ ] stable error codes;
- [ ] examples/schema tests.

## M2.02 — Создать Cassandra keyspace и schema runner

- [ ] NetworkTopologyStrategy config;
- [ ] RF=1 local, RF=3 production-like;
- [ ] таблицы direct-pair, dialogue, user activity/position;
- [ ] versioned idempotent CQL migrations;
- [ ] schema agreement/readiness.

## M2.03 — Реализовать Cassandra async adapter

**Зависит от:** M2.02.

- [ ] session lifecycle;
- [ ] prepared statements;
- [ ] driver future → asyncio bridge;
- [ ] consistency/timeouts/retry policy;
- [ ] tracing/error mapping без blocking event loop.

## M2.04 — Создать direct dialogue идемпотентно

**Зависит от:** M2.01–M2.03.

- [ ] canonical pair key;
- [ ] LWT create reservation;
- [ ] deterministic repair projections;
- [ ] self-dialog запрещён;
- [ ] peer existence через bounded internal Profile/Identity contract, не чужую DB.

**Готово:** concurrent create возвращает один `dialog_id`.

## M2.05 — Список диалогов с opaque cursor

- [ ] query user position shards/buckets;
- [ ] bounded merge;
- [ ] signed opaque cursor;
- [ ] batch profile enrichment;
- [ ] stable ordering on equal timestamp.

## M2.06 — История пустого диалога

- [ ] membership check;
- [ ] bucket-aware cursor;
- [ ] empty page semantics;
- [ ] чужой dialogue скрывается как `404`.

## M2.07 — Закрыть Gate G2

- [ ] duplicate/concurrent dialogue tests;
- [ ] pagination without duplicates/gaps;
- [ ] Cassandra restart/readiness test;
- [ ] no ALLOW FILTERING/unbounded scan;
- [ ] OpenAPI и sequence diagrams актуальны.

---

# M3 — Первое durable text message

## M3.01 — Зафиксировать command/event contracts

- [x] `message.send.v1` command;
- [x] `message.persisted.v1` для sender и `message.created.v1` для recipient;
- [ ] `command.accepted/rejected` WS envelopes;
- [x] `clientMessageId` semantics;
- [x] Kafka key=`dialogId` для commands, `targetUserId` для events.

## M3.02 — Добавить message/idempotency/projection tables

- [ ] `message_request_by_sender_bucket`;
- [ ] `messages_by_dialog_bucket`;
- [ ] `message_by_id`;
- [ ] user sync event table;
- [ ] partition-size tests/guardrails.

## M3.03 — WS Gateway принимает соединение

- [ ] cookie/JWT verification + Origin allow-list;
- [ ] connection registry abstraction;
- [ ] bounded outbound queue + one writer;
- [ ] heartbeat/token-expiry close;
- [ ] per-user/device connection limit.

## M3.04 — Gateway принимает `message.send.v1`

- [ ] frame schema/size validation;
- [ ] auth subject overrides client identity;
- [ ] rate limit;
- [ ] Kafka publish с timeout;
- [ ] `command.accepted` только после broker ACK;
- [ ] no local business persistence.

## M3.05 — Messages consumer сохраняет command

- [ ] membership/body/limits validation;
- [ ] idempotency reservation;
- [ ] UUIDv7 public ID + timeuuid order;
- [ ] canonical write и repairable projections;
- [ ] deterministic result/event IDs;
- [ ] offset commit last.

## M3.06 — Отправитель получает canonical event

- [ ] `message.created.v1` опубликован;
- [ ] dispatcher route sender user;
- [ ] все active sender connections получают event;
- [ ] retry не создаёт второй message.

## M3.07 — HTTP history показывает сообщение

- [ ] bucket-aware query;
- [ ] opaque cursor;
- [ ] sender snapshot/attachment empty list;
- [ ] read-after-accepted eventual behavior описано клиенту.

## M3.08 — Закрыть Gate G3

- [ ] lost ACK/retry test;
- [ ] consumer crash after Cassandra write test;
- [ ] duplicate command test;
- [ ] sender realtime + history E2E;
- [ ] lag/backpressure metrics.

---

# M4 — Получатель, receipts и reconnect

## M4.01 — Dispatcher Kafka → Valkey node channel

- [ ] consume durable events;
- [ ] resolve active node IDs;
- [ ] publish node-targeted Pub/Sub payload;
- [ ] Gateway subscribes only own channel;
- [ ] dedupe event ID per connection bounded cache.

## M4.02 — Durable `/sync`

- [ ] per-user durable sync projection;
- [ ] 30-day TTL baseline;
- [ ] signed cursor;
- [ ] page limit;
- [ ] expired cursor → explicit full-resync error/flow.

## M4.03 — Client reconnect state machine

- [ ] persist last applied cursor locally;
- [ ] reconnect with exponential backoff+jitter;
- [ ] call `/sync` before/alongside live stream without reorder loss;
- [ ] dedupe by event ID;
- [ ] resume live.

## M4.04 — Delivered receipt command

- [ ] recipient-only authorization;
- [ ] watermark monotonic CAS/LWT;
- [ ] idempotent retry;
- [ ] sender event;
- [ ] no mass per-message updates.

## M4.05 — Read receipt command

- [ ] all rules M4.04;
- [ ] `read <= delivered` invariant by promoting delivered if needed;
- [ ] dialog-level highest-read watermark;
- [ ] sender status derivation.

## M4.06 — Offline/slow client behavior

- [ ] bounded connection queue;
- [ ] documented close code;
- [ ] routing TTL cleanup;
- [ ] `/sync` repair;
- [ ] metrics slow disconnect/reconnect storm.

## M4.07 — Закрыть Gate G4

- [ ] recipient online event;
- [ ] recipient offline then sync;
- [ ] Valkey Pub/Sub loss then sync;
- [ ] delivered/read monotonicity;
- [ ] multi-device fan-out;
- [ ] node crash/reconnect E2E.

---

# M5 — Typing

## M5.01 — Зафиксировать typing contract

- [ ] `typing.start/stop` client command;
- [ ] server event contains dialogue/user/expiry;
- [ ] no durable cursor;
- [ ] max frame/rate/TTL.

## M5.02 — Реализовать ephemeral routing

- [ ] membership authorization;
- [ ] per-user/dialog throttle;
- [ ] Valkey TTL state/routing;
- [ ] exclude sender connection as product rule dictates;
- [ ] automatic stop by client timer.

## M5.03 — Failure и cleanup tests

- [ ] disconnect без stop;
- [ ] dropped Pub/Sub;
- [ ] reconnect;
- [ ] spam/rate-limit;
- [ ] typing никогда не появляется в Cassandra/Kafka durable history.

## M5.04 — Закрыть Gate G5

**Готово:** индикатор не зависает дольше TTL и его потеря не влияет на сообщения.

---

# M6 — Object Storage, attachments и avatar

## M6.01 — Зафиксировать storage contracts и limits

- [ ] upload ticket/finalize;
- [ ] validate-use/download-ticket internal;
- [ ] purpose/type/size/checksum;
- [ ] idempotency keys;
- [ ] error schemas/examples.

## M6.02 — PostgreSQL metadata и migrations

- [ ] objects/status/version;
- [ ] durable idempotency;
- [ ] cleanup indexes;
- [ ] DB constraints и transition tests.

## M6.03 — MinIO adapter и private bucket bootstrap

- [ ] server-generated key;
- [ ] presigned PUT/GET;
- [ ] required signed headers;
- [ ] short TTL;
- [ ] SDK blocking isolation;
- [ ] bucket never public.

## M6.04 — Upload ticket use case

- [ ] ownership from JWT;
- [ ] allow-list/limits/quota;
- [ ] durable idempotency;
- [ ] no URL/token in logs.

## M6.05 — Finalize use case

- [ ] HEAD outside DB transaction;
- [ ] size/checksum/magic signature;
- [ ] optimistic CAS status/version;
- [ ] concurrent/idempotent retry;
- [ ] reject + async delete.

## M6.06 — Cleanup worker

- [ ] expired pending/rejected only;
- [ ] lease/backoff;
- [ ] idempotent delete;
- [ ] heartbeat/lag metric;
- [ ] READY never auto-deleted in MVP.

## M6.07 — Avatar integration

- [ ] Profile validates owner+purpose+READY;
- [ ] PATCH with profile version;
- [ ] own/public download policy;
- [ ] old avatar retained safely.

## M6.08 — Attachment integration

- [ ] batch validate before message acceptance;
- [ ] immutable snapshot in message/event;
- [ ] max count/total bytes;
- [ ] authorized download via Messages;
- [ ] text-only messages independent of Storage.

## M6.09 — Закрыть Gate G6

- [ ] upload/finalize/avatar E2E;
- [ ] upload/finalize/message/download E2E;
- [ ] foreign/pending/corrupt object tests;
- [ ] MinIO timeout does not hold DB lock;
- [ ] private bucket verified.

---

# M7 — Hardening и scale laboratory

## M7.01 — Унифицировать health/readiness/metrics

- [ ] матрица из главы 6;
- [ ] worker ops internal-only;
- [ ] event loop lag/pool wait/consumer lag;
- [ ] probes дешёвые и bounded.

## M7.02 — Автоматизировать reference E2E client

- [ ] `two-users-chat`;
- [ ] reconnect/sync;
- [ ] receipts/typing;
- [ ] avatar/attachment;
- [ ] machine-readable result и failure diagnostics.

## M7.03 — Contract compatibility gate

- [ ] OpenAPI/AsyncAPI/JSON Schema validation;
- [ ] examples parse;
- [ ] producer/consumer fixtures;
- [ ] breaking change блокирует CI.

## M7.04 — Failure-injection suite

- [ ] Kafka outage/outbox recovery;
- [ ] consumer redelivery;
- [ ] Cassandra ambiguous timeout;
- [ ] Valkey loss/reconnect sync;
- [ ] MinIO timeout;
- [ ] process graceful shutdown.

## M7.05 — Зафиксировать workload contract

- [ ] peak/average и география;
- [ ] online/reconnect/receipt amplification;
- [ ] payload/attachment distribution;
- [ ] hot-dialog scenario;
- [ ] exact success/latency definitions.

## M7.06 — Baseline load report

- [ ] сценарии из главы 6;
- [ ] versions/hardware/replicas/data seed;
- [ ] p50/p95/p99/error/lag/saturation;
- [ ] bottleneck и следующий experiment;
- [ ] никаких неподтверждённых заявлений о 100M DAU.

## M7.07 — Backup/restore drills

- [ ] PostgreSQL PITR/restore;
- [ ] Cassandra snapshot/schema restore;
- [ ] MinIO object restore;
- [ ] key/secret recovery;
- [ ] RPO/RTO measured.

## M7.08 — Security review

- [ ] auth source/audience/origin/CSRF;
- [ ] rate/frame/connection limits;
- [ ] no raw credentials/presigned URL/content in logs;
- [ ] private network boundaries;
- [ ] dependency/container scanning;
- [ ] abuse cases documented.

## M7.09 — MVP release checklist

- [ ] все `G0–G6` закрыты;
- [ ] open TBD имеют owner и не нарушают MVP invariant;
- [ ] clean bootstrap/E2E повторён;
- [ ] known limitations опубликованы;
- [ ] rollback/runbook проверены;
- [ ] production SLA не заявлен без evidence.

---

# Post-MVP — Identity Cassandra laboratory

Эти карточки не перемещаются в `READY`, пока `M7.09` не DONE.

## IM.01 — Написать executable Cassandra session spike

- [ ] access patterns IA-01–IA-07;
- [ ] canonical single-partition model;
- [ ] conditional rotation;
- [ ] ambiguous timeout recovery;
- [ ] bounded partition proof.

## IM.02 — Сравнить PostgreSQL и Cassandra

- [ ] одинаковый correctness suite;
- [ ] latency under contention;
- [ ] write/read amplification;
- [ ] operational cost/repair/failure modes;
- [ ] ADR с решением оставить или мигрировать.

## IM.03 — Реализовать выбранный session adapter

- [ ] не менять application contract без причины;
- [ ] Valkey остаётся hot path;
- [ ] no raw token;
- [ ] replay encrypted;
- [ ] fault/load tests.

## IM.04 — Безопасный cutover

- [ ] greenfield invalidate либо dual-read plan;
- [ ] метрики fallback;
- [ ] rollback;
- [ ] удалить старый adapter только отдельным изменением.

## IM.05 — Session management и auth version

- [ ] list/revoke one/all;
- [ ] `sid`/auth version semantics;
- [ ] fail-open/fail-closed matrix;
- [ ] privacy/security tests.

---

# Быстрый маршрут на сегодня

Если доска кажется огромной, не смотрите дальше этих пяти действий:

1. создать карточку `M0.01`;
2. открыть главы [1](01-contracts-and-security.md) и [2](02-identity-outbox-and-profile.md);
3. написать schema `identity.user_registered.v1`;
4. добавить valid/invalid contract fixtures;
5. остановиться на review контракта — не начинать outbox migration в той же карточке.

Следующий физический шаг всегда только один. Полная карта нужна, чтобы не потерять направление, а не чтобы держать её целиком в голове.
