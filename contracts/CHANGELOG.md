# Contracts Changelog

Все значимые изменения межсервисных контрактов
фиксируются в этом файле.

## Формат версий

- `MAJOR` - breaking contract changes;
- `MINOR` - backward-compatible additions;
- `PATCH` - исправления документации, examples или schema constraints,
не меняющие wire semantics.

## 1.0.0 — 2026-08-18

### Added
- базовый Kafka event envelope event-envelope.v1;
- контракт identity.user_registered.v1;
- valid fixture для identity.user_registered.v1;
- invalid fixture без payload.user_id;
- invalid fixture с некорректным UUID;
- invalid fixture с неправильным типом поля;
- invalid fixture с запрещёнными credential/PII полями.

### Contract

Kafka topic:

    identity.events.v1

Kafka key:

    user_id

Producer:

    andruha-identity-service

Consumer:

    andruha-user-profile-service