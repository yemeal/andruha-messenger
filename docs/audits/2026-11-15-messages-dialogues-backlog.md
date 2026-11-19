# Messages and Dialogues: backlog до интеграционной готовности

> Начальная оценка ниже относится к моменту аудита. Пользователь затем разрешил
> поэтапную реализацию всех карточек. Текущие статусы, принятые решения и evidence:
> [ход реализации](2026-11-15-readiness-implementation.md). Это не означает, что
> ещё не проверенные storage/realtime критерии уже выполнены.

Дата: 2026-11-15. Это план будущей реализации по результатам аудита; выполнение карточек ещё не разрешено. Учебные Word-отчёты и ERD исключены из требований проекта. Код не менялся. Владельцы/схемы API и БД/новые зависимости требуют согласования при реализации; включение в backlog не означает их утверждения. Целевой продуктовый scope: личные диалоги, Saved, группы, история/пагинация, редактирование и удаление, receipts, attachments и events/realtime во взаимодействии с Identity/User Profile.

Отчёт-основание: [аудит трёх сервисов](2026-11-15-andruha-readiness-report.md). Проверки: [evidence](../verification/andruha-audit-2026-11-15.json).

Все карточки имеют статус **не начато в рамках этого аудита**; существующие реализации переиспользуются. Ни audit findings, ни прохождение тестов не разрешают правки, коммиты, push или PR. Владелец MD-N00/02 — parent contracts + Messages; остальных MD-N — Messages, кроме явно указанных внешних зависимостей. Изменения нескольких сервисов согласовываются отдельным scope.

Приоритет P1 означает блокер соответствующего сценария; P2 — остаток качества/эксплуатации. Работать вертикальными этапами: контракт → минимальная application-правка → реальный adapter → transport → проверка. Карточки infrastructure/query расширяются по мере Direct → Saved → Group, а не выполняются как большой предварительный framework. Ни одна карточка не закрывается за счёт ещё не выполненного real-storage AC.

## Зависимости вне Messages и порядок начала

Следующие задачи также не реализовывались. Они относятся к конкретным репозиториям и требуют отдельного разрешения на изменения.

| ID | Приоритет / владелец | Результат и критерии приёмки |
|---|---|---|
| BASE-01 | P1 / Identity | Исправить expired refresh fence. На настоящем PostgreSQL повтор consumed refresh с тем же ключом после TTL не даёт 500, не откатывает security revoke и соблюдает согласованную reuse policy. Одновременные contenders после TTL не создают две ротации. Cleanup не является условием корректности. Основание F-02 отчёта. |
| BASE-02 | P1 / Identity + parent E2E/Compose | Обеспечить relay bootstrap recovery. После недоступности/перезапуска Kafka и SIGKILL relay процесс восстанавливается автоматически, expired claim доходит до SUCCESS без ручного start. Readiness/liveness роли различаются; startup retry bounded по попытке/времени и имеет backoff. Полный E2E и два изолированных повтора сценария проходят; дополнительно отдельный acceptance проверяет восстановление без ручного start (существующий relay_crash сам выполняет start и этого не доказывает); красные результаты аудита сохраняются как исходное доказательство. Изменение одного timeout не закрывает задачу. F-03. |
| BASE-03 | P1 / Identity + Messages + parent contracts | Зафиксировать и реализовать bounded защищённый internal lookup/batch завершённых аккаунтов. Проверить completed/absent/pending/Profile-only, неверный service credential, timeout и Identity down. API не раскрывает credentials/PII и не публикуется через внешний gateway. Messages adapter использует этот контракт, Profile HEAD остаётся existence-only. До реализации выбрать минимальные DTO/маршрут, а не предполагать готовый endpoint. F-04. |
| BASE-04 | P1 для event integration / Identity + parent | Выравнять identity.events.v1 в default runtime, env/Compose, contracts, producer tests и E2E. Не опираться на test-only override. Дополнительно передавать IDENTITY_POSTGRES_* в DATABASE_* API/relay/reconciler согласованно: default и нестандартные disposable credentials проходят migration/auth/outbox. Секреты не выводятся в diagnostics. F-07/F-12. |
| BASE-05 | P1 операционный / User Profile | Согласовать и реализовать dependency-aware readiness. PostgreSQL down → ready503 и предсказуемый business503; DB/schema/auth config healthy → ready200. Liveness не обращается в БД. После восстановления PostgreSQL сервис возвращается в ready без ручного restart. F-10. |
| BASE-06 | P2 / User Profile | Устранить ORM/Alembic drift. Upgrade head + alembic check на чистой БД без diff; upgrade существующей поддерживаемой схемы сохраняет данные, username uniqueness и корректный 409 при гонке. Имя constraints и repository mapping согласованы. История миграций не переписывается без проверки применённых revisions. F-11. |
| BASE-07 | P2 / Identity | Закрыть runtime dependency audit dnspython: проверить безопасную обновлённую версию/lock и совместимость email validation; runtime pip-audit не содержит двух выявленных advisory. Обновление не заменяет оценку достижимости. Новые зависимости/версии не менялись в аудите. F-13. |
| BASE-08 | Решение / Identity + User Profile + Messages | Сохранить текущие Profile fields/status и определить разницу Identity account status и Profile lifecycle. Утвердить, кто может начинать чат, добавляться в группу и продолжать операции при DISABLED/BLOCKED; добавить негативные contract tests по принятому правилу. Не приписывать текущему Profile block уже работающий межсервисный запрет. |
| BASE-09 | P2 / соответствующий сервис | Runtime retention/metrics/key lifecycle: bounded purge, relay observability и безопасный redrive, Profile metrics exporter, проверка time invariants и явное решение о защите сохранённых replay payload (существующий AES-GCM protector Profile пока не подключён). Каждая подзадача имеет собственного владельца, отдельные AC и не объединяется в переписывание idempotency framework. |
| EXT-01 | P1 для live delivery / WebSocket Gateway, отдельно согласуемый объём | Реальный authenticated WS handshake, Origin policy, broker ACK до command.accepted, dispatcher/fan-out на все устройства, bounded queues и reconnect через Messages sync. Contract producer/consumer использует утверждённые topics/events. Проверить два клиента и два WS instances. Одних Messages events недостаточно для закрытия realtime. |
| EXT-02 | P1 для media / Object Storage, отдельно согласуемый объём | Реальный upload/finalize/validate-use/download-ticket с owner/purpose/READY и immutable descriptors. Проверить private object access и отказ на чужой/незавершённый объект на реальном MinIO. Это внешняя зависимость MD-N14; не подменять её fake UUID. |
| EXT-03 | P1 для edge E2E / parent + API Gateway + тестовый клиент | Реальные точные routes dialogues/messages/sync/internal boundary, cookie-to-principal и contract-compatible client. Текущая UI-демонстрация не заменяет сетевую переписку. Выполнить полный E2E с pinned сервисами, migrations, generated secrets и безопасной очисткой отдельного Docker project. |

Порядок начала:

1. Параллельно ограниченные BASE-01/02 и MD-N01; MD-N00 фиксирует контракты и открытые решения.
2. BASE-03, BASE-04 и MD-N02/03/04/05 готовят интеграционные границы.
3. Первый durable Direct slice: MD-N06/07/08/09/10; принимать создание, сообщение и историю отдельными вертикальными шагами.
4. Расширить те же механизмы до Saved/Group, MD-N11/12/13; не переписывать готовые domain handlers.
5. EXT-01/02/03 + MD-N14/15/16 закрывают полный пользовательский flow. MD-N17 и нужные observability tests добавлять вместе со slices.

Удаление и event identity имеют открытые продуктовые решения: это блокеры только зависимых карточек. Если внешние сервисы остаются за пределами разработки, разрешён частичный gate Messages API/worker, но полная интеграционная готовность не объявляется.

## Состояние старого application backlog

| Старые ID | По коду сейчас |
| --- | --- |
| MD-101..105 | Реализованы handlers создания, rename/avatar, transfer ownership, leave. Recovery создания группы требует MD-N03. |
| MD-201..202 | Group edit handler и repository signature есть; result replay после поздних edits не закрыт. |
| MD-301..305 | Direct/Saved send, Direct ACK и два фасада есть. 8 tests падают по времени, concurrency adapter не доказан. |
| MD-401 | Models/EventFactory/OutboxRepository Protocol есть частично; routing/nullable causation/identity проблемны. |
| MD-402..403 | Handlers не подключены к durable outbox/publish, не реализовано. |
| MD-501..505 | Query layer/DTO/ports/handlers отсутствуют. |
| Delete + persistence + business HTTP/Kafka + внешние клиенты | Старый application-only backlog не охватывает целиком; нужны отдельные задачи ниже. |

## Рекомендуемые вехи

1. **Основание**: определить спорные бизнес-контракты, получить детерминированный verification baseline, закрыть application recovery gaps. Никакой массовой архитектурной переделки.
2. **Первый реальный вертикальный slice**: зарегистрированные A/B -> один Direct -> durable текст -> HTTP history + sender/recipient sync -> события по согласованной identity-политике на реальных Cassandra/Kafka. Saved подключить теми же механизмами.
3. **Полный Messages flow**: группы/права/проекции, edit/delete Direct/Saved/Group, versioned updates и group receipts, pagination и reconnect.
4. **Медиа и внешний realtime**: реальные Object Storage/WS зависимости и итоговые E2E. Если внешние сервисы по-прежнему skeleton, честно фиксировать блокер полной цели; contract stubs не считать интеграционной готовностью.

## MD-N00 — Зафиксировать действующие продуктовые и wire правила

Приоритет P1. Зависимости: нет. Область: docs/contracts design, без runtime изменений в этой задаче.

Решения:

- Источник факта завершённой регистрации: текущий код Identity, не Profile existence — подтверждено пользователем. Нужен ли batch internal endpoint/cache/fact projection — выбрать доступный подтверждающий контракт с Identity owner.
- messaging.events.v1 уже выбран пользователем целевым; закрепить это единой настройкой/контрактом.
- Event identity пользователем оставлена открытой. Сравнить persisted UUIDv7/envelope, deterministic UUID от business identity и fresh publication-attempt ID с отдельным logical dedup key; выбрать один protocol и критерии, затем обновить docs/consumers. Stable eventId в этом draft — предлагаемое направление, не согласованное требование.
- Edit retry: старый command_id возвращает прежний результат и не отменяет позднюю правку; выбрать stable acceptance contract.
- Delete semantics: для всех/только у себя, кто вправе удалять (автор/владелец группы/участник), временное окно/restore/retention, сохранение message identity/position/receipts, видимость attachments. Пока это вопросы, не готовая политика.
- Group READ: пользователь подтвердил список ВСЕХ прочитавших сообщение (как Telegram). Требуются reader identity, query списка readers и однозначный per-reader version scope. Политику авторизации receipt detail/отображения вышедших участников и дополнительные read timestamps уточнить при дизайне; aggregate any/all не заменяет readers list.
- Медиа: MESSAGE против AVATAR/image purpose, descriptors snapshot, immutable READY object, правило авторизации download.

AC: согласованные решения отражены в decision log; текущие кодовые правила и новые предложения разделены; каждый новый/изменённый API/event имеет версию, samples и compatibility plan. Неполученные ответы помечены блокерами зависимых задач, а не угаданы.

Зависимость от MD-N00 означает зависимость от конкретного решения, а не ожидание всех остальных решений. Уже подтверждены Identity registration, topics, текущая storage-модель, edit replay и список group readers. Открыты event identity и deletion policy. Они блокируют только затрагиваемые acceptance criteria; routing/null serialization, fixtures и Identity lookup можно готовить независимо.

## MD-N01 — Сделать существующий verification baseline воспроизводимым

P1. Зависимости: нет. Область: fixtures/tests после разрешения менять код.

Исправить clock consistency в 5 Direct-send и 3 Saved-send tests: dialog time и handler time получают из одного явного fixed clock. Не ослаблять MessageCreatedAtPrecedesDialogError.

AC:

- Полный unit suite проходит на любой текущей дате, включая дату позже 2026-10-19; не добавляются skips/xfails.
- Negative test «message before dialog» продолжает отклонять операцию без изменения state.
- Existing 8 bootstrap integrations, Python-scoped Ruff formatter/linter/ty и lock check проходят.
- Проверены текущие команды CI; remote CI не объявляется зелёным без его фактического запуска.

Основание: F-09 отчёта; tests/.../test_send_direct_message.py:118, tests/.../test_send_saved_message.py:114.

## MD-N02 — Исправить wire serialization и routing существующих событий

P1. Зависимости: topics уже решены; routing и causationId можно исправлять независимо. Только AC о logical event identity зависит от открытого решения MD-N00/EventId, не от удаления. Область: EventFactory/models/contract tests и тестовые ожидания.

AC:

- persisted/created/rejected/receipt уходят в messaging.events.v1, Kafka key равен targetUserId.
- Optional causationId отсутствует при None либо содержит валидный UUID; null не публикуется.
- Выход реальной factory, а не только заготовленные examples, проходит Draft202012Validator + FormatChecker с общей Registry для каждого event type, без/с causationId и с attachments.
- После выбора eventId policy проверяется согласованный dedup/replay protocol. Рекомендованный вариант: logical event повторяет saved identity/envelope, новые target/type/version различаются; альтернативный fresh-attempt ID требует явного logical dedup key во всех consumers/sync. Не считать рекомендованный вариант уже утверждённым.
- Новые consumer/publisher читают уже согласованную настройку topic.

Основание: F-07/F-12; probe_factory.py; factory-validation.json.

## MD-N03 — Сделать создание группы восстанавливаемым

P1. Зависимости: подтверждённые правила групп и дизайн create command identity из MD-N00; delete/EventId не блокируют application repair. Область: CreateGroup command/ports/handler/tests; затем persistence adapter.

AC:

- Одна stable create operation identity передаётся клиентом/transport и сохраняется на retry; новый логический create получает другую identity.
- Первый успешный canonical save сохраняет intent и result group_id/time/revision атомарно.
- Timeout до/после commit, потерянный ответ и сбой проекции любого участника с последующим retry возвращают тот же group_id; canonical groups count остаётся 1.
- Повтор repair не сбрасывает более новую activity/preview/membership.
- Тот же operation ID с другим title/member/avatar intent даёт стабильный conflict, без второй группы.
- Application acceptance воспроизведён на fakes; те же сценарии обязательны для реального adapter в MD-N06. Прохождение fakes не закрывает storage gate.

Основание: F-05; probe_retries.py -> groups_after_retry=2 сейчас.

## MD-N04 — Зафиксировать результат edit-команды и late replay

P1. Зависимости: подтверждённое правило edit replay и дизайн edit command acceptance из MD-N00; delete/EventId не блокируют application fix. Реальное storage-подтверждение следует в MD-N06/08, распространение на Direct/Saved — в MD-N11. Область: edit command acceptance/repository/result/handler; Group first, затем Direct/Saved.

AC:

- A -> B(cmd1), B -> C(cmd2), повтор cmd1 возвращает результат первоначального cmd1 и не меняет сохранённый C/его version/edited_at.
- Retry cmd1 с другим message/actor/text даёт intent conflict.
- Потерянный commit response разрешается по durable command acceptance; неизвестный исход не считается доказанным CAS conflict.
- No-op text и replay принятой команды не создают новую edit-версию/event.
- Одновременное исключение участника и edit не даёт успеха по устаревшему membership.
- Уже принятая old command result не выдаёт неавторизованным caller данные; transport authenticates original actor.

Основание: F-06; docs/message-text-editing...:99, probe B/C/B -> B v4 на текущих fakes.

## MD-N05 — Спроектировать и доказать canonical Cassandra write boundary

P1. Зависимости: подтверждённая модель хранения и command acceptance MD-N03/04. Открытые delete/EventId определяют соответствующие расширения схемы, но не блокируют проектирование базового Direct write boundary. Область: актуальный ADR/DDL/портовые контракты + небольшой проверочный adapter slice.

Пользователь подтвердил current code + ADR источником схемы. Нужно объединить текущие domain int MessagePosition, group common revision, sender-scoped identity во всём сервисе и repairable projections. Старый direct-only handbook CQL не считать готовой схемой. Не переносить PostgreSQL UoW как обещание rollback Cassandra+Kafka.

AC:

- Все access patterns имеют известный partition key; нет ALLOW FILTERING/full scan в hot path.
- Описаны canonical state, command result/intent, revision/position allocation, immutable media descriptors, publication/recovery material и bounded read projections.
- Group membership/send/edit/ACK применяются в общей условной атомарной границе; no-op/replay fence тоже проверяет свежие права.
- Global (sender_id, client_message_id) уникален между Direct/Group/Saved и после перехода месяца/restart; retention соответствует retention message, старый ID не становится новым send.
- Разрешение unknown conditional outcome доказано real integration test, не только docstring.
- Связь int position с persisted order детерминирована, сохраняется при retry/restart; позже не появляется новое входящее сообщение до уже ACK watermark.
- Partition/command-log retention ограничен и не удаляет материал незавершённого recovery. Понятны горячие группы и цена общей revision; high-load production обещания пока не даются.

## MD-N06 — Добавить migrations и реальные репозитории Cassandra

P1. Зависимости: MD-N05. Область: infrastructure persistence/schema runner/config/fixtures, выбранный driver.

AC:

- Versioned migrations/checksum применяются на чистой изолированной Cassandra и повторно безопасно; destructive schema reset не нужен.
- Реализованы Direct/Saved canonical create_or_get, Group conditional stores, messages, receipts, command acceptance и required projection ports.
- Пара A-B/B-A при конкурентном создании возвращает одного победителя; group creation retries не дублируют.
- Два writers последнего group place принимают ровно одного; send/ACK/edit против removal соблюдают CAS порядок; stale absence at_revision не выдаётся как достоверный None.
- Две разные конкурентные отправки имеют разные конечные позиции; конфликт чтения last_position не теряет отправку и имеет оговорённый retry.
- Любая ошибка/timeout не возвращается клиенту как SENT без подтверждённого durable state.
- Integration tests используют реальную Cassandra с изоляцией/teardown и разрешением unknown writes, не fake class.

## MD-N07 — Подключить Identity, JWT и Profile представление

P1. Зависимости: BASE-03 и подтверждённое правило Identity registration из MD-N00; от delete/EventId не зависит. Область: clients/security adapters/composition root; изменения чужих сервисов — отдельные задачи владельцам.

AC:

- Actor берётся из проверенного principal/sub; подставленный actor/userId из тела не меняет пользователя.
- Проверяются подпись/RS256/typ/kid/issuer/audience/exp и обязательные claims по текущему Identity контракту; используется public key ring и согласованная reload policy, fail closed для недостоверного token. Наличие JWKS endpoint не предполагается.
- Direct creation и group add/create различают unregistered vs Identity unavailable; partial registration/Profile-only не считается registered.
- Обычная отправка/чтение не делает синхронный Identity check при каждом действии, если достаточно локальной token verification и membership.
- Profile batch enrichment отдаёт display name/avatar по согласованной privacy политике без N+1; Profile outage не меняет права и не теряет сообщение.
- Contract tests и integration A/B из Identity с настоящими профилями проходят; principal spoof/expired token/foreign dialog denied.

## MD-N08 — Реализовать durable projections, event journal/outbox и recovery

P1. Зависимости: MD-N02/05/06 и выбранный protocol event identity для публикации. Базовое закрытие: Direct/Saved send recovery; расширения edit/delete/group принимаются в MD-N11/12/13. Область: canonical acceptance/recovery adapter + projection updater + Kafka publisher/outbox worker.

AC:

- Принятая Direct/Saved send-команда оставляет восстановимый материал в той же canonical boundary. Поддержка receipt/edit/delete/membership добавляется и принимается вместе с соответствующими MD-N11/12/13.
- Падение после canonical commit, посередине history/lookup/activity/sync updates и после publish до command ACK не меняет logical identities и ремонтируется повтором/worker.
- Старый recovery snapshot не перезаписывает более новую activity/send state. Аналогичная защита edit/delete versions обязательна в MD-N11/12.
- Target events адресуются отправителю и участникам; IDs/dedup/replay следуют выбранной в MD-N00 политике. Сохранение одной identity/envelope предлагается, но ещё не утверждено.
- Publish failure/unknown broker ACK не теряет события; claim lease/fencing/retry/quarantine имеют bounded policy и не позволяют stale worker завершить чужую claim.
- Domain no-op ACK не пропускает незавершённую публикацию предыдущего результата.
- Repair ограничен batch/range/cursor, без полного cluster scan; незавершённые записи не исчезают по TTL.

## MD-N09 — Реализовать query-side: списки, история, point reads, sync

P1. Зависимости: MD-N06/08. Базовое закрытие — send history/list/sync для Direct/Saved; edit/delete/group updates расширяются в MD-N11/12/13, без обратной зависимости на их реализацию. Область: queries/read DTO/ports/adapters, cursor codec, tests.

AC:

- Список пользователя не содержит дублей/stale activity, поддерживает bounded cursor pagination через bucket и stable continuation при concurrent inserts.
- История Direct/Group/Saved возвращает все сообщения в согласованном порядке, без duplicate/skip при переходе month boundary.
- Membership проверяется до выдачи данных; новые group members видят полную историю, ушедшие лишены её, сообщения ушедшего автора сохранены.
- Cursor подписан/opaque, привязан к user/dialog/query/ordering; чужой/повреждённый cursor отклоняется.
- Статусы страницы вычисляются bounded чтением watermarks без N+1 на сообщение.
- Базовый /sync содержит sends; одинаковые события safe replay. Edit/delete/receipt/group updates обязательны в MD-N11/12/13 и общем MD-N16 gate; отсутствие ещё не реализованного delete не блокирует закрытие базового Direct slice.
- Retention/expired cursor даёт согласованный full_resync_required, history остаётся доступной; rebuild snapshot/cursor protocol определён.
- Query не создаёт диалоги/профили/receipts и не меняет бизнес-состояние.

## MD-N10 — Добавить versioned business HTTP API и composition root

P1. Зависимости: MD-N03/04/06/07/09. Закрывается базовый API реализованных Direct/Saved/Group create/management/query; edit/delete и reader detail расширяются в MD-N11/12/13. Область: endpoints/schemas/error mapper/DI, OpenAPI examples, authz tests.

AC:

- Клиент вызывает create/get/list Direct/Saved/Group, group management, history/point read/sync и согласованные mutations через опубликованные endpoints.
- Нужные команды и query handlers реально собраны с production adapters; нельзя поднять business role с fake memory store без явного test mode.
- Responses содержат metadata реализованного базового среза и cursors; edit/delete/version extensions принимаются отдельно в MD-N11/12. Старый v1 contract не нарушается случайным добавлением extra fields.
- Нет различимой утечки чужого dialog/message (единообразный внешний forbidden/not-found по утверждённой политике); internal errors/SQL/CQL/user text не выдаются.
- Create returns success только после нужных canonical/projection effects; retryable incomplete effect сообщает стабильную identity операции.
- Idempotency, If-Match/expectedVersion и status mapping описаны и проверены на API boundary.

## MD-N11 — Завершить редактирование для Direct, Saved, Group

P1. Зависимости: MD-N00/04/06/08/10. Область: Direct/Saved edit commands + общий edit routing + versioned update/sync DTO.

AC:

- Автор в доступном ему диалоге редактирует только text, сохраняя send key/message ID/position/createdAt/attachments.
- Чужой автор и текущий nonmember отклоняются, включая no-op; equivalent normalized text не меняет version/time и не создаёт event.
- Удаление подписи допустимо лишь при оставшихся attachments; пустое сообщение запрещено.
- Late retry прежней edit команды не отменяет позднюю правку; concurrent edits имеют оговорённый version conflict semantics.
- Получатели и sender devices получают update по message ID/version; reconnect sync доставляет edit старого сообщения, а receipt position не сбрасывается.

## MD-N12 — Реализовать удаление сообщений после выбора политики

P1 для полного scope. Зависимости: MD-N00, MD-N05/08/09/10. Область: domain state/methods/application/deletion storage+projection/event contracts; не запускать до product decision.

AC:

- Проверены согласованные author/admin/member rules, виды удаления и окно; отказ не меняет данные.
- Delete устойчиво идемпотентен с stable result, согласован с concurrent edit/send replay, не воскрешается старым repair/event.
- Сохраняется согласованная identity/position/tombstone semantics; history/sync/list preview/unread/read receipts ведут себя по принятому правилу.
- isEdited больше не выводится ошибочно из общей version>1: deletion не выдаётся за edit текста.
- Все устройства и reconnect получают versioned delete; удалённый текст/attachments недоступны при выбранном удалении для всех.
- Физический purge/GC и удержание Object Storage отделены от message transaction и не удаляют чужое или ещё используемое вложение.

## MD-N13 — Завершить group receipts и изменяемый membership в read/realtime

P1 для group flow. Зависимости: MD-N00/06/08/09. Область: versioned group receipt payload/query DTO/fan-out, membership projections.

AC:

- Для каждого сообщения клиент получает список ВСЕХ прочитавших с reader identity, как запросил пользователь; aggregate any/all недостаточен. Query и versioned events имеют однозначный per-reader statusVersion scope.
- Дубли/запоздалые ACK не откатывают watermark/status, READ включает DELIVERED; собственные сообщения и Saved ACK запрещены.
- Ушедший участник не пишет ACK даже по старому snapshot, новый вправе подтвердить старую историю по текущим правилам.
- Добавление/исключение/leave/rename/avatar/ownership отражаются в списках и sync нужных пользователей; повтор старой membership команды не откатывает более новое состояние.
- Receipt delivery нескольким авторам истории группы определена и протестирована; один through-message не теряет подтверждения другого автора в том же диапазоне.

## MD-N14 — Подключить реальные media lifecycle/metadata/download права

P1 для полного scope; внешняя зависимость. Зависимости: MD-N00/06/08/10, готовые business endpoints Object Storage. Владельцы: Messages adapters и отдельная согласованная задача Object Storage.

AC:

- Upload ticket -> bytes PUT -> finalize READY -> send attachment работает на реальном Object Storage/MinIO, не fake UUID.
- Перед первой acceptance подтверждаются owner/permission/purpose/immutable READY descriptors; неверный purpose/не-image avatar/unfinished object недопустимы.
- Canonical message хранит agreed immutable metadata snapshot для wire (objectId/mediaType/size/checksum), сохраняемый при replay/outage/restart.
- Text+attachment и media-only wire не теряют metadata; до 4 уникальных attachments в исходном порядке.
- Download URL выдаётся после текущей membership/read authorization; бывший group member не получает новый URL.
- Replay уже принятого send не зависит от повторной успешности Object Storage, не меняет canonical content.
- Снятие group avatar не удаляет shared bytes; physical GC следует отдельной политике.

## MD-N15 — Добавить Kafka consumer/publisher role и transport failure policy

P1. Зависимости: MD-N02/06/07/08. Область: entrypoints/messaging, lifecycle/config/role readiness, tracing/error/DLQ.

AC:

- Реальные message.send.v1 и receipt.advance.v1 envelopes преобразуются в application commands с доверенным user scope/correlation/causation.
- Broker accepted не считается SENT; offset commit разрешён после обязательного durable effect и публикации результата по согласованному протоколу.
- Business rejection даёт стабильный rejection event, dependency outage/unknown commit не превращается в постоянный отказ.
- Invalid/unsupported envelopes изолируются в DLQ без блокировки partition; transient retry bounded, backpressure/rebalance/shutdown не теряют подтверждённые сообщения.
- Consumer readiness требует Cassandra+Kafka; read HTTP role не блокируется Kafka outage, если read зависимости готовы.

## MD-N16 — Проверить полный интеграционный flow и отказоустойчивость

P1, выходной gate. Зависимости: MD-N01..15 и реальные внешние зависимости. Область: изолированные E2E fixtures/runner/report, без публикации/production deploy.

AC:

- Identity создаёт A/B/C, User Profile доступен; A/B получают один Direct; Saved принадлежит одному actor.
- A создаёт группу, добавляет/исключает C, переименовывает/меняет avatar, передаёт ownership и выходит; current membership определяет API/query/send/ACK/download права.
- Текст и вложения сохраняются один раз; история и список, pagination через bucket, edit/delete, per-group receipt semantics соответствуют согласованным требованиям.
- Два устройства sender/recipient и reconnect после потери realtime восстанавливают state через sync без дублей/отката версий.
- Перезапуск Messages/Kafka consumer, Cassandra/Kafka outage, lost commit response и partial projections покрыты реальными failure tests; нет успеха без durable confirmation.
- Доказаны cross-dialog global send-key uniqueness, group multi-writer races, late edit/delete replay и stale worker fencing.
- Unit/integration/E2E/contract tests, Python formatting/lint/types, lock/audit и роль-specific Docker smoke проходят; unrun checks перечислены отдельно.
- Итоговый report содержит команды, версии/HEAD, counts, ограничения и реальные external blockers. Без WS/Object Storage readiness отмечается как частичная, full scope не закрывается.

## MD-N17 — Обновить действующую документацию и эксплуатационные метрики

P2, часть реализации рядом с соответствующими slices. Зависимости: актуальные контракты/roles.

AC: README/CONTEXT/application map/backlog статусы совпадают с runtime; исторические walkthrough помечены снимками. Handbook DDL соответствует утверждённой schema и Identity source-of-truth. Health отражает реальные обязательные зависимости роли. Есть bounded low-cardinality metrics для accepted/rejected/retry/unknown CAS/repair lag/consumer lag/outbox age/sync expired и safe structured logs без текста сообщений/credentials. Никаких неподтверждённых HA/100M DAU/production readiness обещаний.
