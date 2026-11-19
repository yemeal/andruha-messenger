# Andruha: аудит трёх сервисов и интеграционной готовности

Дата: 15 ноября 2026 года. Обследован текущий локальный checkout в C:/Projects/Andruha.

**Вывод:** Identity и User Profile уже образуют работающую основу регистрации, аутентификации, профилей и настроек. Messages and Dialogues содержит существенное доменное и прикладное ядро, но переписка через настоящий API и хранилище ещё не работает. Основной следующий объём — собрать проверяемые вертикальные сценарии на реальных адаптерах. Переписывать готовые Identity/Profile или заново строить домен Messages не требуется.

В ходе аудита найдены и воспроизведены дефекты refresh после истечения идемпотентности, запуска relay после восстановления Kafka, повторного создания группы и повторного редактирования сообщения. Это исследование: исправления кода, тестов, конфигурации и прежних документов не выполнялись.

Отдельный план: [Messages and Dialogues: backlog и критерии приёмки](2026-11-15-messages-dialogues-backlog.md).
Машиночитаемые результаты: [evidence](../verification/andruha-audit-2026-11-15.json).

## 1. Границы и принятые решения

Пользователь поручил только исследование и список задач. Три субагента независимо исследовали Identity, User Profile и Messages and Dialogues; основной агент сопоставил документацию, контракты, инфраструктуру и сквозные сценарии.

Цель будущей реализации — интеграционная готовность полного flow: личные диалоги, Saved, группы, управление участниками, сообщения, история с пагинацией, редактирование, удаление, доставка/прочтение, вложения и события для realtime. Другие сервисы отдельно не аудировались: их интерфейсы рассматриваются как внешние зависимости этого flow.

Подтверждено пользователем во время исследования:

| Вопрос | Решение |
|---|---|
| Источник актуального состояния | Код и результаты проверок; устаревшие статусы документации перечислить отдельно |
| Word ЛР5/ЛР6 и учебные ERD | Вымышленные учебные материалы, к требованиям Andruha не относятся; исключены из backlog |
| Старый MVP только 1:1 | Текущее поручение включает также группы, edit/delete и полный flow сообщений |
| Kafka topics | Целевые identity.events.v1 и messaging.events.v1 |
| Проверка собеседника/участника | Подтверждение завершённой регистрации через Identity; наличие Profile недостаточно |
| Основа Cassandra design | Текущая модель кода, числовая MessagePosition, CONTEXT и ADR; старый direct-only DDL требует переработки |
| Replay редактирования | Повтор старой команды не отменяет более позднюю правку |
| Прочтение в группе | Нужен список всех прочитавших, а не только сводный статус |
| Profile fields | Сохраняется текущая модель: bio до 255 без переносов, ru/en в настройках, строковый avatar_key |
| Статус Profile | Текущая модель сохраняется; смысл и влияние статусов на доступ требуют отдельной задачи |
| EventId при повторной публикации | Решение оставлено открытым; варианты разобраны в разделе 7 |

Учебные требования организаций, org_id, корпоративных администраторов, модераторов и отзыва JWT за 60 секунд не применялись к продукту. Ограничения медиа из Word/ERD также не применялись. Не добавлялись звонки, реакции, пересылка, поиск по сообщениям или mobile push.

## 2. Проверенный снимок

| Репозиторий | Ветка | HEAD | Состояние |
|---|---|---|---|
| Родитель | feat/messenger-frontend | f4b5e2e9866d3b7152733ad240e6520d693f598a | Исходно есть локальные изменения и новые файлы |
| Identity | main | 30ec116e87def5f711a5df1b4632802afedc18c9 | Чистый |
| User Profile | main | cbabe926faf447d55109dccc1f42531c61f07194 | Чистый |
| Messages and Dialogues | feat/messages-dialogues-application-layer | 69314c30e4919534c7a56d709d3d5bd50f2a947e | Чистый |

Локальные HEAD сервисов отличаются от gitlinks родительского HEAD. Результаты относятся к этим рабочим деревьям, а не к произвольному клону опубликованной версии. Существовавшие изменения родителя сохранены. Коммиты, push и PR не выполнялись.

## 3. Что уже сделано

### Identity

Работают HTTP register/login/refresh/logout/me, PostgreSQL credentials и session families, Argon2id вне event loop, непрозрачные refresh-токены с hash в БД, RS256 JWT, HttpOnly cookies и локальная проверка claims. Audience Messages уже предусмотрен.

Регистрация — durable orchestration: резервируется registration operation и user_id, вне SQL-транзакции вызывается защищённый Profile PUT, затем user, outbox и завершение операции фиксируются одной локальной транзакцией. Ответ 201 означает завершение; 202 означает сохранённую незавершённую операцию. Reconciler восстанавливает операции с lease/fencing/retry/redrive. Kafka уведомляет о регистрации; создавать профиль через Kafka consumer сейчас не требуется.

Refresh использует durable fence/replay в PostgreSQL, encrypted result и ускоряющий Valkey с lease/heartbeat/CAS. Valkey outage имеет durable fallback. Outbox имеет claim/retry/quarantine, стабильный идентификатор сохранённого события и отдельный relay process. Есть Alembic, Docker/CI definitions, HTTP health/metrics, безопасный request ID.

Доказательства: [registration orchestration](../../services/identity-service/src/app/application/use_cases/resume_registration/handler.py), [refresh](../../services/identity-service/src/app/application/use_cases/refresh/handler.py), [outbox relay](../../services/identity-service/src/app/application/outbox/relay.py), [worker entrypoint](../../services/identity-service/src/app/entrypoints/messaging/relay.py).

Не реализованы как законченные функции: проверка регистрации произвольных peer/member UUID для Messages, session list/logout-all/remote revoke, password reset/change, email verification, полноценный runtime retention/worker observability. Access JWT stateless и после logout может жить до exp; немедленный отзыв не является текущим обещанием. Перенос session storage в Cassandra не нужен для запуска Messages.

### User Profile

Есть UserProfile/UserSettings и 11 application handlers: default provisioning, обновления профиля/настроек, чтение собственного/публичного/batch профиля, username lookup, existence и настройки. HTTP чтение и PATCH подключены. Используются ETag/If-Match, OCC, durable idempotency, PostgreSQL repositories/readers/UoW и Redis lease/heartbeat/circuit breaker.

Provisioning атомарно создаёт profile, settings и completion marker; replay не затирает поздние изменения. GET не создаёт профиль. JWT проверяется локально; публичные чтения применяют privacy masking. Batch ограничен и устраняет дубли без N+1. Повтор истёкшего idempotency key корректно заменяет expired row без обязательной предварительной очистки.

Доказательства: [HTTP Profile routes](../../services/user-profile-service/src/app/entrypoints/http/routers/profiles.py), [settings routes](../../services/user-profile-service/src/app/entrypoints/http/routers/settings.py), [internal provisioning](../../services/user-profile-service/src/app/entrypoints/http/routers/internal.py), [durable store](../../services/user-profile-service/src/app/infrastructure/idempotency/postgres/durable_store.py).

UpdateAvatar и ResetSettings существуют на application-уровне, но не являются подключёнными внешними функциями. Аватару недостаёт API и Object Storage validation owner/purpose/READY. Profile HEAD подтверждает только строку профиля, а не завершённый аккаунт Identity.

### Messages and Dialogues

Это уже не пустой домен: 16 конкретных command handlers и 2 фасада, 146 source Python files и 81 test Python file.

| Возможность | Уже реализовано | Граница готовности |
|---|---|---|
| Direct | Каноническая пара A/B, запрет self, create_or_get, проверка registered users, восстановление пользовательских проекций | Application + fake repositories |
| Saved | Единственный владелец, create_or_get, отправка себе; собственные сообщения имеют SENT | Application + fakes |
| Группы | Создание, название/аватар, add/remove/leave, передача владения; 1–1000 участников | Domain/application + fakes |
| Права групп | Текущий участник видит всю историю, включая до вступления; после выхода/исключения доступа нет | Domain и race tests; query API отсутствует |
| Полномочия групп | Текущие участники изменяют сведения/состав; только владелец передаёт владение; owner нельзя удалить, выход требует передачи | Текущие правила кода; owner-only управление не вводилось |
| Message | Текст до 4096 code points, нормализация, до 4 уникальных ObjectId, UUIDv7 client_message_id, положительная int position | Domain; реального storage нет |
| Send | Direct/Saved/Group handlers, membership, attachment verifier port, canonical replay; group revision fence | Без production adapters |
| Edit | Общий Message.edit_text, version/is_edited/edited_at, no-op; group handler | Direct/Saved application edit отсутствует; group replay дефектен |
| Receipt | Per-dialog/per-user watermarks, READ включает DELIVERED, монотонность, проверки through-message | Direct/Group handlers + fakes; внешний flow отсутствует |
| События | EventEnvelope, четыре EventFactory метода, OutboxMessage и repository Protocol | Не подключены к handlers/runtime |
| Операционная основа | FastAPI factory, health, logging/request ID, Docker/CI definitions | HTTP подключает только health |

Ключевые источники: [CONTEXT](../../services/messages-dialogues-service/CONTEXT.md), [application](../../services/messages-dialogues-service/src/app/application/README.md), [group aggregate](../../services/messages-dialogues-service/src/app/domain/aggregates/group_dialog.py), [Message](../../services/messages-dialogues-service/src/app/domain/aggregates/message.py), [ADR conditional writes](../../services/messages-dialogues-service/docs/adr/0001-conditional-group-command-writes.md).

**Отсутствуют:** реальные Cassandra schema/driver/repositories, DI business wiring, JWT principal, Identity/Profile/Storage clients, HTTP business routes, query layer и cursor pagination, durable sync, Kafka consumer/relay, обязательные projections/recovery и сетевые edit/delete/receipt flows. Delete отсутствует целиком: нет доменной операции/tombstone, команды и события.

## 4. Находки, требующие внимания

P1 — блокер соответствующего сценария или надёжности. P2 — важный ограниченный дефект/эксплуатационный остаток. Новая отсутствующая функция отделена от регрессии работающего runtime. Подтверждённых P0 в обследованном объёме не установлено.

### F-01 / P1 — Messages не подключён к runtime

[HTTP factory](../../services/messages-dialogues-service/src/app/entrypoints/http/main.py):39 подключает только health; infrastructure/di и entrypoints/messaging не содержат бизнес-композиции. Ни один application handler не вызывается production entrypoints.

Следствие: нельзя через сеть создать чат, сохранить сообщение, прочитать историю или ACK. Нужен первый Cassandra + Identity + HTTP вертикальный срез, затем расширение flow. Количество unit tests и health=200 этой готовности не доказывает.

### F-02 / P1 — expired fence в Identity даёт 500 и откатывает отзыв refresh family

[idempotency_record_repository.py](../../services/identity-service/src/app/infrastructure/database/repositories/idempotency_record_repository.py):33 игнорирует истёкшую строку при чтении, но :72 использует ON CONFLICT DO NOTHING по прежнему ключу. [durable.py](../../services/identity-service/src/app/application/idempotency/durable.py):51–63 после callback откатывает проигравшую запись и выбрасывает RuntimeError, если winner не найден.

Реальное воспроизведение с TTL=1s: refresh R0/K → 204 и R1; после TTL повтор R0/K → 500; revoked_at остаётся NULL; R1 с новым ключом продолжает работать → 204. Security revoke, выполненный callback для consumed R0, откатился вместе с конфликтом fence. Штатный expiry test вручную удаляет expired row и этот случай не ловит.

Нужна атомарная обработка expired fence и regression на PostgreSQL; janitor не должен быть условием корректности. Profile уже имеет conditional UPSERT для сходного lifecycle, но Identity-specific security semantics необходимо сохранить.

### F-03 / P1 — relay завершается при недоступном Kafka bootstrap

Полный E2E дал 38 PASS / 1 FAIL: relay_crash_claim_recovery не восстановился за 90 секунд. Два дополнительных независимых повтора также дали FAIL (96,52 и 96,42 секунды на case). После старта Kafka worker завершился с Exited(1), Connect call failed kafka:29092 и KafkaConnectionError: Unable to bootstrap; брокер затем healthy, outbox остаётся CLAIMED с истёкшим lease.

Suite.stopped('kafka') запускает брокер без ожидания healthy. Worker startup не повторяет bootstrap, в Compose нет restart policy. Поздний сценарий заново запускает relay, поэтому последующая общая сходимость не отменяет этот дефект восстановления.

Исправление должно обеспечить восстановление worker после временной недоступности брокера. Одно увеличение timeout или ручной start не является приёмкой. Отдельно следует уточнить ожидание broker readiness в E2E. Исходный красный прогон сохранён.

Источники: [E2E fault runner](../../scripts/e2e/identity.py):270 и :802, [relay entrypoint](../../services/identity-service/src/app/entrypoints/messaging/relay.py), [Compose relay](../../docker-compose.yml).

### F-04 / P1 — нет Identity контракта для проверки участников

[RegisteredUsersProtocol](../../services/messages-dialogues-service/src/app/application/ports/identity/registered_users.py):7–11 требует completed Identity registration. Identity имеет /auth/me только для caller, но внутреннего lookup/batch произвольных UUID нет.

При registration saga профиль может существовать до commit Identity. Подмена проверки Profile HEAD нарушает подтверждённое правило. Требуются защищённый bounded internal contract Identity и adapter Messages; Profile остаётся источником карточек и username.

### F-05 / P1 — retry создания группы может создать вторую группу

[create_group/command.py](../../services/messages-dialogues-service/src/app/application/commands/groups/create_group/command.py):9 не имеет стабильного operation ID. [handler](../../services/messages-dialogues-service/src/app/application/commands/groups/create_group/handler.py):72 генерирует новый ID при каждом вызове, сохраняет группу :79 до пользовательских проекций :86.

Probe на существующих test fakes: canonical save → ошибка projection → повтор той же команды → две группы с разными ID; исходная проекция не восстановлена. Это подтверждение пробела application boundary, а не потери данных существующего production adapter: его ещё нет.

Нужны stable command identity, persisted result и repair прежних проекций. Тест должен проверять retry, а не только сохранение первой группы после ошибки.

### F-06 / P1 — старый retry edit отменяет позднюю правку

[group edit handler](../../services/messages-dialogues-service/src/app/application/commands/groups/edit_message/handler.py):41–69 повторно читает текущий Message и применяет new_text; отсутствует восстановление durable результата команды.

Probe на существующем test wrapper: А → Б(cmd1) → В(cmd2) → retry cmd1 даёт Б/version4/changed=true. Пользователь подтвердил, что актуальный текст должен остаться В. Нужен command result/replay protocol; этот протокол понадобится и Direct/Saved edit.

### F-07 / P1 — фактические Kafka DTO и routing не соответствуют общим contracts

[EventFactory](../../services/messages-dialogues-service/src/app/application/events/factory.py):71/119/205 использует messages.events, :165 — receipts.events; целевой topic messaging.events.v1 подтверждён пользователем. Identity default [kafka.py](../../services/identity-service/src/app/core/settings/kafka.py):9 использует identity.user-registered.v1 вместо подтверждённого identity.events.v1.

Messages также сериализует causationId:null. [Общая схема](../../contracts/envelope/event-envelope.v1.schema.json) допускает отсутствие поля либо UUID string. Три реальных образца фабрики — persisted, replay persisted и receipt — не прошли Draft202012Validator по этому полю; при его отсутствии прошли. Проходящие общие fixture-тесты это расхождение не ловят.

E2E специально переопределяет Identity topic. Его успех не подтверждает правильность default topic deployment. Нужны contract tests настоящих producer/consumer DTO, унификация конфигурации и versioned contracts для новых групповых/edit/delete сценариев.

### F-08 / P1 для полного flow — группы, edit/delete и sync не помещаются в имеющийся wire-контракт

receipt.watermark_advanced.v1 не содержит reader identity: для группы невозможно определить, кто прочитал. message.v1 не передаёт version/edit/delete state. Изменение старого сообщения нельзя восстановить курсором только по позиции новых отправок.

Нужны per-user receipt events/query со списком прочитавших, versioned edit/delete updates и отдельный поток изменений для sync. Семантика удаления пока не определена: для себя/всех, полномочия, retention и поведение вложений должны быть согласованы до реализации.

### F-09 / P1 для проверки — восемь Messages unit tests зависят от календарной даты

[test_send_direct_message.py](../../services/messages-dialogues-service/tests/unit/application/dialogues/test_send_direct_message.py):118 и [test_send_saved_message.py](../../services/messages-dialogues-service/tests/unit/application/dialogues/test_send_saved_message.py):114 задают handler clock 2026-10-19, а диалоги создают без явного now, с фактической датой ноября.

MessagePostingPolicy корректно запрещает создание сообщения раньше диалога. Результат: 463 PASS / 8 FAIL. Это дефект детерминизма fixtures, не доказательство поломки обычной отправки. Исправлять нужно управление временем тестов с сохранением доменного guard; во время аудита тесты не менялись.

### F-10 / P1 операционный — Profile readiness не отражает отказ PostgreSQL

[main.py](../../services/user-profile-service/src/app/entrypoints/http/main.py):37–38 выставляет ready после создания verifier, без DB probe. [readers/base.py](../../services/user-profile-service/src/app/infrastructure/database/readers/base.py):26 не классифицирует connectivity errors.

Probe production create_app/Dishka с недоступным DB port: /health/ready → 200, public profile → безопасный 500. Текущий README честно описывает process-only readiness; для интеграционной готовности требуется согласованное dependency-aware ready и предсказуемый unavailable response. Happy-path Profile подтверждён отдельно.

### F-11 / P2 — Profile Alembic metadata drift

После upgrade head на чистой изолированной schema, alembic check сообщает remove_constraint(profiles.username) + add_index(ix_profiles_username, unique=True).

[ORM](../../services/user-profile-service/src/app/infrastructure/database/models/profiles.py):44 задаёт unique index, [baseline](../../services/user-profile-service/alembic/versions/0001_profile_storage.py):126 — именованное unique constraint. Repository conflict mapping зависит от profiles_username_key. Текущий schema_match test проверяет таблицы/roundtrip, но не отсутствие metadata diff.

При исправлении сохранить уникальность, корректный 409 и стратегию исторических миграций; не переписывать baseline вслепую.

### F-12 / P2 и будущие gates — эксплуатационные и архитектурные остатки

- Media: AttachmentVerifierProtocol возвращает только None, не принимает purpose и не возвращает immutable descriptors. Он используется и для message attachments, и для group avatar. Нужны owner/purpose/READY/image checks и durable snapshot size/type/checksum; UUID сам по себе недостаточен. Profile UpdateAvatar тоже пока не делает Storage validation.
- Persistence: общий group revision/CAS — контракт, доказанный fakes. Реальная атомарность, global sender/client_message_id uniqueness между видами диалогов, position allocation, cross-partition repair и unknown outcomes ещё не доказаны Cassandra.
- Identity relay: observer не подключён; NullOutboxRelayObserver, отсутствуют отдельные worker health/metrics. Результаты gather(return_exceptions=True) не анализируются. Ошибки DB finalization требуют безопасного сигнала.
- Retention: физическая очистка terminal/expired operation, idempotency/outbox/session данных не подключена полностью. Логическое expiry и физическая очистка — разные задачи.
- Profile: Prometheus counters есть, HTTP exporter не подключён. AES-GCM protector существует, но pipeline его не вызывает; шифрование replay payload нельзя считать включённым.
- Profile domain time: допускаются naive datetime и откат updated_at между версиями; production HTTP defaults используют UTC. Усиление доменной границы — отдельная задача, не основание переписывать сервис.
- Identity migrations импортируют живую ORM metadata. Следующие schema changes требуют замороженных versioned DDL и upgrade/downgrade проверки.
- Root Compose: default Identity DB settings совпадают с default PostgreSQL. Однако изменение IDENTITY_POSTGRES_USER/PASSWORD/DB меняет БД, а DATABASE_* не передаётся API/relay/reconciler: кастомизация может нарушить соединение.
- Root CI проверяет contracts и app smoke; полный Identity/Profile fault E2E не является его обязательным шагом. Health smoke не доказывает сценарий переписки.

### F-13 / P2 dependency gate — Identity dnspython

Runtime pip-audit Identity сообщил два advisory для dnspython 2.8.0: CVE-2026-114605 и CVE-2026-128089. Цепочка: pydantic[email] → email-validator → dnspython.

Первичный [advisory DNS wire parser](https://github.com/rthalley/dnspython/security/advisories/GHSA-45c3-73f7-pv4m) описывает CPU DoS до 2.9.0; [advisory WKS zone parser](https://github.com/rthalley/dnspython/security/advisories/GHSA-vvf4-9x63-8xvv) — memory/CPU DoS до 2.9.2. Источники проверены 15 ноября 2026 года.

Достижимость этих parsing paths через Identity не подтверждена: EmailStr использует check_deliverability=False; прямых dns imports в src не найдено. Это подтверждённый dependency finding и задача безопасного обновления/проверки, без заявления о воспроизведённой удалённой атаке. Runtime scans Profile и Messages не нашли известных уязвимостей на дату прогона.

## 5. Результаты проверок

| Проверка | Identity | User Profile | Messages |
|---|---:|---:|---:|
| Unit | 371 PASS | 490 PASS | 463 PASS, 8 FAIL |
| Integration | 110 PASS | 161 PASS | 8 PASS |
| Реальные зависимости integration | PostgreSQL/Valkey + HTTP Profile peer | PostgreSQL 17.10/Valkey 8.1.9 | Только HTTP bootstrap |
| Ruff lint | PASS | PASS | PASS |
| Ruff Python formatting | PASS | PASS, 232 файла | PASS, 227 файлов |
| ty --error-on-warning | PASS | PASS | PASS |
| uv lock --check | PASS | PASS | PASS |
| Runtime pip-audit | FAIL: 2 advisory | PASS | PASS |

Итого существующие unit/integration suites: 1603 passed и 8 failed. Нет оснований считать восемь падений согласованными учебными RED: подтверждена календарная зависимость.

Дополнительно:

- Общие contracts: 4 unittest checks PASS (включают subtests схем/fixtures). Системный Python первоначально не имел jsonschema; повтор выполнен через изолированный uv с contracts/requirements-dev.txt.
- docker compose config --quiet: PASS. Это проверка модели, не запуск неизменённого стенда.
- Identity/Profile runtime images и API Gateway построены; обе Alembic migrations применены в отдельном E2E project.
- Полный fault E2E: 38 PASS / 1 FAIL, причина relay описана в F-03. Общая проверка сходимости PASS: users=33, profiles=33, settings=33, outbox=33; Kafka deliveries=34, включая один допустимый дубль eventId.
- Два независимых повтора relay_crash_claim_recovery: оба FAIL с той же bootstrap-причиной. Их диагностический harness завершился 0 после сбора данных/cleanup, но вложенные Suite.run оба вернули 1. Автоматическое восстановление после SIGKILL требует отдельного будущего acceptance: существующий сценарий сам вызывает start.
- Проверены registration replay/races, login/JWT/gateway header boundary, refresh/logout races, provisioning, Profile updates/settings/search, отказы DB/Profile/Valkey/Kafka, crash/reconciler/redrive, потеря ответа и отсутствие credential canaries в логах.
- Messages probes: schema violation и два replay-пробела подтверждены; последние два используют существующие fakes, не реальную Cassandra.
- В integration-тестах каждого сервиса есть сторонний Starlette/AnyIO DeprecationWarning. Это не скрытое падение.
- Дополнительный широкий ruff format --check . захватывает Markdown Python fences: 4 документа Profile и 5 Messages требуют LF. Обязательный Python scope проходит; это не провал Python formatter.

Основные команды из родителя:

~~~text
rtk proxy python scripts/codex-service.py <service> unit
rtk proxy python scripts/codex-service.py <service> integration
rtk proxy uv run --no-project --with-requirements contracts/requirements-dev.txt python -m unittest discover -s contracts/tests -v
rtk proxy docker compose config --quiet
~~~

Из сервисов использованы uv run ruff check, read-only ruff format --check в Python scope, uv run ty check --error-on-warning, uv lock --check и runtime export/pip-audit. E2E запущен из Identity: rtk proxy uv run python ../../scripts/e2e/run.py.

**Не запускались/не подтверждены:** coverage threshold, remote GitHub Actions, history secret scan, release/deploy, полный mutating prek, load/HA/backup restore, настоящие Messages Cassandra/Kafka adapters и пользовательский E2E переписки. У этих адаптеров ещё нет реализации. E2E использует generated configuration и disposable keys/volumes; его нельзя выдавать за запуск неизменённого root Compose.

## 6. Документация и достоверность статусов

Просмотрены README/instructions, domain/application/transport docs трёх сервисов, их source/test trees, migrations, dependency/lock metadata, Docker/CI/configuration; общие docs, handbook, contracts, Compose и E2E scripts сопоставлены по зонам ответственности.

| Материалы | Как использованы |
|---|---|
| README, docs/README, project-overview, product-development-plan | Цели, границы и прежние этапы; статусы перепроверены кодом |
| developer-handbook 00–08 | Контракты, правила, persistence/realtime/media/operations и старый Kanban; устаревшие решения отделены |
| mvp-sequence-diagrams | Целевые взаимодействия, retries/order/sync; не доказательство реализации |
| identity architecture/idempotency/migration/E2E docs и verification JSON | История решений и проверок; прежние результаты не подменяют текущие |
| ci-cd-runbook, skeleton spec | Историческая инженерная база; команды и CI проверены по текущим файлам |
| agent-guidelines, adaptation README/research, AGENTS | Действующие ограничения работы; не дополнительное продуктовое scope |
| Service docs Identity | README, integration README, HTTP/worker/persistence composition и проверки |
| Service docs Profile | Все 11 Markdown-файлов: README/AGENTS, postgres/idempotency guides, domain/application/ports/HTTP |
| Service docs Messages | README/CONTEXT, domain/application README, design/walkthrough/hardening/edit/backlog и ADR |
| contracts | Schemas/envelopes/examples/tests, фактический producer output и topics |
| scripts/e2e и root integration workflow | Изоляция, сценарии отказов, реальные границы CI |
| frontend API/Messenger | Только интеграционная граница: auth/profile подключены; отправка сообщений в UI не доказывает backend flow |
| Два DOCX и две ERD PNG | Текст извлечён, диаграммы просмотрены; по ответу пользователя исключены из требований |

Конкретные документы, требующие актуализации:

- Identity tests/integration/README.md:29–31 ещё отрицает outbox publishing; старые Poetry-команды.
- Profile docs/postgres-infrastructure.md:99/124 и idempotency guides говорят health-only/unwired/intentionally-red; текущие маршруты и тесты это опровергают.
- Profile handbook DTO/поля расходятся с текущей подтверждённой моделью; Locale README обещает дополнительные языки, которых нет в enum/SQL.
- Messages README/AGENTS/application README перечисляют шесть handlers; сейчас 16 + 2 фасада.
- Messages прежний application backlog содержит уже реализованные истории, но не закрывает transport/persistence/queries/delete.
- Root contracts README всё ещё описывает Kafka consumer как механизм создания Profile; фактическое provisioning синхронное.
- Root handbook/project-overview/development plan местами называют Messages целиком skeleton и откладывают группы/edit; это прежний snapshot, не актуальная граница поручения.
- Handbook Cassandra DDL/timeuuid/hash нельзя копировать поверх текущего MessagePosition/group revision/no-original-text-hash решения.
- Исторические CI counts/Poetry/coverage/remote-green statements не подтверждены текущим прогоном и не являются текущими фактами.

Исторические документы и инструкции не исправлялись. Обновление актуального contract snapshot включено в backlog.

## 7. Открытое решение: eventId

MessageId обозначает сохранённое сообщение. EventId обозначает уведомление о конкретном изменении. При сбое уведомление может прийти повторно, даже если messageId остаётся прежним.

| Вариант | Как работает | Последствия |
|---|---|---|
| Сохранённый стабильный envelope | При первом принятии сохранить случайный eventId и envelope в durable recovery/outbox record; повтор публикует тот же snapshot | Простая дедупликация по eventId; необходимо надёжное хранение и repair record |
| Детерминированный eventId | Получать ID из версии операции/типа/адресата по согласованному алгоритму | Меньше отдельно генерируемого состояния; нужно различать edit versions, receipt advances и адресатов, иначе сольются разные события |
| Новый eventId на попытку | Каждая публикация получает новый ID; логическую identity передаёт отдельный стабильный operation/version key | Потребителям нужен другой dedupe key; eventId уже обозначает попытку, общие contracts/sync/client expectations придётся пересогласовать |

Рекомендация для рассмотрения — сохранять стабильный envelope один раз. Пользователь это решение пока не утвердил. До выбора нельзя закреплять неизменяемые eventId assertions как уже согласованный продуктовый контракт. Независимо от выбора, повтор не должен создавать второе сообщение или отменять новую редакцию.

## 8. Порядок продолжения

1. Восстановить достоверную базу проверок: календарные fixtures Messages, expired refresh fence, relay startup/recovery; устранить wire topics/serialization drift.
2. Согласовать executable contracts: Identity registered-users, Cassandra schema на текущей модели, edit/delete/receipts/sync и event identity.
3. Собрать Direct + реальная Cassandra + Identity/Profile + JWT + HTTP create/list/history.
4. Подключить durable send, projections/recovery и Kafka command/result path.
5. Довести Saved и группы, конкурентные изменения состава, edit/delete, per-reader receipts и sync.
6. Проверить медиа через реальный Object Storage и realtime через WebSocket Gateway. Это внешние зависимости; без них полный пользовательский flow не принимается.
7. Закрыть общий fault E2E и эксплуатационные gates на согласованном локальном наборе сервисов.

План разбит на отдельные карточки с владельцами репозиториев, зависимостями и критериями приёмки в сопутствующем backlog. Реализация этих карточек настоящим аудитом не разрешалась и не выполнялась.
