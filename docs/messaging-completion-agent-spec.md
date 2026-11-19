# ТЗ для агента по завершению рабочей переписки Andruha

Версия 1.0 от 18 ноября 2026 года. Подготовлено для агента реализации.
Пользователь подтвердил область ТЗ — все оставшиеся этапы до полного E2E.

Рабочий каталог `C:/Projects/Andruha`. Python-сервисы являются независимыми
Git-репозиториями и подключены как сабмодули. Начни со стартового задания ниже,
затем используй критерии и команды для текущего этапа.

## 1. Команда исполнителю

После поручения на реализацию выполни этапы M0–M6, сохраняя Direct/Saved text flow.
Начни с проверки окружения и текущего Direct/Saved baseline. Первый новый тест
должен проверить восстановление Group create, когда один пользователь уже получил
карточку, а создание карточки другого прервалось. Повтор команды с тем же ID
выдаёт исходный `dialogId`, обе карточки становятся доступны, второй группы нет.
После этого доведи Group send/history/sync до критериев M1 и продолжай по этапам.

Доводи каждый сценарий от команды до результата через реальные адаптеры.
Используй существующие доменные модели, обработчики, порты, механизм принятия
команд, recovery и outbox. Покажи прохождение M6 перед заявлением о полной готовности.

## 2. Цель и конечный результат

Зарегистрированные A/B/C используют Direct, Saved и Group: отправляют текст и
вложения, читают историю, редактируют и удаляют сообщения, управляют группами,
видят delivery/read receipts и всех прочитавших. Два устройства одного
пользователя получают обновления через разные экземпляры WS Gateway.
Reconnect восстанавливает пропущенные изменения через sync.

Повтор команды, потерянный ответ, restart процесса, частичная проекция и отказ
Cassandra/Kafka/Object Storage не создают повторную логическую отправку,
не откатывают более новое состояние и не дают SENT без durable подтверждения.

Итог проверяется на реальных изолированных Identity/Profile, Cassandra, Kafka,
WS Gateway, Object Storage/MinIO и Gateway. Сетевая доставка не подменяется
прямым вызовом handler или заглушкой внешнего сервиса.

## 3. Источники истины и исходное состояние

### 3.1. Обязательные источники

- Рабочие инструкции родителя и каждого изменяемого сервиса. Перед shell-командами
  прочитай `C:/Users/Alex/.codex/RTK.md`. [AGENTS.md родителя](../AGENTS.md)
- [Текущий progress](audits/2026-11-15-readiness-implementation.md) и
  [исходный backlog](audits/2026-11-15-messages-dialogues-backlog.md).
- [Последний Direct/Saved evidence](verification/messages-direct-text-2026-11-18.json).
- [HTTP-контракт](contracts/messages-http-v1.md),
  [Kafka-контракты](../contracts/README.md), schemas/examples в `contracts/`.
- [Messages CONTEXT](../services/messages-dialogues-service/CONTEXT.md),
  [application map](../services/messages-dialogues-service/src/app/application/README.md).
- [ADR-0001](../services/messages-dialogues-service/docs/adr/0001-conditional-group-command-writes.md),
  [ADR-0002](../services/messages-dialogues-service/docs/adr/0002-cassandra-canonical-command-journal.md).
- [Системная карта БД](database-interactions.md),
  [Cassandra runbook](../services/messages-dialogues-service/docs/database-interactions.md),
  [окружение](codex-environment.md).

Для текущего статуса сопоставь код, progress и evidence. Считай исходный audit
историческим снимком. Подтверждённые решения раздела 5 действуют, пока пользователь
их не изменит.

### 3.2. Проверенная при подготовке карта кода

Таблица указывает точки входа для первого чтения кода.

| Граница | Существующая реализация |
|---|---|
| Групповые сценарии | `services/messages-dialogues-service/src/app/application/commands/groups/`: create_group, add_member, remove_member, leave_group, rename, transfer_ownership, change_avatar, remove_avatar, send_message, edit_message, advance_receipt |
| Group persistence contracts | `services/messages-dialogues-service/src/app/application/ports/persistence/repositories/group_commands.py` и `models.py` в родительском persistence package |
| Реальный group adapter | Создание и изменение состава в `services/messages-dialogues-service/src/app/infrastructure/persistence/cassandra/group_commands.py` |
| Direct/Saved persistence | `services/messages-dialogues-service/src/app/infrastructure/persistence/cassandra/messages.py`, `dialogues.py`, `views.py`, `work.py`, `outbox.py`, `records.py` |
| Schema и async CQL | Тот же Cassandra package: `schema/V001__canonical_groups.cql` … `V004__message_projections.cql`, `async_session.py`, `statements.py`, `migrations.py` |
| Composition и HTTP | `services/messages-dialogues-service/src/app/infrastructure/bootstrap/messaging.py`, `src/app/entrypoints/http/main.py`, `routers/dialogues.py`, `errors.py` |
| Read layer | `services/messages-dialogues-service/src/app/application/queries/messages.py`, `dto/reading.py`, `ports/reading.py` |
| Security / events | `services/messages-dialogues-service/src/app/infrastructure/security/`, `src/app/application/events/`, `src/app/application/ports/dto/outbox.py` |
| WS | Каркас в `services/websocket-gateway-service/src/app/entrypoints/websocket/`, `entrypoints/messaging/`, `entrypoints/http/main.py` |
| Медиа | `services/object-storage-service/src/app/`: skeleton, business API и metadata schema отсутствуют |
| Edge | `services/api-gateway/nginx.conf` и `proxy-common.conf`. Gateway переводит access cookie в Authorization. JWT проверяет upstream. |
| Пример Kafka publisher | `services/identity-service/src/app/infrastructure/messaging/kafka_publisher.py`; изучить ACK/error semantics перед переиспользованием подхода |
| Replay protection | `services/identity-service/src/app/infrastructure/security/replay_result_protector.py` и `services/user-profile-service/src/app/infrastructure/idempotency/security/stored_result_protector.py` |
| Пакетное чтение профилей | `services/user-profile-service/src/app/entrypoints/http/routers/profiles.py` и `src/app/application/queries/profiles/get_batch/handler.py` в Profile |
| Проверки | `services/messages-dialogues-service/tests/integration/cassandra/`, `tests/unit/application/groups/`, `contracts/integration/test_messages_factory.py`, `scripts/e2e/run_messages.py`, `scripts/verification/run_messages_checks.py` |

### 3.3. Уже выполнено и требует регрессии

Direct/Saved text HTTP работает с JWT и реальной Cassandra: canonical create,
global send key, последовательные позиции, immutable envelopes, bounded repair,
archive/retire, history/point/list/detail/sync и подписанные cursors.
Реализованы также canonical group creation/membership.

В evidence от 2026-11-18 записаны 532 unit и 44 integration, покрытие 89,22%,
9 E2E проверок и 8 проверок миграций в Docker. Перед реализацией сними новый
baseline в текущем рабочем дереве.

### 3.4. Ограничения, которые нужно учитывать в проектировании

- `CassandraMessages` и `MessagingRuntime` собраны для Direct/Saved; готовой
  общей поддержки Group/send/edit/delete/receipt в них нет.
- `CassandraMessageViews.ensure_for_user` явно отклоняет Group. `_Change`
  типизирован Direct/Saved. History/lookup первоначального send пишутся через
  IF NOT EXISTS: это не version-aware updater для edit/delete.
- Immutable send archive содержит snapshot принятой отправки. После появления
  edit/delete нельзя считать этот snapshot источником текущего Message.
- Group working commands ограничены, но общего archive/drain для них нет.
- WS и Object Storage — отдельная реализация, а не подключение готовых бизнес-API.
- Для version/position/delete и идентификации конкретного group reader нужны
  расширения Kafka schemas. Действующий receipt event v1 содержит `targetUserId`,
  `dialogId`, границу и `statusVersion`.
- User sync может хранить прежние события группы. После удаления участника
  нельзя продолжать выдавать эти private payload только по совпадению actor.
- HTTP list сейчас упорядочен по первому добавлению диалога, по возрастанию.
  Не менять этот опубликованный порядок на activity order скрыто.

## 4. Область изменений и правила исполнения

**RUN-01.** Агент должен сохранять существующие незакоммиченные изменения родителя
и сервисов. Перед изменением каждого сервиса прочитать его инструкции и Git status.
Ошибка доступа к Git metadata не является доказательством чистого checkout.

**RUN-02.** Область этапов включает Messages, WS Gateway, Object Storage, API Gateway,
их контракты, тесты, конфигурацию и документы. Identity/Profile входят в область
расширения контрактов профилей и оставшихся задач BASE-09. Работу в каждом
репозитории начинай в пределах поручения на этот этап.

**RUN-03.** Агент должен соблюдать dependency direction и сохранять бизнес-правила
в domain/application. HTTP, Kafka, WS, CQL, SQL и MinIO остаются в адаптерах.

**RUN-04.** Результат этапа — проверенные незакоммиченные изменения. Commit, push,
создание или публикация PR, deploy и удаление общих данных возможны только по
отдельному прямому поручению пользователя на соответствующее действие.

**RUN-05.** Агент должен применять TDD/pytest по локальным инструкциям. Матрица
приёмки задаёт публичные границы новых тестов после утверждения задания. Для
изменения уже написанного теста и неожиданного падения применяй локальный AGENTS.md.

**RUN-06.** Агент должен использовать текущие locked runtimes и repository helpers.
Новые зависимости/инструменты, если они ещё не разрешены поручением на исполнение,
представить конкретным перечнем до изменения lock/dependency declarations.

Область ограничена backend переписки, указанными изменениями смежных сервисов
и контрактным HTTP/WS клиентом для E2E. Сохраняй выбранные хранилища и текущий
framework идемпотентности. Редизайн frontend, отдельный сервис уведомлений,
production deployment и реорганизация CI требуют отдельного задания.

## 5. Подтверждённые правила и общие инварианты

**INV-01.** Messages должен брать actor из проверенного JWT principal. Client
actor/userId не может изменить авторство. Для Kafka доверенный user scope
формируется WS Gateway и защищён границей producer/internal transport.

**INV-02.** Новое создание Direct/Saved/Group и добавление участника должны проверять
ACTIVE/completed registration в Identity. Обычные действия доверяют действующему
access token до exp без синхронного Identity lookup на каждый запрос. Profile
lifecycle сам по себе не вводит запрет переписки.

**INV-03.** Один `(sender_id, client_message_id)` должен обозначать одну отправку
во всём Messages: Direct, Saved и Group, независимо от даты, restart и транспорта.

**INV-04.** Позиция должна назначаться при canonical acceptance внутри диалога.
Две разные принятые отправки имеют разные последовательные позиции. Replay,
edit/delete и receipts сохраняют исходную позицию сообщения.

**INV-05.** Canonical acceptance должна сохранять материал восстановления и
первоначальные event identities/envelopes в той же атомарной границе, что и
изменение бизнес-состояния. Repair/publish retry не создаёт новый eventId.

**INV-06.** Unknown commit outcome должен разрешаться по durable acceptance.
Недоказанный исход даёт retryable unavailable, а не успех или доказанный CAS conflict.

**INV-07.** Group membership/send/edit/delete/receipt должны использовать одну
общую revision boundary с QUORUM + SERIAL для условной записи. SERIAL reads
должны подтверждать также отсутствие результата на ожидаемой revision.
Replay/no-op проверяют текущие права.

**INV-08.** Старый projector/worker должен быть fenced так, чтобы не откатить
Message version, membership, receipt watermark, activity или опубликованный sync
cursor. Archive должен быть durable до retire working result.

**INV-09.** Recovery и hot reads должны использовать известные partition keys
и ограниченные batches. ALLOW FILTERING, full cluster scans и неограниченный
canonical command log в hot path запрещены.

**INV-10.** Runtime/migration CQL должен идти через execute_async → await.
Согласованное исключение — один lifecycle executor для native connect/shutdown.
Query offload через to_thread и sync pagination не добавляются.

**INV-11.** Изменения должны сохранять существующие domain limits: текст 4096
символов, title 128, attachments 4, группа 1000 участников включая owner.
Источники — `domain/limits.py` и действующие schemas; лимиты не дублировать по handlers.

**INV-12.** Незавершённое восстановление и send identity должны сохраняться
на срок существования соответствующих бизнес-данных. TTL не может разрешить
повторное использование старого send key или потерю accepted work.

Текущая схема использует buckets по 256 позиций и 16 work shards по 256 задач.
User pending head ограничен 256 изменениями и 1 MiB. Лимиты заданы в Cassandra
`limits.py`. Размер bucket и формула shard определяют размещение уже записанных
данных. Для их изменения нужен план миграции и поиска существующих записей.

## 6. Этапы и условия перехода

| Этап | Область | Связь с backlog | Условие завершения |
|---|---|---|---|
| M0 | Контракты, delta plan, воспроизводимый baseline | MD-N00/05/17 | Утверждённые правила отделены от новых контрактов, карта изменений и проверки конкретны |
| M1 | Group text HTTP, состав/метаданные, общие storage/recovery/read paths | MD-N03/05–10/13 частично | A/B/C group flow, exclusion races и cold repair на реальной Cassandra |
| M2 | Edit/delete Direct/Saved/Group | MD-N04/11/12 | Versioned updates/tombstones, late replay, no resurrection |
| M3 | Delivery/read receipts и все readers | MD-N13 | Per-reader monotonic state, pagination и fan-out всем нужным авторам |
| M4 | Kafka roles и WS multi-device | MD-N08/15, EXT-01/03 | Два WS instances, несколько устройств, reconnect и реальные отказы |
| M5 | Object Storage/MinIO и медиа | MD-N14, EXT-02/03 | Upload → finalize → send → authorized download на реальном MinIO |
| M6 | Эксплуатация, replay protection и full gate | BASE-09, MD-N16/17 | Полный E2E, role readiness, metrics, bounded cleanup и финальный evidence |

M1–M3 сохраняют обязательный durable outbox даже до подключения publisher.
Его capacity нельзя временно обходить: переполнение даёт backpressure, а не
удаление старых задач. Операции с аватаром принимаются в M5 на реальном
Object Storage.

### M0. Подготовить исполнимую карту изменений

**PRE-01.** Агент должен снять актуальный baseline перед первым изменением
соответствующего сервиса и обозначить причину каждого падения. M0 начинается с
Messages, родительских контрактов и Direct/Saved E2E. Baseline WS и Object Storage
сними при входе в их этапы.

**PRE-02.** Перед каждым этапом агент должен зафиксировать изменения контрактов
этого этапа. Укажи маршруты, запросы, ответы, события, версии, actor, position,
ошибки и примеры. В M0 достаточно подготовить рабочий контракт M1. Контракты
последующих этапов уточняй к началу соответствующей реализации.

**PRE-03.** Агент должен описать новые запросы и переходы состояния в Cassandra
или PostgreSQL. Укажи partition key, лимит рабочих записей, принятие команды,
архивирование, проверку версии проекции и поиск работы для восстановления.
Добавляй детали перед изменением соответствующей границы хранения.

**PRE-04.** Агент должен определить пределы размера payload, числа рабочих записей,
повторов, времени claim, очередей соединений и пакетов рассылки для текущей роли.
Привяжи значения к действующим доменным лимитам и воспроизводимым проверкам.

**PRE-05.** Агент должен записать migration/compatibility plan для уже существующих
V001–V004 данных, legacy outbox envelopes и persisted cursors. Добавь следующую
версию по актуальному каталогу миграций, сохраняя checksum применённых файлов.

### M1. Групповая текстовая переписка через HTTP

**G-01.** Group create должен использовать stable client command UUIDv7,
совпадающий с group ID, и сохранять immutable intent/result. Retry возвращает
ту же группу. Тот же ID с другим intent даёт conflict.

**G-02.** Текущий участник должен иметь доступ ко всей истории группы, включая
сообщения до вступления. После выхода/исключения он теряет read/send доступ.
Сообщения ушедшего автора остаются историей остальных участников.

**G-03.** Управление должно сохранять существующие правила группы. Текущий участник
может менять название, аватар и состав. Только текущий владелец передаёт владение
другому текущему участнику. Владелец защищён от исключения и перед выходом
передаёт владение.

**G-04.** Group send должен использовать `message_sends` и существующую
согласованную границу `canonical_rows` для всех типов диалогов. Reservation
служит общей привязкой ID. Если после неё состав изменился, повтор проверь на
новой revision. Задача восстановления подтверждает уже принятое сообщение либо
заново проходит проверку текущих прав для ещё не принятого.

**G-05.** Реальный group adapter должен реализовать необходимые membership,
message, metadata/ownership и revision-fence порты. После подтверждения эффектов
архивируй и освобождай рабочие строки, расходующие лимит. Создание может хранить
свой неизменяемый результат в единственной строке состояния группы.

**G-06.** Group projection должна распространять create/membership/metadata/send
изменения в карточки, detail, history и пользовательский sync. Повтор старой
команды не применяет старый состав/preview поверх нового состояния.

**G-07.** Query/replay должен проверять текущие права перед возвратом private
payload, включая старые group creation/membership результаты и ранее адресованные
пользователю записи sync. Immutable DTO/список recipients не доказывает доступ сейчас.

**G-08.** Sync должен доставлять соответствующее контрольное событие выхода/
исключения, не раскрывая после него недоступное содержимое группы. При фильтрации
недоступных payload cursor должен корректно продвигаться без бесконечной пустой страницы.

**G-09.** Fan-out должен сохранять event identities и progress по ограниченным
chunks. Большая группа не должна превращать один запрос или canonical row в
неограниченный список JSON/envelopes. Admission limits не обходятся поднятием
глобальных лимитов без измерения и migration анализа.

**G-10.** Для имени и аватара используй существующий `POST /api/v1/profiles/batch`
с `user_ids` (1–100 ID за запрос) и контекстом зрителя. Переиспользуй видимость
полей из Profile. При outage верни доступные данные диалога со стабильными ID
участников. Права и запись сообщения определяются в Messages.

После теста создания подключи изменения состава и метаданных. Затем добавь
сохранение сообщения с общим ключом и HTTP-выдачу истории и sync. Проверь
отдельными тестами край последнего места в группе, отправку одновременно с
исключением, прежний курсор и повтор команды исключённым участником.

### M2. Редактирование и удаление

**E-01.** Автор доступного сообщения должен редактировать только text, сохраняя
message/send identity, position, createdAt и порядок attachments во всех типах диалогов.

**E-02.** Нормализованно равный text должен быть no-op без новой Message version,
editedAt и edit event. Удаление подписи допускается только при непустых attachments.

**E-03.** Edit command должна иметь stable commandId и immutable intent/result.
Последовательность A → B(cmd1) → C(cmd2) → retry cmd1 не должна менять сохранённый C.
Изменённый intent с прежним commandId должен давать conflict.

**E-04.** Конкурирующие правки должны проверять ожидаемую Message version в
canonical boundary. Проигравшая новая команда получает version conflict.
Replay уже принятой команды сначала распознаёт acceptance, а не применяется заново
только потому, что ожидаемая версия уже устарела.

**E-05.** Send replay после edit должен возвращать текущую редакцию без дубля и
перезаписи text. Различия replay text после реальной правки игнорируются. Диалог,
автор и порядок attachments сохраняются. Отдельные original_text
и fingerprint исходного text для этой replay-проверки не вводятся.

**E-06.** History/point/card/sync должны применять новые версии через условные
version guards и overlay незавершённой canonical mutation. IF NOT EXISTS исходного
send projection не является реализацией обновления сообщения.

**D-01.** Удаление действует для всех. Доступное сообщение может удалить автор,
а в Group также текущий owner. Удаление доступно без временного окна и необратимо.

**D-02.** Delete должен оставлять versioned tombstone с теми же messageId/position
и запрещать дальнейшее редактирование или восстановление содержимого send replay.

**D-03.** Повтор delete должен быть идемпотентен, а прежний commandId с другим
intent должен давать conflict. Состояние и принятие delete сохраняются атомарно.

**D-04.** Старые repair, create/edit events и cached command results не должны
воскрешать tombstone или выдавать удалённый text/attachments через текущие API,
sync и replay. Неизменяемый acceptance — исторический внутренний факт, а не
разрешение вернуть его private body после delete/revocation.

**D-05.** Delete должен обновлять доступные history/list/detail/sync представления,
не сдвигая порядок истории и receipt positions. Общая version после delete
не должна ошибочно означать isEdited=true.

**D-06.** В M2 удаление фиксирует tombstone до каких-либо действий с медиа. В M5
выдача ссылки учитывает tombstone. Физическая очистка в M6 идёт отдельной
операцией и учитывает ссылки из других сообщений и аватаров.

Начни с durable edit на Group и используй ту же семантику для Direct и Saved.
Затем добавь delete с приоритетом tombstone в history и sync. Форму безопасного
ответа на поздний replay зафиксируй в контракте по D-04.

### M3. Доставка, прочтение и список всех readers

**R-01.** Receipt должен приниматься только от текущего участника и только до
сохранённого входящего сообщения соответствующего диалога. ACK собственных
сообщений и ACK в Saved запрещены.

**R-02.** READ должен подразумевать DELIVERED. Повторные/запоздалые ACK не должны
уменьшать watermark, менять identity без основания или создавать новый event для no-op.

**R-03.** Group ACK/replay/no-op должен проверять общую свежую revision вместе с
membership и receipt mutation. После принятого removal нельзя принять ACK по
старому snapshot. Новый участник может прочитать и подтвердить старую историю.

**R-04.** API должен отдавать для сообщения список всех прочитавших с readerId
и однозначной scope statusVersion. Булевы anyRead/allRead и aggregate count
не заменяют readers list. Большой список имеет bounded pagination.

**R-05.** History page должна вычислять статусы bounded чтением watermarks,
без отдельного запроса для каждого сообщения. Reader detail не запускает
сканирование всей истории/всего кластера.

**R-06.** Receipt должен обновлять всех затронутых авторов входящих сообщений
в покрытом диапазоне. Through-message одного автора не может потерять ACK
другого автора в той же группе. Fan-out и recovery должны иметь durable progress.

**R-07.** Receipt updates должны попасть в sync/outbox с сохранённой identity
и per-reader version guard. Новое устройство принимает только актуальную версию.

Сначала подключи ACK в Direct через имеющийся handler, затем Group с общей
revision и выдачей readers. Для M3 достаточно durable результатов, HTTP и
проверки сохранённых событий. Доставка этих событий до устройств проверяется в M4.

### M4. Kafka и WebSocket

Сначала подключи publisher к существующему Cassandra outbox. Затем подключи
consumer к тем же application use cases, которые обслуживают HTTP. После этого
подключи WS Gateway и проверь доставку через два экземпляра. Описание ролей и
реестра соединений есть в [handbook WS](developer-handbook/04-websocket-realtime.md).

**K-01.** Publisher должен публиковать сохранённый envelope с тем же `eventId`
и Kafka key. Перевод в `SUCCESS` допустим после broker ACK и проверки действующей
claim. Потерянный ACK и crash до finalization допускают повтор того же события.

**K-02.** Claim должен использовать уникальный token, срок и CAS. Publisher
должен ограничивать batch, время запроса, backoff и attempts. Терминальный отказ
переходит в наблюдаемый quarantine с возможностью безопасного redrive той же
identity. Просроченный worker не может завершить или перезаписать чужую claim.

**K-03.** Consumer должен валидировать envelope, payload, producer boundary и
соответствие partition key. `message.send.v1` и `receipt.advance.v1` вызывают
общий durable command path. `correlationId` передаётся из команды, `causationId`
для её событий равен `commandId`. Уже принятое через HTTP событие сохраняет
исходный envelope при Kafka replay той же send identity.

**K-04.** Consumer должен подтверждать offset после durable исхода команды и
соблюдения протокола публикации результата, указанного в разделе 8. Повтор после
rebalance или потери offset commit должен использовать первоначальную acceptance.

**K-05.** Постоянный бизнес-отказ команды должен иметь воспроизводимый результат
при повторе. Для send используется `message.rejected.v1`. Таймауты Cassandra,
недоступность зависимостей и unknown commit остаются retryable, без permanent
rejection и ложного SENT.

**K-06.** Неподдерживаемые или невалидные envelopes должны изолироваться в
`<topic>.dlq` после подтверждённой публикации записи установленного формата.
Ограниченный retry/backpressure должен сохранять необработанный offset при
временном отказе. Нельзя коммитить позицию за незавершённой командой в партиции.

**K-07.** Остановка роли и rebalance должны прекращать admission и ограниченно
дожидаться выполняемой работы. Неподтверждённую работу подхватывает следующий
consumer или publisher по сохранённому offset/lease.

**W-01.** WS handshake должен проверять точный Origin allowlist и Identity JWT,
включая аудиторию WS и expiry. Actor соединения берётся из JWT. Истечение токена
прекращает авторизованную работу соединения по описанному WS-протоколу.

**W-02.** WS Gateway должен отправлять `command.accepted.v1` после broker ACK
публикации команды. Клиент получает `SENT` лишь по подтверждённому результату
Messages. Сетевой send в socket сам по себе не продвигает DELIVERED/READ.

**W-03.** Dispatcher должен доставлять событие всем активным соединениям target
user, включая два разных WS instances. Устаревшие маршруты соединений должны
истекать. Рекомендованная топология из handbook использует одну группу dispatcher,
Valkey registry с TTL и каналы экземпляров, затем локальный fan-out.

**W-04.** WS роль должна ограничивать размер входящего frame и глубину очереди
каждого соединения. Переполнение медленного клиента закрывает его соединение
с семантикой reconnect. Остальные соединения продолжают принимать события.

**W-05.** Reconnect должен восстанавливать пропуски из Messages sync. Клиент
дедуплицирует `eventId`, применяет Message version, group revision и per-reader
statusVersion в собственной области. Закрытый socket или downtime Valkey не
уничтожает историю, результаты команд и записи sync.

**W-06.** Realtime передача private payload должна учитывать текущую авторизацию
на группу и текущий Message state. Для отложенных или уже сохранённых legacy
envelopes проверку выполняй перед выдачей либо доставляй безопасный сигнал
перечитать авторизованный sync. Один `targetUserId` из старого envelope не
разрешает отправить удалённый текст или текст бывшему участнику.

**W-07.** API Gateway должен маршрутизировать разрешённые HTTP/WS routes и
сохранять cookie-to-Authorization и request ID policy. Internal routes доступны
только по защищённой межсервисной границе. JWT и domain access проверяют upstream.

Приёмка M4 охватывает две сессии отправителя и получателя на двух WS instances,
ACK broker/offset, publisher lost ACK, poison record, rebalance, slow client и
пропущенный realtime. Во время Kafka outage доступное HTTP-чтение продолжает
работать, а после восстановления sync согласуется с history.

### M5. Object Storage, MinIO и вложения

Реализуй Object Storage как отдельного владельца метаданных и signed tickets.
Используй его PostgreSQL из Compose и приватный bucket MinIO. Messages владеет
ссылкой на объект и проверкой прав по сообщению или группе. Рекомендуемый
жизненный цикл описан в [handbook Object Storage](developer-handbook/05-object-storage.md).

**M-01.** Object Storage должен выдавать upload ticket аутентифицированному
owner. Ticket имеет ограниченный срок, серверный objectId/key и ограничения
purpose, размера, checksum и media type. Бинарные данные идут напрямую в MinIO.

**M-02.** Finalize должен перевести только проверенный объект в READY, сверив
реальные bytes/metadata с ticket. Повтор выдаёт тот же objectId и результат.
Конкурентный finalize, cleanup и неизвестный ответ не создают второй объект и
не меняют уже принятую версию содержимого.

**M-03.** READY descriptor должен ссылаться на неизменяемые bytes даже при
повторном PUT со старым ещё действующим ticket. Подтверждение только `HEAD`
без защиты от последующей перезаписи не удовлетворяет этому требованию.

**M-04.** Private validate-use должен по доверенному service credential проверять
owner/permission, READY и purpose. Attachment и avatar используют разные purpose,
аватар дополнительно требует разрешённый image type. Messages не принимает новый
send или смену аватара при невыясненном результате проверки.

**M-05.** Canonical send должен сохранять immutable snapshot каждого проверенного
вложения, включая `objectId`, `mediaType`, `sizeBytes`, `sha256Base64`, в исходном
порядке. Text+attachments и media-only работают через актуальный wire contract.
Accepted send replay использует сохранённый snapshot при outage Object Storage.

**M-06.** Messages должен выдавать download ticket только после проверки
актуального права на связанное сообщение или аватар. Object Storage должен
проверять service credential и READY. После исключения участника или удаления
сообщения новые tickets недоступны. Политику срока уже выданного presigned URL
зафиксировать до реализации M5.

**M-07.** Изменение или снятие аватара должно обновить Group projections, list и
sync по версии группы. Снятие ссылки оставляет shared bytes под политикой GC.

**M-08.** Object Storage должен ограниченно очищать просроченные незавершённые
загрузки. Cleanup не удаляет финализированные bytes или ссылку, нужную принятому
сообщению. READY purge разрешён после доказанного отсутствия использующих ссылок
и утверждённой политики retention.

Приёмка M5 проходит через Gateway и реальные PostgreSQL/MinIO. Проверить
повтор upload/finalize, некорректные checksum/размер/type, повтор PUT после READY,
object чужого владельца, разные purpose, outage между finalize и send, replay уже
принятого send при outage, скачивание до и после removal и снятие аватара.

### M6. Эксплуатация, защита replay и итоговый E2E

**O-01.** Каждая роль должна проверять в readiness обязательные зависимости
и своё состояние. Liveness показывает состояние процесса и не обращается к БД
или broker. Изменение зависимости подтверждается stop/start в реальном стеке.

**O-02.** Runtime должен давать метрики accepted/rejected/retry, unknown CAS,
repair/consumer lag, outbox age, queue overflow, sync expiry и media failures.
Используй bounded labels, например role/operation/outcome. IDs, текст и имена
файлов не включаются в labels, ошибки и diagnostic logs.

**O-03.** Purge/journal retention должны работать ограниченными batches с
проверяемым watermark. Просроченный или выбывший из retention sync cursor даёт
`410 full_resync_required`. Rebuild возвращает согласованный snapshot и cursor
для продолжения. Новый курсор не может перескочить над пропущенными изменениями.

**O-04.** Identity outbox/reconciler должны сохранять действующие time invariants,
наблюдаемость relay и безопасный bounded redrive/purge. Profile должен отдавать
собственные метрики через принятый exporter. BASE-09 закрывается по сервисам
отдельно и не требует замены общего idempotency pipeline.

**O-05.** Replay результата должен проверять исходного actor, операцию и
актуальное право на раскрытие результата. Для чувствительных сохранённых
ответов определить защиту и lifecycle ключей до включения. Проверить ротацию,
legacy rows и отказ восстановления при повреждении, неверном контексте или
отсутствии нужного ключа. Сохранить уже действующую Identity replay protection.

**O-06.** Документация должна соответствовать runtime. Обнови README, CONTEXT,
application map, contracts, таблицы доступа к БД, runbook, текущий backlog и
evidence. Старый audit сохраняется как исторический снимок.

**O-07.** Итоговый gate должен проверять реальные runtime images с уникальными
keyspaces, schemas, topics/consumer groups, Docker project/volumes и generated
credentials. Fault injection и cleanup используют только ресурсы этого запуска.

**O-08.** Финальный отчёт должен разделять unit, реальные integration, contract,
Docker smoke, E2E и проверки, которые не запускались. Для каждого существенного
acceptance criterion укажи артефакт и результат. Не закрывай карточку с невыполненным AC.

## 7. Данные и согласованность

| Данные | Источник и ключ доступа | Гарантия для реализации |
|---|---|---|
| Диалог, состав, принятие команд | `canonical_rows`, partition `dialog_id` | Один conditional batch сохраняет новую revision, бизнес-результат и durable намерения проекций. Права на групповую команду проверяются на той же revision. |
| Идентичность отправки | `message_sends`, `(sender_id, client_message_id)` | Reservation связывает ключ с одним диалогом и одной операцией. SENT требует принятия внутри canonical partition. Неудавшееся или неизвестное принятие не освобождает ключ до подтверждения безопасного исхода. |
| Working acceptance → archive | Ограниченный working set диалога, затем доступ по `(dialog_id, command_id)` или send key | Archive хранит исходный результат. Удаление working row условно по его identity/revision и подтверждённым эффектам. При stale absence или неизвестном исходе перечитать подтверждение. |
| Текущий Message | History `(dialog_id, position_bucket)` и locator `(dialog_id, message_id)` с рабочим overlay | Version guard защищает edit/delete. Message ID/position остаются стабильными. Tombstone скрывает содержимое во всех пользовательских ответах. |
| Карточки и sync | Бакеты пользователя, ordinal/sequence, дедупликация по identity проекции | Старое событие не отменяет removal/metadata/activity. Продвижение cursor использует последнюю просмотренную sequence при фильтрации. Группа проверяется по canonical membership. |
| Receipts/readers | Watermark в scope `(dialog_id, reader_id)` с общей revision Group; индексы для списка readers/авторов диапазона | Отдельно хранятся позиции DELIVERED/READ и statusVersion. Fan-out возобновляется по сохранённой границе диапазона. |
| Outbox/repair | `work_rows` по известному kind/shard; immutable envelope и claim state по `event_id` | Обнаружение работы независимо от процесса. Полный fan-out более одного batch обрабатывается с durable progress. Переполнение ограничивает admission и сохраняет незавершённую работу. |
| Object Storage | PostgreSQL по `objectId` и `(owner, operation, key)`, private MinIO locator/version | Только подтверждённые bytes получают READY. Backend locator остаётся внутри адаптера. Metadata и привязка к версии объекта неизменяемы после finalize. |

Для группы зафиксируй две границы. Snapshot принятия определяет адресатов и
порядок конкурирующих команд. Каноническое состояние при выдаче определяет право
на раскрытие данных. Сценарий, начатый после подтверждённого removal, обязан
видеть новое состояние. Для запроса, пересёкшегося с removal, зафиксируй точку
согласованной проверки прав и протестируй обе последовательности. Не обещай
отзыв байтов, которые клиент уже получил до изменения прав.

Сохраняй один recoverable план рассылки для большой группы. До первой записи
эффекта конкретному получателю зафиксируй его стабильный ID и содержание события,
чтобы cold repair продолжал с того же места. Приёмка должна пересечь границу
fan-out chunk, включая 1000 участников и переполнение настроенной очереди.

Для полного восстановления клиента берётся согласованная начальная граница sync.
Клиент получает snapshot разрешённых диалогов/истории и дочитывает изменения от
этой границы, сливая данные по ID и версии. Изменения, пришедшие между чтениями
страниц, обнаруживаются курсором. Removal и tombstone применяются при слиянии.

## 8. HTTP, Kafka и WS контракты

Ниже предлагаемые расширения для выполнения M0. Они задают рабочий вариант,
который можно применить в пределах согласованного задания. Существующие контракты
берутся из [HTTP v1](contracts/messages-http-v1.md) и [schemas](../contracts/README.md).
Литеральные имена новых полей и путей фиксируй перед их реализацией по AGENTS.md.

### HTTP

Сохраняй Direct/Saved v1 маршруты, коды и прежние обязательные поля. Поля, которые
изменят закрытую схему, перечисление `kind` или семантику старого ответа, вводи
с явно выбранной версией представления. Зафиксируй поддержку существующего
текстового клиента на сохранённых данных и новых версиях сервисов.

| Этап | Предлагаемая граница | Поля и результат |
|---|---|---|
| M1 | `POST /api/v1/dialogues/groups` | `Idempotency-Key` UUIDv7 и `{title, initialMemberIds}`. Предлагаемый ответ `200` на создание и replay содержит `dialogId` и group summary. В M1 группа создаётся без аватара. |
| M1 | `POST /api/v1/dialogues/{dialogId}/members`, `DELETE /api/v1/dialogues/{dialogId}/members/{userId}`, `POST /api/v1/dialogues/{dialogId}/leave` | Стабильный `Idempotency-Key`, для add — `{userId}`. На успешный leave и его авторизованный replay достаточно результата операции без private group snapshot. |
| M1 | `PATCH /api/v1/dialogues/{dialogId}/group`, `POST /api/v1/dialogues/{dialogId}/ownership` | `Idempotency-Key`, соответственно `{title}` и `{newOwnerId}`. Group state содержит `dialogId`, `kind`, title, owner, участников, group version, `avatarObjectId` и activity. |
| M1–M3 | История, точечное чтение, list и sync под текущим `/api/v1/dialogues/` | Используй действующие resource paths и подпись курсора. Если требуется расширить закрытый v1 ответ, объяви совместимый способ выбора versioned view. Сохраняй порядок по position в history и sequence в sync. |
| M2 | `PATCH` / `DELETE /api/v1/dialogues/{dialogId}/messages/{messageId}` | `Idempotency-Key`, для edit — `{text}` и `If-Match` текущей Message version. Нормализованный intent включает версию для новой edit. Tombstone возвращает stable identity/position/version и delete marker без тела. |
| M3 | `POST /api/v1/dialogues/{dialogId}/receipts`, `GET /api/v1/dialogues/{dialogId}/messages/{messageId}/readers` | `{kind, throughMessageId}`, `Idempotency-Key` где нужен replay результата. Readers — `items` с readerId/statusVersion и подписанный `nextCursor`. |
| M5 | `POST /api/v1/objects/uploads`, `POST /api/v1/objects/{objectId}/finalize` | Owner из JWT и `Idempotency-Key`. В запросе ticket `purpose`, `mediaType`, `sizeBytes`, `sha256Base64`. В ответе objectId, HTTP-метод, URL, обязательные headers и expiry. Finalize возвращает статус и descriptor. |
| M5 | `PUT` и `DELETE` для `/api/v1/dialogues/{dialogId}/avatar`. `GET /api/v1/dialogues/{dialogId}/avatar/download` и `GET /api/v1/dialogues/{dialogId}/messages/{messageId}/attachments/{objectId}/download` | Стабильная identity изменения аватара, `{objectId}` при установке. Messages проверяет действующую ссылку на аватар или конкретное вложение и право участника. |
| M5 | Private `validate-use` и `download-ticket` в Object Storage | Доверенный сервис передаёт actor/owner/intent scope, purpose и object IDs. Точные path/header/schema фиксируются в M0 и не выводятся наружу через Gateway. |

Коды ответа согласуются с текущим HTTP API. Нет валидного JWT — `401`.
Отсутствующий или недоступный dialog/message — одинаковый безопасный `404`.
Значимое запрещённое действие
в доступном ресурсе получает стабильную доменную ошибку. Intent/send conflict
— `409`. Для нового edit с устаревшим `If-Match` предлагается `412`. Неизвестные
поля/невалидная команда — `422`. Неподтверждённый результат — `503` со смыслом
«повторить то же действие с тем же ID». Курсоры сохраняют действующие `400` и
`410`. Права на выдачу immutable replay result проверяются при каждой выдаче.

### Kafka

- `messaging.commands.v1` использует `dialogId` как partition key, `payload.userId`
  устанавливает доверенный WS producer. Имя producer в JSON само по себе
  не удостоверяет происхождение. Разграничение producer/consumer прав и
  network boundary документируются в конфигурации роли.
- `messaging.events.v1` использует `targetUserId` как key. Direct/Saved v1 send
  envelopes сохраняют существующие поля и поведение. Kafka ordering действует
  в пределах партиции. Клиентское состояние упорядочивается Message position/version,
  group revision и reader statusVersion.
- Для edit/delete, group lifecycle и reader-aware receipts добавь versioned types
  и примеры. Для `message.created/persisted` с новым несовместимым snapshot
  объяви новую версию. Старые envelopes остаются читаемыми и валидными. При
  сосуществовании версий тестируй, что один logical change применяется один раз.
- События, порождённые новой Kafka command, сохраняют её correlation/causation.
  `causationId` отсутствует у допустимой root-операции без причины. Отсутствие
  поля не заменяется `null`. Single logical event сохраняет исходный envelope.
- Предлагаемый протокол offset для M4 требует durable command acceptance или
  durable business rejection, затем broker ACK применимого результата. При
  успешном no-op проверь отсутствие незавершённого эффекта исходной команды.
  Отдельные publisher и consumer используют общее сохранённое состояние
  подтверждения. Временная недоступность оставляет offset для retry. Для
  invalid envelope аналогичная граница — broker ACK записи в DLQ.
- В `dlq-envelope.v1` исходная запись обязательна в `originalValueBase64`.
  Ограничь доступ и срок хранения DLQ и сохраняй документированный redrive.
  Диагностические поля содержат стабильные коды. Логи и метрики исключают
  оригинальную запись, текст и credentials.

### WebSocket

Используй существующий edge `/ws`. Начальный вариант протокола берёт из handbook
`connection.ready.v1` и `command.accepted.v1`; client frame не содержит actor.
Задай схемы для frame/errors, heartbeat и expiry, поведение reconnect и клиентское
слияние версий. Пропуск ephemeral fan-out допустим при сохранённом recoverable
sync. Запрещено коммитить permanent business ACK для незавершённой durable команды.

## 9. Развёртывание и эксплуатационные границы

| Роль | Зависимости readiness |
|---|---|
| Messages HTTP/sync | Cassandra/schema и валидная локальная auth/cursor config. Для текстового чтения достаточны эти зависимости. Identity lookup нужен при создании и добавлении участников. |
| Messages repair | Cassandra/schema и активный repair loop. Readiness должна отличать неработающий loop от обычного пустого work queue. |
| Messages Kafka consumer/publisher | Cassandra/schema, соответствующая Kafka операция и работоспособный lifecycle роли. |
| WS server / dispatcher | WS server проверяет JWT config, registry и producer path. Dispatcher проверяет consumer и Valkey routing. |
| Object Storage | PostgreSQL/schema, приватный MinIO bucket и пригодная конфигурация подписания. |
| Gateway / Identity / Profile | Gateway проверяет свой routing smoke. Identity/Profile сохраняют свои проверки readiness с нужными зависимостями роли. |

Новую схему вноси добавочными migration files. Докажи clean install и upgrade
из предыдущей схемы с сохранёнными данными. Проверь незавершённые legacy work
rows, send reservations, outbox и cursor. Если дорожка требует backfill,
предусмотри возобновляемую обработку с checkpoint. Откат приложения должен
сохранять принятые данные. Destructive down проверяется только на изолированной
схеме и выполняется над общими данными по отдельному решению.

## 10. Матрица приёмки

Для каждого сценария сохрани команду, результат и идентификатор артефакта.
Заявление о прохождении по этой таблице требует фактического запуска указанной
проверки. Сценарии проверяют публичный результат, а доступ к состоянию БД служит
дополнительным доказательством атомарности и восстановления.

| Критерий | Требования | Сценарий и наблюдаемый результат | Проверка и evidence |
|---|---|---|---|
| AC-00 | RUN-01–RUN-06, PRE-01–PRE-05 | Для M1 снят актуальный baseline, определены границы хранения и контракты. Последующие этапы уточняют свои изменения при входе. Существующие правки сохранены. | Git status/diff, документы M0, результаты исходных проверок. |
| AC-01 | G-01, G-06, INV-01, INV-02 | A создаёт группу с B/C. Потерянный ответ, частичная карточка и restart дают одну группу с тем же ID. Прежний key с другим intent отклонён. Незавершённый аккаунт и подставленный actor отклонены. | Real Identity/Profile + HTTP и Cassandra, отчёт восстановления. |
| AC-02 | G-02, G-03, G-05, G-06, G-07, G-08, INV-07 | Вступивший C видит прежнюю историю. После removal C получает одинаковый 404 для закрытого/отсутствующего ресурса, не видит карточку или private sync/replay. B видит тексты C. Проверены rename, add/remove, ownership, leave, невозможность удалить owner. | HTTP E2E и real-Cassandra race tests, включая прежние cursors и потерянные ответы. |
| AC-03 | G-04, G-05, INV-03, INV-04, INV-06, INV-07 | Конкурентные отправки получают последовательные позиции. Один send key между тремя типами диалогов имеет одного победителя после restart и смены месяца. Send/removal и два претендента на последнее место дают допустимый порядок CAS. Чтение отсутствующей записи по устаревшей revision выявляет конфликт. | Реальная Cassandra с барьерами, повтором того же ID и проверкой обоих исходов потери ответа LWT. |
| AC-04 | G-05, G-06, G-09, INV-05, INV-08–INV-12 | Cold restart после canonical LWT, между проекциями и перед retire не теряет эффект. Количество working rows ограничено. Группа до 1000 проходит несколько chunks. Исчерпание capacity даёт backpressure, ожидающие операции сохраняются. | Изолированная Cassandra, fault injection, повтор envelope ID/payload, проверка bounds и выборок по ключам. |
| AC-05 | G-02, G-06, G-08, G-10, INV-09 | История пересекает position bucket, новый send не попадает в прежний snapshot. Чужой курсор отклонён. List и sync продвигаются через отфильтрованную страницу. При недоступном Profile возвращаются ID вместо недоступных имён и аватаров. | Реальные HTTP, Cassandra, Profile. Проверка видимости полей и количества запросов на страницу. |
| AC-06 | E-01–E-06, INV-07, INV-08 | Во всех типах диалогов edit сохраняет identity/position. Равный текст не меняет версию. Две concurrent edits дают version conflict. Поздний retry возвращает допустимый исход cmd1 без отката cmd2. Send replay читает текущий текст. | Domain/handler unit, real-Cassandra edit/removal и HTTP history/point/sync. |
| AC-07 | D-01–D-06, INV-08 | Автор и текущий owner группы удаляют с сохранением tombstone. Остальные получают отказ. Повтор, поздний edit/send replay и старое восстановление не возвращают удалённое тело. Общая version не подменяет isEdited. | Unit, Cassandra/HTTP integration и восстановление. Доступ к медиа и GC принимаются в AC-11/AC-12. |
| AC-08 | R-01–R-07, INV-07, INV-09 | READ включает DELIVERED. Прежний ACK сохраняет границы, Saved/own/nonmember отклонены. При чтении диапазона с сообщениями двух авторов событие сохраняется для каждого. Readers list содержит всех прочитавших и поддерживает cursor. | Реальная Cassandra и HTTP с доказательством ограничения количества чтений. Доставка events проверяется в AC-09/AC-10. |
| AC-09 | K-01–K-07, INV-05, INV-06 | Accepted/rejected/invalid имеют нужный durable исход. Lost broker ACK и rebalance повторяют тот же logical effect. Poison запись уходит в DLQ, временный outage не коммитит offset и не создаёт business rejection. Stale claim token не завершает чужую работу. | Kafka + Cassandra integration, снятые ACK/offset/event identity и sanitation evidence. |
| AC-10 | W-01–W-07, INV-01 | Вход разрешён для валидного JWT/Origin. `command.accepted` приходит после broker ACK. Два устройства на разных WS instances получают свои события и дочитывают пропуски через sync. Остальные клиенты переживают отключение slow client. Задержанное событие не выдаёт недоступное тело. | Реальный Gateway, два WS instances, Kafka + Valkey; проверка expiry, отказа и reconnect. |
| AC-11 | M-01–M-08, D-06 | Upload/PUT/finalize/send/download работает для текста с медиа, media-only и аватара. Ошибочные checksum/type/purpose/owner отклонены. Старый PUT не меняет READY bytes. Removal/delete запрещают новый ticket, незавершённый upload очищается без потери READY. | Реальный PostgreSQL + MinIO + Messages, retry/restart/fault tests. |
| AC-12 | O-01–O-04, INV-09, INV-12 | Stop/start зависимостей отражается в readiness нужной роли. Read HTTP выдерживает Kafka outage. Bounded cleanup не теряет pending work, старый sync cursor даёт 410, rebuild не оставляет gap. Метрики/логи безопасны. | Изолированные smoke/ops tests с искусственным временем и данными, dependency matrix. |
| AC-13 | O-05, G-07, D-04 | Replay выдаётся исходному авторизованному actor. Неверный контекст/ключ и повреждённый envelope не раскрывают payload. Ротация читает допустимые старые результаты. Legacy policy реализована согласно решению. | Unit/integration соответствующего сервиса с временными ключами и тестами rolling upgrade. |
| AC-14 | O-06–O-08, PRE-05, RUN-04 | Полный реальный E2E, clean/upgrade migrations и локальные quality/security checks выполнены. Отчёт подтверждает scope, проверки и изоляцию. | Итоговый JSON/Markdown evidence с командами, HEAD/image IDs, migrations, counts и cleanup. |

Финальная последовательность AC-14 включает A/B/C с реальной регистрацией и
профилями, один Direct A–B, Saved только владельца, группу с передачей ownership
и выходом, текст и медиа без дублей, edit/delete/readers, историю через границу
bucket, два устройства и два WS instances. Повтори критичные операции при
restart Messages/consumer, Cassandra/Kafka/Valkey/MinIO outage, lost LWT/broker
response и частичной проекции. Для отказов проверяй сохранённое состояние после
восстановления. Простого успешного HTTP status до сбоя недостаточно.

## 11. Команды и порядок проверки

Используй Python 3.14, локальные uv environments, Docker Linux containers и
изолированные credentials. Команды ниже соответствуют существующим helpers
и текущему CI. В новом checkout сначала проверь состояние окружения. Для source
checks, которым нужны зависимости, используй locked окружение сервиса.

Базовые проверки из `C:/Projects/Andruha` после чтения RTK и инструкций сервиса.
Если `check-tools` выявит отсутствие `.venv`, используй `setup` из того же helper
в соответствии с [инструкцией окружения](codex-environment.md).

```powershell
rtk proxy git status --short --branch
rtk proxy git -C services/messages-dialogues-service status --short --branch
rtk proxy python scripts/codex-service.py messages-dialogues-service check-tools
rtk proxy python scripts/codex-service.py messages-dialogues-service unit
rtk proxy python scripts/codex-service.py messages-dialogues-service lint
rtk proxy python scripts/verification/run_messages_checks.py
```

Runner Cassandra передаёт аргументы `uv run pytest` в каталоге Messages.
Совмещённое покрытие ветвей и проверка Compose из корня проекта.

```powershell
rtk proxy python scripts/verification/run_messages_checks.py tests/unit tests/integration -q --cov=app --cov-branch
rtk proxy docker compose -f docker-compose.yml config --quiet
```

Проверки общих схем и сериализации EventFactory выполняются из
`C:/Projects/Andruha/services/messages-dialogues-service`.

```powershell
rtk proxy uv run python -m unittest discover -s ../../contracts/tests -v
rtk proxy uv run pytest -c pyproject.toml ../../contracts/integration -q
```

Сетевой регрессионный тест Direct/Saved из
`C:/Projects/Andruha/services/identity-service`.

```powershell
rtk proxy uv run python ../../scripts/e2e/run_messages.py
```

Для M1 и следующих этапов расширь или добавь проверку на этой границе с учётом
AGENTS.md и сохранением исходных assertions. Групповые и поздние E2E-команды
задокументируй вместе с реализацией. Существующий runner подтверждает исходный
Direct/Saved scope, а новые сценарии появляются вместе с кодом.

Перед закрытием каждого этапа выполни его целевые проверки и необходимые
quality gates из актуального CI затронутых репозиториев. Для Python это lint,
format, ty, lock, unit/real integration, branch coverage по `COVERAGE_MIN` и
аудит runtime dependencies. Для изменений Gateway проверь `nginx -t` при сборке
образа и запусти сетевой smoke маршрутов. Для миграций Messages запускай
`services/messages-dialogues-service/scripts/smoke_cassandra.py` с аргументом
`--image` для проверяемого образа. Скрипт исходно ожидает V001–V004. Обновление
ожиданий под новую миграцию подчиняется правилам изменения существующих проверок.

Если sandbox, недоступная сеть или Docker блокируют проверку, укажи команду,
конкретную ошибку и доступную альтернативную проверку. Для зависимых критериев
оставь статус «не проверено» до реального запуска. Не запускай удалённый CI
через публикацию изменений без отдельно выданного поручения.

## 12. Решения по мере реализации и условия остановки

| Когда | Что уточнить | Рабочий вариант и граница решения |
|---|---|---|
| M0 → M1 | Совместимость group list/sync и новые management DTO | Сохраняй существующее представление для старого клиента. Объяви расширенный view и новые маршруты в OpenAPI с contract tests. Основа — таблица раздела 8. |
| M2 | Tombstone в API и поздний replay с приватным содержимым | Возвращай безопасный tombstone/результат операции без удалённого payload. Согласуй стабильные ошибки и способ версионирования до открытия endpoint. |
| M3 | Исторические readers после выхода, viewer privacy | Рабочий вариант сохраняет факт прочтения в истории текущих участников, лишая вышедшего доступа к query и новым ACK. Уточни политику выдачи reader identity, если действующий контракт требует другой scope. |
| M4 | Version negotiation WS, Kafka ACL и retry/quarantine config | Используй текущие topic keys и handbook topology. Конкретизацию frame versions, права ролей и limits согласуй на границе transport. Для исключённого участника безопасный вариант — сигнал без закрытого содержимого и повторная проверка через sync. |
| M5 | Allowlist, limits, TTL и уже выданный URL | Базовый проект handbook задаёт 25 MiB на attachment, 5 MiB на avatar, 10 мин upload и 5 мин download. Зафиксируй values, поддерживаемые типы и проверяемое правило срока ссылки в контракте M5. Уже выданный URL действует до expiry при обычной presigned схеме. Для требования немедленного отзыва нужен отдельный механизм. |
| M6 | Retention окон и legacy replay данных | Текущий курсор действует 30 дней. Перед включением purge укажи отдельную политику хранения данных и watermark. Для чувствительного Profile replay изучи подключение имеющегося AES-GCM protector и опиши обработку старых записей и ротацию. |

После поручения на исполнение применяй согласованные правила и решай обратимые
детали в рамках этапа. Для изменения публичных контрактов, схем, зависимостей
и существующих проверок используй порядок актуального AGENTS.md. Если найдено
противоречие, способное поменять права, идемпотентность, совместимость или данные,
подготовь конкретный delta, последствия и проверку. Согласуй затронутую границу,
продолжая независимую работу. Сроки и production SLO в этом ТЗ не установлены.

## 13. Что передать после реализации

- Локальные изменения в соответствующих репозиториях, versioned migrations и
  repeatable setup для изолированного тестового стека.
- Актуальные OpenAPI/JSON schemas и валидные/невалидные примеры. Contract tests
  проверяют реальные DTO producer/consumer и старые версии.
- Runbook с roles/config, схемой доступа к БД и recovery/roll forward, командами
  E2E и проверяемой политикой retention, redrive и replay keys.
- Сводку M0–M6 с evidence для AC-00…AC-14. Укажи изменения, команды, реальные
  зависимости, число тестов, покрытие, версии, HEAD и образы, проверки отказов,
  очистку и оставшиеся причины незакрытых карточек.
