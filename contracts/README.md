# Andruha Messenger Contracts

Этот каталог является source of truth для межсервисных wire-контрактов.

Сервисы не импортируют `contracts/` как runtime Python package.

Каждый сервис хранит собственные transport DTO / Pydantic models и обязан
проверять их совместимость с JSON Schema из этого каталога contract-тестами.

## Формат схем

Все JSON Schema используют:

- JSON Schema Draft 2020-12;
- versioned filenames;
- versioned event names;
- строгую валидацию обязательных полей;
- явную политику `additionalProperties`.

## Версионирование

Major version является частью имени события:

```text
identity.user_registered.v1
message.send.v1
message.created.v1
```

Совместимые изменения внутри одной major version:

- добавление нового optional field;
- расширение допустимого множества значений, если это безопасно для consumers.

**Breaking changes требуют новой major version:**

```text
identity.user_registered.v1
identity.user_registered.v2
```

**Breaking change включает:**

- удаление поля;
- изменение типа;
- изменение смысла поля;
- превращение optional field в required;
- несовместимое изменение структуры payload.

## Event envelope

Все `events` используют **общий** envelope:

```json
{
  "event_id": "019c...",
  "event_type": "identity.user_registered.v1",
  "schema_version": 1,
  "occurred_at": "2026-08-17T10:15:30.123Z",
  "producer": "andruha-identity-service",
  "correlation_id": "019c...",
  "causation_id": "019c...",
  "payload": {}
}
```

**Семантика:**

1. `event_id` - уникальный identity логического события; для repair-публикаций может быть детерминированной;
2. `event_type` - версионированный тип бизнес-события;
3. `schema_version` - major version payload-контракта;
4. `occurred_at` - время возникновения бизнес-события в UTC;
5. `producer` - стабильное имя сервиса, который произвел событие;
6. `correlation_id` - идентификатор всей пользовательской операции;
7. `causation_id` - ID command/event, который вызвал текущее событие
8. `payload` - versioned business payload.

## Тестирование контрактов

Для каждого контракта требуется:

1. валидировать саму JSON Schema;
2. иметь минимум один валидный пример;
3. иметь невалидные фикстуры для критичных нарушений;
4. проверять реальный producer DTO против schema;
5. проверять consumer DTO на valid fixtures;
6. проверять backward compatibility изменений внутри одной major version.