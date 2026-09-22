<div align="center">

# Andruha Messenger

### Distributed messenger backend built for reliability, security and horizontal scale

Backend мессенджера на микросервисной архитектуре, спроектированный
с акцентом на **распределённость, отказоустойчивость, безопасность
и масштабирование под высокую нагрузку**.

<br>

[![Integration](https://github.com/yemeal/andruha-messenger/actions/workflows/integration.yml/badge.svg)](https://github.com/yemeal/andruha-messenger/actions/workflows/integration.yml)
![Python](https://img.shields.io/badge/Python_3.14-3776AB?logo=python\&logoColor=white)

### Технологический стек:

![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi\&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?logo=pydantic\&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00)
![Alembic](https://img.shields.io/badge/Alembic-6BA81E)
![Dishka](https://img.shields.io/badge/DI-Dishka-blue)

![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql\&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-FF4438?logo=redis\&logoColor=white)
![Kafka](https://img.shields.io/badge/Apache_Kafka-231F20?logo=apachekafka\&logoColor=white)
![Cassandra](https://img.shields.io/badge/Cassandra-1287B1?logo=apachecassandra\&logoColor=white)
![MinIO](https://img.shields.io/badge/MinIO-C72E49?logo=minio\&logoColor=white)
![Elasticsearch](https://img.shields.io/badge/Elasticsearch-005571?logo=elasticsearch\&logoColor=white)

![NGINX](https://img.shields.io/badge/NGINX-009639?logo=nginx\&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker\&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=githubactions\&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-0A9EDC?logo=pytest\&logoColor=white)
![Ruff](https://img.shields.io/badge/Ruff-D7FF64?logo=ruff\&logoColor=black)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
![prek](https://img.shields.io/badge/prek-0.5.3-blue?logo=rust\&logoColor=white)

</div>

---

## О проекте

**Andruha Messenger** — backend распределённого мессенджера, построенный как набор независимо развёртываемых и масштабируемых сервисов.

Архитектура рассчитана на разделение нагрузки между независимыми компонентами, отказ отдельных узлов без остановки всей системы, асинхронную обработку событий и горизонтальное масштабирование наиболее нагруженных частей.

Разные типы данных обслуживаются специализированными хранилищами в зависимости от их access pattern: PostgreSQL используется для транзакционных данных, Cassandra — для сообщений, Redis — для кеширования и ephemeral state, Elasticsearch — для поиска, MinIO — для объектов и медиа.

Внешний трафик разделён между HTTP API, WebSocket-соединениями и загрузкой медиа. Это позволяет масштабировать realtime, API и object delivery независимо друг от друга.

Корневой репозиторий выступает как integration repository и фиксирует совместимые версии сервисов через Git submodules.

---

## Architecture

```mermaid
flowchart LR
    Clients["Web / Mobile Clients"]

    LB["Load Balancer"]
    Gateway["API Gateway"]

    Identity["Auth / Identity Service"]
    Profile["User Profile Service"]
    Messages["Messages & Dialogues Service"]
    Objects["Object Storage Gateway Service"]
    WS["WebSocket Gateway Service"]
    Notifications["Notifications Service"]
    Search["Search Service"]

    Queue["Event Bus / Queue"]

    PG["PostgreSQL"]
    Redis["Redis"]
    Cassandra["Cassandra"]
    MinIO["MinIO"]
    Elastic["Elasticsearch"]

    Clients --> LB --> Gateway

    Gateway --> Identity
    Gateway --> Profile
    Gateway --> Messages
    Gateway --> Objects

    Clients --> WS

    Identity --> PG
    Profile --> PG
    Messages --> Cassandra
    Objects --> MinIO

    Identity --> Redis
    Profile --> Redis
    WS --> Redis

    Identity --> Queue
    Messages --> Queue
    WS --> Queue

    Queue --> Notifications
    Queue --> Search

    Search --> Elastic
````

> Диаграмма показывает логические границы системы. Каждый сервис может масштабироваться независимо в зависимости от характера нагрузки.

---

## Сервисы

| Сервис                                                              | Назначение                                                                 | Статус      |
| -------------------------------------------------------------------- | -------------------------------------------------------------------------- | ----------- |
| [API Gateway](https://github.com/yemeal/andruha-api-gateway)                                  | Внешняя точка входа для HTTP API, маршрутизация и передача auth-контекста  | MVP     |
| [Auth / Identity Service](https://github.com/yemeal/andruha-identity-service)                 | Аутентификация, учётные данные, сессии и жизненный цикл токенов            | **Готов**       |
| [User Profile Service](https://github.com/yemeal/andruha-user-profile-service)                | Профили пользователей, настройки приватности и жизненный цикл профиля      | **Готов**       |
| [Messages & Dialogues Service](https://github.com/yemeal/andruha-messages-dialogues-service)  | Диалоги, хранение сообщений, статусы доставки и прочтения                  | В разработке     |
| [WebSocket Gateway Service](https://github.com/yemeal/andruha-websocket-gateway-service)      | Постоянные realtime-соединения и доставка событий подключённым клиентам    | В разработке     |
| [Object Storage Gateway Service](https://github.com/yemeal/andruha-object-storage-service)    | Загрузка и выдача медиа, метаданные объектов и presigned-доступ             | В разработке     |
| Notifications Service                                                | Доставка push-уведомлений через FCM / APNs                                 | _В планах_ |
| Search Service                                                       | Индексация и поиск по данным мессенджера                                   | _В планах_ |

---

## Архитектурные принципы

### Горизонтальное масштабирование

Прикладные сервисы проектируются **stateless** там, где это возможно, и могут запускаться в нескольких экземплярах за балансировщиками нагрузки.

HTTP API, WebSocket-соединения, обработка медиа и фоновые процессы **масштабируются независимо** друг от друга.

Состояние, которое препятствовало бы горизонтальному масштабированию, вынесено во внешние хранилища и инфраструктурные компоненты.

### Изоляция отказов

Границы сервисов ограничивают влияние отказа одного компонента на остальную систему.

Синхронное взаимодействие используется там, где клиенту требуется немедленный результат. Независимые операции выносятся в асинхронные event-driven процессы.

Для работы в условиях частичных отказов используются:
- таймауты;
- ограниченные retry;
- exponential backoff;
- Circuit Breaker;
- идемпотентность;
- надёжная доставка событий.

### Согласованность данных

Система не использует единую модель согласованности для всех типов данных.

Транзакционные данные хранятся в PostgreSQL, а распределённые процессы используют асинхронную доставку событий и идемпотентную обработку.

`Transactional Outbox` применяется там, где изменение состояния в БД и публикация события должны оставаться согласованными без использования распределённых транзакций.

### Безопасность

Аутентификация, учётные данные и управление сессиями изолированы внутри `Identity Service`.

Внешние точки входа отделены от внутреннего межсервисного взаимодействия, а внутренние сервисы не должны быть напрямую доступны клиентам.

Передача медиа строится через контролируемый object-storage flow и `presigned URL`, поэтому крупные файлы после авторизации могут передаваться без проксирования через прикладные сервисы.

Чувствительные данные, связанные с аутентификацией и replay-защитой, обрабатываются отдельно от обычного прикладного состояния.

### Хранилища под конкретную нагрузку

Технологии хранения выбираются исходя из характера данных и access pattern, а не по принципу одной БД для всей системы:

- **PostgreSQL** — транзакционные и строго согласованные данные;
- **Cassandra** — большие объёмы распределённого хранения сообщений;
- **Redis** — кеши, сессии и краткоживущее координационное состояние;
- **Elasticsearch** — поисковые индексы;
- **MinIO** — бинарные объекты и медиа.

---

## Структура репозитория

```text
andruha-messenger/
│
├── services/
│   ├── api-gateway/
│   ├── identity-service/
│   ├── user-profile-service/
│   ├── messages-dialogues-service/
│   ├── websocket-gateway-service/
│   └── object-storage-service/
│
├── contracts/
├── docs/
├── scripts/
│
├── .github/workflows/
├── docker-compose.yml
├── .env.example
└── README.md
````

Каждый сервис развивается в отдельном репозитории и подключается к интеграционному репозиторию через Git submodules.

Корневой репозиторий фиксирует совместимый набор версий сервисов и содержит общие межсервисные контракты, интеграционную инфраструктуру и документацию уровня системы.

---

## Быстрый запуск

### Требования

* Git
* Docker + Docker Compose
* Python 3.14
* uv
* _OpenSSL (для генерации секретов для [Auth / Identity Service](https://github.com/yemeal/andruha-identity-service))_

### Клонирование

```powershell
git clone --recurse-submodules https://github.com/yemeal/andruha-messenger.git
Set-Location andruha-messenger
Copy-Item .env.example .env
```

Значения из .env.example предназначены исключительно для локальной разработки.


>   Корневой .env содержит конфигурацию интеграционного окружения и используется
    при запуске системы через корневой docker-compose.yml.
    Команда выше не создаёт конфигурацию внутри Git submodules. Каждый сервис имеет
    собственные переменные окружения, секреты и конфигурационные файлы. При запуске
    сервиса отдельно от общей Docker Compose-топологии необходимо настроить его
    окружение согласно README соответствующего сервиса.
    

### Генерация локальных секретов

```powershell
New-Item -ItemType Directory -Force .secrets/identity

openssl genpkey `
  -algorithm RSA `
  -pkeyopt rsa_keygen_bits:2048 `
  -out .secrets/identity/jwt-private.pem

openssl rsa `
  -pubout `
  -in .secrets/identity/jwt-private.pem `
  -out .secrets/identity/jwt-public.pem

openssl rand `
  -out .secrets/identity/replay-v1.key `
  32
```

### Запуск

```powershell
docker compose build
docker compose up -d --wait
```

Проверка готовности:

```powershell
Invoke-WebRequest http://localhost:8080/health/ready
```

Остановка:

```powershell
docker compose down
```

---

## Документация

Архитектурная и инженерная документация уровня системы находится в [`docs/`](docs/).

Инструкции по локальной разработке, конфигурации и запуску конкретных сервисов находятся в их собственных репозиториях.
