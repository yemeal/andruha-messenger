# Взаимодействие с БД

Краткая карта реализованных границ Identity, User Profile и Messages.

| Сервис | Хранилище и доступ | Миграции |
|---|---|---|
| Identity | Собственный PostgreSQL через async SQLAlchemy/asyncpg; Valkey — отдельное состояние idempotency/cache | Alembic через async engine и `run_sync` |
| User Profile | Собственный PostgreSQL через async SQLAlchemy/asyncpg; Redis/Valkey — idempotency coordination | Alembic через async engine и `run_sync` |
| Messages | Cassandra через `execute_async` → asyncio Future → `await`; creation, group membership, Direct/Saved text acceptance, history/list/sync и durable outbox | Собственный async runner, CQL-формат cql-track, V001–V004 |

Messages проверяет регистрацию через защищённый HTTP lookup Identity и не читает
чужие таблицы. Действующий JWT используется до `exp`; новый чат/добавление
участника проверяют ACTIVE в Identity. Profile lifecycle не вводит отдельного
запрета переписки.

Все CQL runtime и миграций асинхронны. Согласованное исключение — только native
`connect/shutdown` в ограниченном lifecycle executor. Подключение, таблицы,
consistency/LWT, timeout и unknown outcome, cancellation, paging, migration lock,
resume и команды собраны в [полном кратком справочнике Cassandra](../services/messages-dialogues-service/docs/database-interactions.md).

Readiness Profile проверяет БД/schema; недоступность PostgreSQL даёт ready503 и
business503. Messages business role проверяет Cassandra/schema и использует
загруженный JWT key ring. При остановке Cassandra readiness и business reads
дают 503, live остаётся 200. Работают Direct/Saved текст, bounded recovery worker,
history/list/sync и сохранение outbox envelopes. Kafka publisher/consumer, group
send/edit/delete/receipts и media/WS остаются незакрытыми карточками backlog.

Проверки текущего Cassandra-этапа: [evidence](verification/andruha-async-cassandra-2026-11-17.json).
Общий статус: [выполнение backlog](audits/2026-11-15-readiness-implementation.md).
