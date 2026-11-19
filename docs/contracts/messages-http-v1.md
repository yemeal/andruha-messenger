# Messages HTTP v1: Direct/Saved text

Messages проверяет Identity RS256 JWT: `typ`, `kid`, issuer, audience, срок и
обязательные claims. Actor равен `sub`. Gateway берёт access cookie и передаёт
внутренний `Authorization: Bearer …`. Бизнес-роль требует
`MESSAGING_ENABLED=true` и реальную Cassandra; без неё business routes дают 503.

| Метод и путь | Запрос / результат |
|---|---|
| `POST /api/v1/dialogues/direct` | `{ "peerId": "uuid" }`; 201 при создании, 200 при повторе. A–B/B–A возвращают один `dialog.dialogId`. |
| `POST /api/v1/dialogues/saved` | Saved текущего пользователя, 201/200. |
| `GET /api/v1/dialogues/` | Карточки, `items`, `nextCursor`; `cursor`, `limit=1..100`, default 50. Порядок первого добавления диалога пользователю, по возрастанию. |
| `GET /api/v1/dialogues/{dialogId}` | Метаданные доступного Direct/Saved. |
| `POST /api/v1/dialogues/{dialogId}/messages` | `{ "clientMessageId": "uuidv7", "text": "Привет" }`; 200 и сохранённое `message`. |
| `GET /api/v1/dialogues/{dialogId}/messages` | История по позиции по возрастанию: `items`, `nextCursor`; `cursor`, `limit`. |
| `GET /api/v1/dialogues/{dialogId}/messages/{messageId}` | Одно сохранённое сообщение. |
| `GET /api/v1/dialogues/sync` | Журнал пользователя: `items`, `cursor`, `hasMore`; `cursor`, `limit`. |

HTTP message содержит `messageId`, `dialogId`, `senderId`, `clientMessageId`,
`text`, `attachmentIds`, `position`, `version`, `sentAt`, `editedAt`, `isEdited`.
Этот HTTP snapshot отделён от существующих Kafka schemas v1. Запрос принимает
только текст. Медиа, edit/delete, receipts и group HTTP добавляются следующими
этапами. OpenAPI доступен на `/openapi.json` Messages.

Новая отправка требует нового `clientMessageId`; retry сохраняет ID и содержимое.
Ключ `(senderId, clientMessageId)` глобален для Direct/Saved. Другой диалог или
содержимое с прежним ключом — `409 send_conflict`. Ответ 200 подтверждает canonical
acceptance, обязательные проекции и durable outbox. Публикация Kafka — будущая
отдельная роль. При 503 клиент повторяет тот же send ID.

Курсор подписан HMAC-SHA256 и привязан к actor, маршруту/ресурсу, порядку,
верхней позиции снимка и сроку 30 дней. Новые позиции после снимка не попадают
в продолжаемую страницу. Чужой/повреждённый cursor — `400 invalid_cursor`;
истёкший — `410 full_resync_required`: запросить снимок без курсора и объединить
данные по ID/version. Смена ключа инвалидирует старые курсоры. Ключ сохраняют
между перезапусками.

Sync включает `dialog.created`, `message.persisted.v1` для sender и
`message.created.v1` для второго участника. Поля записи: `sequence`, `eventId`,
`type`, `dialogId`, nullable `message`. Identity событий сохраняется вместе с
canonical acceptance; repair не генерирует новый event ID. Sync упорядочен по
приёму проекций пользователя; история — по позиции сообщения в диалоге.

Пока `hasMore=true`, читают следующие страницы. Последний `cursor` сохраняют
для последующих incremental запросов, включая пустой ответ. Незавершённая
проекция не продвигает опубликованную границу журнала. Журнал пока без TTL;
очистка относится к эксплуатационному этапу. Список просматривает максимум
четыре buckets на запрос: разреженный индекс может вернуть пустую страницу
с `nextCursor`.

Чужой и отсутствующий dialog/message имеют одинаковый `404 not_found`.
Без достоверного JWT — 401; подставленный `actorId` и неизвестные поля — 422.
Обычная отправка/чтение не вызывает Identity lookup. Readiness бизнес-роли
проверяет Cassandra/schema; live не обращается к БД.
