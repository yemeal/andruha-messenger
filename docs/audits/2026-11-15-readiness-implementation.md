# Выполнение backlog интеграционной готовности

Исходный аудит и его JSON сохраняются без изменения результатов.
Поручение пользователя от 2026-11-15 разрешает поэтапную реализацию всех 30 карточек
backlog, включая связанные сервисы и необходимые изменения тестов/контрактов.
Коммиты, push и PR не запрошены; результат остаётся локальным.

## Принятые пользователем решения

- Event identity: UUIDv7 и envelope сохраняются в durable boundary один раз;
  повторная публикация использует тот же eventId/envelope.
- Удаление: для всех, автором без временного окна; в группе также текущим
  владельцем. Без восстановления. Message identity/position сохраняются как
  tombstone; physical media GC выполняется отдельно.
- Identity определяет завершённость регистрации и активность аккаунта.
  DISABLED/BLOCKED Profile относятся к lifecycle профиля и сами по себе не
  вводят дополнительный запрет общения.
- Ранее подтверждённые правила: identity.events.v1 / messaging.events.v1,
  current code + ADR как источник схемы, late edit replay без отмены новой
  правки, список всех group readers.

## Последовательность выполнения

1. Основание: MD-N01; BASE-01/02/04/05/06/07; decision log MD-N00.
2. Границы и application recovery: BASE-03/08, MD-N02/03/04/05.
3. Реальный Direct/Saved slice: MD-N06/07/08/09/10, Cassandra + Kafka.
4. Groups, edit/delete, receipts: MD-N11/12/13; расширение тех же адаптеров.
5. Media/realtime/edge: EXT-01/02/03, MD-N14/15.
6. Итоговый gate: MD-N16; BASE-09 и MD-N17 выполняются рядом со своими slices.

Карточка закрывается только при выполнении всех её AC. Application fakes не
заменяют real-storage acceptance. Незапущенные проверки указываются явно.

## Проверенные результаты

| Карточка | Состояние | Доказательство |
|---|---|---|
| MD-N01 | Выполнена | 471 unit, 8 bootstrap integration; prek all-files passed. В двух send-модулях dialog/handler используют одно fixed time. Negative test времени до создания диалога проходит. |
| BASE-01 | Выполнена | PostgreSQL conditional upsert expired fence; HTTP 401 и сохранённый revoke; гонка 32 запросов. Identity: 371 unit / 112 integration до добавления lookup. |
| BASE-02 | Выполнена | Bounded bootstrap retry/backoff, worker live/ready, init + restart policy. Полный E2E 41/41 и два отдельных успешных повтора automatic recovery без manual start. |
| BASE-03 | Выполнена | Private accounts lookup, контракт v1, max 100, service credential; 6 Identity integration / 7 adapter unit / 1 Messages-to-real-Identity E2E. Profile-only исключён в реальном E2E. |
| BASE-04 | Выполнена | Runtime/producer tests/Compose используют identity.events.v1. Root DATABASE_* согласованы с IDENTITY_POSTGRES_*. Default full E2E и custom-credentials subset 5/5 без topic override. |
| BASE-05 | Выполнена | ready проверяет PostgreSQL tables/JWT, business connection failures дают 503, live не проверяет БД. Реальный stop/start PostgreSQL: ready 200→503→200 без restart Profile. |
| BASE-06 | Выполнена | ORM использует историческое profiles_username_key; baseline не менялся. Реальный alembic check без diff, Profile 490 unit / 166 integration. |
| BASE-07 | Выполнена | dnspython 2.9.2, uv constraint/lock; runtime pip-audit: No known vulnerabilities found. |
| BASE-08 | Выполнена для текущей границы | Решение пользователя записано выше; ACTIVE Identity проходит lookup при BLOCKED Profile, DISABLED Identity исключён. JWT verifier и Direct/Saved HTTP composition проверены, включая реальные A/B из Identity/Profile. Обычные действия используют JWT до exp, без Identity lookup на каждое действие; новые создания/добавления проверяют ACTIVE. |
| MD-N00 | В работе | Открытые eventId/delete/status решения получены; internal lookup version/schemas/examples зафиксированы. Остальные API/event extensions добавляются со своими slices. |
| MD-N02 | Factory/contract и Direct/Saved durable envelopes выполнены | 16 real factory schema cases; outbox.id = eventId. Message и первоначальные envelopes сохраняются одним canonical CAS, repair не меняет event IDs. Broker consumers/publisher остаются MD-N15. |
| MD-N03 | Application и начальный canonical store | Required command_id UUIDv7 одновременно group ID; immutable intent/result. 14 application create tests; реальная Cassandra подтверждает сохранение ID/time после нового adapter instance. Projection recovery остаётся MD-N08. |
| MD-N04 | Application часть выполнена | Immutable edit intent/result, late/no-op replay и fresh membership fence; 18 edit handler tests. Cassandra acceptance остаётся MD-N06/08. |
| MD-N05 | Direct/Saved send boundary проверена, полный scope открыт | Global sender/client key, canonical position/message/envelopes CAS, archive до revision-fenced retirement, bounded work discovery. Real Cassandra подтверждает concurrent writers/replay и unknown outcome; group send/edit/ACK и общий archive/drain остаются открыты. |
| MD-N06 | Частично выполнена | Async create/group membership + Direct/Saved send/read/projection/outbox adapters, V001–V004. 36 real Cassandra + 8 bootstrap integration. Receipt/edit/delete/group send adapters остаются открыты. |
| MD-N07 | Direct/Saved authentication/eligibility подключены | Actor только из JWT sub; signature/claims, spoof/foreign dialog/cursor checks, настоящие A/B из Identity/Profile. Profile batch enrichment остаётся открытым. |
| MD-N08 | Direct/Saved storage/recovery выполнены частично | Durable work hint до acceptance, message/envelopes в одном CAS, history/lookup/cards/sync и archive/retire; холодный repair и lease fencing outbox проверены. Kafka publisher, retry/quarantine policy и остальные mutations ещё открыты. |
| MD-N09 | Базовые Direct/Saved reads подключены | History/point/card/list/sync; signed actor/resource/snapshot/expiry cursors, integer buckets, стабильная history pagination и incremental sync. Group/mutation/receipt extensions и эксплуатационная retention остаются открыты. |
| MD-N10 | Direct/Saved text HTTP выполнен | Production Cassandra composition, JWT, create/send/history/list/sync/point/detail, безопасные 401/404/409/422/503. Group HTTP и mutation endpoints ещё открыты. |
| BASE-09, MD-N11..17, EXT-01..03 | Не закрыты | Full functional/realtime/media/operational gate этим текстовым срезом не закрывается. |

Последний полный Messages run (2026-11-18): **532 unit + 44 integration = 576 passed**;
branch coverage **89.22%**. Quality gate, runtime dependency audit, 20 parent contract
checks, 8 CLI image smoke checks и 9 реальных E2E checks проходят. Полные
Identity/Profile suites в этом этапе не повторялись; их runtime участвует в E2E.
Исторический async этап от 2026-11-17 имел 530 unit / 35 integration и coverage 92%.

E2E артефакты (не публиковать private compose/manifest/keys):

- Исходный красный прогон: `%TEMP%/andruha-identity-e2e-n0c5cupm`, 38/41;
  два повторных automatic-recovery acceptance также красные. Причина нового
  fault injector — защита PID 1 внутри namespace; два прочих падения связаны с
  ожиданием прямой readiness раньше обновления Docker DNS у gateway.
- Зелёный default full run: `%TEMP%/andruha-identity-e2e-e7p57nmm`, 41/41;
  `results-relay-repeat-1.json` и `-2.json`: по 1/1.
- Нестандартные disposable credentials + internal lookup + реальный Messages
  adapter: `%TEMP%/andruha-identity-e2e-cqil0do0`, 5/5 + отдельный pytest 1/1.
- Все три Docker projects очищены своими runners; старые проекты/тома не трогались.

Для непредвиденных E2E-падений пользователь отдельно разрешил исправления
`init: true`, SIGKILL реального worker PID и безопасный GET через gateway в
`wait_ready`; статусы assertions сохранены. Первое красное доказательство
не перезаписано.

Bootstrap integration выдаёт сторонний DeprecationWarning Starlette/AnyIO.
Remote CI не запускался.

## Асинхронный DB этап — 2026-11-17

Все runtime/migration CQL выполняются через execute_async → await. Пользователь
явно разрешил один lifecycle executor только для native connect/shutdown.
Переход проверен с запретом Session.execute в runtime/migration paths,
сохранением прежних fault-injection assertions и async пагинацией.

[DB reference](../database-interactions.md),
[подробности Cassandra](../../services/messages-dialogues-service/docs/database-interactions.md),
[evidence](../verification/andruha-async-cassandra-2026-11-17.json).

## Direct/Saved текст через HTTP — 2026-11-18

Достигнут следующий конкретный результат: зарегистрированные A/B с настоящими
профилями создают один Direct A–B/B–A, отправляют текст без дублей и читают его
через HTTP history/sync. Gateway, Identity/Profile, Messages и Cassandra работают
в изолированном Docker project. Проверены 8 concurrent retries, стабильный
history snapshot при новой отправке, incremental sync, права, Saved и конфликт
одного sender/client ключа между диалогами. Последний образ содержит тот же
runtime source, что и текущий checkout; SHA256 сравнение сохранено в evidence.

Процесс Messages переживает restart. При stop Cassandra live остаётся 200,
readiness и business history дают 503; после start чтение/replay восстанавливаются
без потери идентичности сообщения. Неизвестный исход conditional commit проверен
в реальной БД отдельно: успех возможен только при durable подтверждении.

Первые E2E артефакты сохранены как красные: `andruha-identity-e2e-90dvi_ev`
(устаревший опубликованный порт после restart) и `andruha-identity-e2e-ocjykz8q`
(`NoHostAvailable` ошибочно давал 500). Ожидания отказа БД не ослаблялись.
Зелёный итоговый прогон: `%TEMP%/andruha-identity-e2e-ri7h97ls`, 9/9;
`messages-image-smoke.json`, 8/8. Все созданные этими runners проекты/тома и
отдельная Cassandra для pytest удалены; private configs/keys/logs не публикуются.

[HTTP contract](../contracts/messages-http-v1.md),
[DB reference](../database-interactions.md),
[evidence](../verification/messages-direct-text-2026-11-18.json).

Далее открыты Kafka/WS, group send/edit/delete, receipts/readers, медиа,
retention/очистка, эксплуатационные метрики/readiness остальных ролей и replay
защита. Remote CI, multi-node и TLS/auth Cassandra этим прогоном не проверялись.
Коммитов, push и PR не выполнялось.
