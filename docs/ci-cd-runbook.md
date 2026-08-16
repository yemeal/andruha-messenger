# CI/CD для Andruha Messenger: воспроизводимый план и runbook

**Статус:** baseline реализован; CI всех семи репозиториев подтверждён на GitHub

**Дата актуализации:** 2026-08-17
**Область:** `andruha-messenger` и шесть сервисных репозиториев

## 1. Что реализовано

После публикации текущих workflow каждый pull request будет автоматически
проверяться до слияния в `main`:

1. зависимости воспроизводимо устанавливаются из lock-файла;
2. Ruff проверяет стиль, импорты и форматирование;
3. Pyright проверяет production-код в строгом режиме;
4. unit- и integration-тесты выполняются раздельными шагами;
5. суммарное branch coverage приложения должно быть не ниже 80%;
6. `pip-audit` проверяет runtime-зависимости на известные уязвимости;
7. secret scanner проверяет историю и содержимое репозитория;
8. Docker-образ собирается только после успешных проверок;
9. проверки миграций и контрактов подключаются только там, где уже есть
   реальные миграции и контракты;
10. релизный тег может публиковать проверенный образ в GHCR.

Автоматический деплой приложения в staging или production в этот план не
входит. Для него сначала нужно выбрать платформу размещения, окружения,
стратегию миграций, health gates и способ отката.

## 2. Текущее состояние и важная граница

На момент актуализации документа:

- пять Python-сервисов имеют runtime/development dependencies и собственный
  `poetry.lock`;
- каждый Python-сервис содержит 48 unit и 8 integration tests;
- Ruff, Pyright strict, tests, coverage и `pip-audit` локально проходят на
  Python 3.14;
- итоговое branch coverage каждого Python-сервиса равно 100% для текущего
  operational skeleton при обязательном gate 80%;
- шесть Docker images собираются, `nginx -t` проходит, app-only Compose stack
  достигает healthy для 6/6 контейнеров;
- `ci.yml` и `release.yml` созданы во всех сервисных репозиториях;
- root workflow проверяет submodules, Compose build и app-only smoke test;
- Gitleaks локально проверил историю всех семи репозиториев и текущее дерево;
- Alembic и миграции по-прежнему отсутствуют;
- `contracts/` по-прежнему не содержит OpenAPI, AsyncAPI или схем событий;
- все семь GitHub-репозиториев публичные, используют default branch `main`,
  GitHub Actions включены;
- GitHub Secret scanning и Push protection подтверждены как enabled во всех
  семи репозиториях;
- CI workflow всех шести сервисов успешно выполнились на GitHub 2026-08-17;
- root Integration успешно выполнил Secret scan и Compose build/smoke на
  GitHub 2026-08-17;
- rulesets пока отсутствуют.

Baseline нельзя упрощать через `continue-on-error`, `|| true` вокруг проверок
или пустые тесты. Best-effort `|| true` разрешён только в cleanup, например при
остановке уже завершившегося disposable container.

## 3. Разница между CI, delivery и deployment

| Термин | Что означает в проекте |
|---|---|
| CI | Проверка каждого PR и каждого изменения `main`: lint, types, tests, audit, Docker build |
| Continuous Delivery | Публикация неизменяемого Docker-образа в GHCR по релизному тегу |
| Continuous Deployment | Автоматическая установка образа в конкретное окружение; пока не проектируется |

## 4. Почему workflow нужен в каждом репозитории

Сервисы подключены к главному репозиторию как Git submodules. Изменение внутри
`andruha-identity-service` само по себе не запускает workflow репозитория
`andruha-messenger`. GitHub видит их как разные проекты с разной историей.

Реализованная структура:

```text
andruha-messenger/
└── .github/workflows/
    └── integration.yml         # Compose и согласованный набор submodules

каждый Python-сервис/
└── .github/workflows/
    ├── ci.yml                  # quality, tests, security, Docker smoke
    └── release.yml             # публикует образ по тегу после повторной проверки

andruha-api-gateway/
└── .github/workflows/
    ├── ci.yml                  # nginx -t, smoke test, secret scan, Docker build
    └── release.yml             # публикует gateway image по тегу
```

На bootstrap-этапе пять Python workflows намеренно самодостаточны: они начнут
работать сразу после публикации каждого сервиса и не зависят от ещё не
опубликованного root commit. Каждый `ci.yml` поддерживает `workflow_call`,
поэтому локальный `release.yml` повторно запускает тот же pipeline.

После первого стабильного GitHub run копии можно вынести в public reusable
workflow. Сервисы должны ссылаться на него только по полному commit SHA, а не
по `@main`.

## 5. Общий граф проверок Python-сервиса

```text
checkout
   |
   v
dependency-integrity
   |
   +----------+------------+-------------+
   |          |            |             |
   v          v            v             v
ruff       pyright      unit+integration  security
                             |             |
                             v             v
                         coverage >= 80  pip-audit + secrets
   |          |            |             |
   +----------+------------+-------------+
                         |
                         v
                    docker build
                         |
                         v
              publish only for release tag
```

Docker build зависит от всех обязательных проверок. Если хотя бы одна проверка
неуспешна, образ не публикуется.

## 6. Предварительные требования

### 6.1 Локальная машина

Нужны:

- Git;
- Python 3.14;
- Poetry той же версии, что закреплена в Dockerfile и workflow;
- актуальный Node.js LTS и npm для официального CLI Pyright;
- Docker Engine или Docker Desktop;
- `gh` CLI только для настройки GitHub и проверки Actions; сами локальные
  проверки от него не зависят.

Проверка инструментов:

```powershell
git --version
py -3.14 --version
poetry --version
node --version
npm --version
docker version
docker compose version
gh auth status
```

Если команда не проходит, следующий шаг не нужно имитировать другой версией.
Сначала восстанавливается требуемый инструмент.

### 6.2 GitHub

Для каждого из семи публичных репозиториев нужны:

- включённые GitHub Actions;
- Secret scanning и Push protection;
- разрешение использовать actions и reusable workflows из публичных
  репозиториев;
- ruleset для ветки `main` с обязательными CI status checks;
- `GITHUB_TOKEN` с `contents: read` для CI и с `packages: write` только для
  release workflow.

Не нужно создавать отдельный PAT для публикации образа из Actions: связанный с
репозиторием пакет в GHCR публикуется через штатный `GITHUB_TOKEN`.

## 7. Dependency bootstrap пяти Python-сервисов

Этот раздел выполняется отдельно в каждом из репозиториев:

- `andruha-identity-service`;
- `andruha-user-profile-service`;
- `andruha-messages-dialogues-service`;
- `andruha-websocket-gateway-service`;
- `andruha-object-storage-service`.

### Шаг 1. Перейти в сервис

Пример для Identity:

```powershell
Set-Location C:\Projects\Andruha\services\identity-service
```

Все следующие команды выполняются из корня выбранного сервисного репозитория.

### Шаг 2. Объявить runtime-зависимости

Текущий код непосредственно импортирует FastAPI, Starlette и Structlog, а
Docker запускает Uvicorn. Эти пакеты должны быть прямыми зависимостями:

```powershell
poetry add fastapi starlette structlog uvicorn
```

На этом шаге Poetry подбирает версии, совместимые с Python 3.14. Результат
фиксируется в `pyproject.toml` и `poetry.lock`. До commit нужно проверить
release notes выбранных версий и убедиться, что Starlette не конфликтует с
диапазоном, который требует FastAPI.

### Шаг 3. Объявить development-зависимости

```powershell
poetry add --group dev ruff pytest pytest-asyncio pytest-cov httpx2 pip-audit
```

Назначение:

| Пакет | Зачем нужен |
|---|---|
| Ruff | lint, сортировка импортов и форматирование |
| pytest | test runner |
| pytest-asyncio | прямые async-тесты ASGI-компонентов |
| pytest-cov | сбор line и branch coverage |
| HTTPX2 | поддерживаемый Starlette transport для TestClient и прямых ASGI-запросов |
| pip-audit | аудит известных уязвимостей Python-зависимостей |

Pyright не добавляется как Python-пакет. Официальный Pyright CLI работает через
Node.js/npm; в workflow закрепляется точная npm-версия.

### Шаг 4. Создать и проверить lock-файл

```powershell
poetry lock
poetry check --lock
poetry sync --with dev --no-root
```

Ожидаемый результат:

- `poetry.lock` создан и добавляется в Git;
- `poetry check --lock` не сообщает, что lock-файл расходится с
  `pyproject.toml`;
- установка не меняет lock-файл;
- `.venv/` остаётся проигнорированной и не попадает в Git.

CI никогда не должен выполнять `poetry update`: эта команда пересчитывает
версии и разрушает воспроизводимость проверки конкретного commit.

## 8. Единая конфигурация качества в `pyproject.toml`

Ниже базовая конфигурация для каждого Python-сервиса. Она добавляется после
dependency bootstrap и затем изменяется только осознанно через PR.

```toml
[tool.ruff]
target-version = "py314"
line-length = 88
src = ["src", "tests"]

[tool.ruff.lint]
select = [
    "E4",
    "E7",
    "E9",
    "F",
    "I",
    "B",
    "SIM",
    "UP",
    "RUF",
]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
line-ending = "lf"

[tool.pyright]
include = ["src"]
exclude = ["**/__pycache__"]
pythonVersion = "3.14"
typeCheckingMode = "strict"
venvPath = "."
venv = ".venv"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
addopts = [
    "-ra",
    "--strict-config",
    "--strict-markers",
]
markers = [
    "integration: test that crosses an application or adapter boundary",
]

[tool.coverage.run]
branch = true
source = ["app"]

[tool.coverage.report]
fail_under = 80
show_missing = true
skip_covered = true
```

Почему выбран один type checker: параллельное использование Pyright и mypy
создаёт две конфигурации, два набора исключений и часто дублирующиеся сообщения.
Для greenfield-кода используется один Pyright в `strict`-режиме. Mypy следует
добавлять только при появлении конкретной зависимости или плагина, который
проверяется именно им.

## 9. Тесты, которые нужны уже для текущего skeleton

Порог 80% достигается тестированием поведения, а не пустыми тестами или
исключением основных модулей из coverage.

### 9.1 Общие unit-тесты пяти Python-сервисов

Минимальный полезный набор:

1. `core/settings.py`:
   - значения по умолчанию;
   - все допустимые варианты `DEV_LOGS`;
   - ошибка для неизвестного boolean-значения;
   - допустимые границы порта `1` и `65535`;
   - ошибки для `0`, `65536` и нечислового значения;
   - очистка и разбор `MUTE_LOGGERS`;
   - очистка cache `get_settings.cache_clear()` между тестами.
2. `core/logging.py`:
   - корректный уровень логирования;
   - ошибка для неизвестного `LOG_LEVEL`;
   - добавление service/version/environment в событие;
   - отсутствие чувствительных HTTP-заголовков в создаваемом контексте.
3. `request_id_policy.py`:
   - безопасный входной ID сохраняется;
   - отсутствующий, слишком длинный или содержащий пробелы ID заменяется;
   - ошибка, если пользовательский generator вернул небезопасное значение;
   - ошибка при `max_length < 1`.
4. `request_lifecycle.py`:
   - нормальный переход response state;
   - повторный `http.response.start` отвергается;
   - status `5xx` помечает запрос как failed;
   - client disconnect и failure корректно сохраняются;
   - request context очищается и после успеха, и после исключения.
5. `request_id.py`:
   - non-HTTP ASGI scope передаётся без HTTP-обработки;
   - единственный корректный заголовок принимается;
   - дублирующиеся заголовки не считаются доверенным ID;
   - response всегда содержит ровно один `X-Request-Id`;
   - исключение до начала ответа превращается в безопасный JSON `500`;
   - исключение после начала ответа не создаёт второй response;
   - отсутствие response start считается ошибкой;
   - disconnect не скрывается;
   - lifecycle observer получает started/failed/finished события.

### 9.2 Общие integration-тесты пяти Python-сервисов

Для каждого `create_app`:

1. `GET /health/live` возвращает `200` и `{"status":"ok"}`;
2. `GET /health/ready` внутри lifespan возвращает `200` и
   `{"status":"ready"}`;
3. до старта lifespan readiness равна `503` — это проверяется на отдельном
   приложении без активированного lifespan;
4. прямой запрос получает сгенерированный `X-Request-Id`;
5. корректный внутренний `X-Request-Id` возвращается без изменения;
6. небезопасный или продублированный ID заменяется;
7. `404` также содержит request ID;
8. тестовый endpoint, выбрасывающий исключение до response start, получает
   безопасный `500` без деталей исключения и с request ID.

Тестовый error endpoint создаётся только внутри теста. Добавлять его в
production router нельзя.

### 9.3 Как запускать unit, integration и общий coverage gate

```powershell
poetry run coverage erase

poetry run pytest tests/unit `
  --cov=app `
  --cov-branch `
  --cov-report=

poetry run pytest tests/integration `
  --cov=app `
  --cov-branch `
  --cov-append `
  --cov-report=

poetry run coverage report --show-missing --fail-under=80
poetry run coverage xml
```

Первый запуск создаёт coverage data, второй добавляет integration coverage к
тем же данным. Gate применяется после обеих групп, поэтому значение отражает
весь обязательный test suite.

Правила coverage:

- измеряется `src/app`, а не сами тесты;
- используется branch coverage;
- threshold считается отдельно для каждого сервиса;
- падение до `79.99%` считается ошибкой;
- `# pragma: no cover` допускается только для недостижимой защитной ветки с
  объяснением в code review;
- запрещено добавлять бессодержательные тесты только ради числа.

## 10. Ruff: локальное исправление и CI-проверка

Локально разработчик может применять исправления:

```powershell
poetry run ruff check --fix .
poetry run ruff format .
```

CI ничего не изменяет и только проверяет:

```powershell
poetry run ruff check --output-format=github .
poetry run ruff format --check .
```

Если CI упал на formatter, нужно выполнить локальный `ruff format .`, изучить
diff и закоммитить результат. Автоформатирование внутри CI недопустимо: runner
не должен скрытно менять проверяемый commit.

## 11. Pyright: строгая типизация

Workflow устанавливает точную, закреплённую версию официального npm-пакета:

```powershell
npm install --global pyright@1.1.413
pyright
```

Версия `1.1.413` совпадает с текущими workflow. Значение `latest` не
используется.

Pyright проверяет `src`, но не требует строгой типизации каждой fixture в
`tests`. Нельзя отключать strict mode целиком из-за одной нетипизированной
библиотеки. Сначала проверяется наличие актуальных stubs, затем проблема
локализуется минимальным typed adapter или точечным комментарием с объяснением.

## 12. `pip-audit`: проверка только runtime-зависимостей

Цель — проверить то, что попадёт в runtime image, без pytest, Ruff и других
development-инструментов.

Для Poetry-проекта наиболее прозрачная последовательность:

```powershell
poetry export `
  --only main `
  --format requirements.txt `
  --output requirements-ci.txt

poetry run pip-audit `
  --requirement requirements-ci.txt `
  --progress-spinner off

Remove-Item -LiteralPath requirements-ci.txt
```

В Poetry 2 команда `export` предоставляется отдельным
`poetry-plugin-export`. Версия plugin должна быть закреплена в CI так же, как
версия Poetry. Временный `requirements-ci.txt` не коммитится.

Почему не используется простой `pip-audit` внутри dev-окружения: он добавит в
результат инструменты тестирования и их transitive dependencies, которых нет в
production image.

Правила обработки finding:

1. проверить идентификатор уязвимости и затронутый диапазон;
2. обновить прямую зависимость или ограничение, затем пересоздать lock-файл;
3. снова выполнить полный test suite и Docker build;
4. ignore допускается только с ID, причиной, владельцем и датой удаления;
5. `|| true` и безусловное подавление exit code запрещены.

## 13. Secret scanning

Используются два уровня.

### Уровень 1. GitHub Secret scanning и Push protection

Для каждого публичного репозитория проверить в GitHub:

```text
Repository -> Settings -> Code security and analysis
```

Ожидается:

- secret scanning включён или активен автоматически для публичного
  репозитория;
- push protection включена;
- alerts регулярно просматриваются;
- bypass не используется для реального секрета.

### Уровень 2. CI scanner

В каждый репозиторий добавляется history-aware scanner, например Gitleaks.
Action закрепляется полным commit SHA:

```yaml
- name: Scan repository for secrets
  uses: gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e # v3.0.0
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Точный SHA сначала сверяется с официальным репозиторием action. Плавающий
`@master`, `@main` или только `@v2` не используется.

При обнаружении настоящего секрета сначала отзывается или ротируется сам
credential. Простое удаление строки из последнего commit не делает уже
опубликованный секрет безопасным.

Локальную проверку можно повторить официальным контейнером Gitleaks. Из корня
superproject:

```powershell
docker run --rm `
  -v "${PWD}:/repo" `
  ghcr.io/gitleaks/gitleaks:v8.30.1 `
  git /repo --redact --verbose

docker run --rm `
  -v "${PWD}:/repo" `
  ghcr.io/gitleaks/gitleaks:v8.30.1 `
  dir /repo --redact --verbose
```

Для истории submodule нужно монтировать весь superproject, а не только каталог
сервиса: файл `services/<service>/.git` ссылается на `.git/modules` родителя.
Например:

```powershell
docker run --rm `
  -v "${PWD}:/repo" `
  ghcr.io/gitleaks/gitleaks:v8.30.1 `
  git /repo/services/identity-service --redact --verbose
```

В корне есть `.gitleaks.toml` с одним узким allowlist: одновременно должны
совпасть путь `docker-compose.yml` и полная строка закреплённого публичного
Valkey image из этого файла. Это устраняет ложный `generic-api-key`, но не
разрешает другие совпадения в том же файле. Реальные credentials добавлять в
allowlist запрещено.

## 14. Docker build в CI

### Python-сервисы

После появления `poetry.lock` Dockerfile должен копировать оба файла до
установки зависимостей:

```dockerfile
COPY pyproject.toml poetry.lock ./
```

Установка builder stage должна быть синхронизирована с lock-файлом и включать
только main dependencies. Runtime stage по-прежнему не содержит Poetry,
компилятор и тестовые инструменты.

Локальная проверка:

```powershell
docker build `
  --target runtime `
  --tag andruha/<service>:ci `
  .
```

После сборки выполняется container smoke test:

1. запустить образ на временном host port;
2. дождаться `/health/live` ограниченным retry-loop;
3. проверить `/health/ready`;
4. проверить наличие `X-Request-Id`;
5. остановить и удалить контейнер;
6. при ошибке вывести `docker logs`.

Контейнер должен удаляться и при успешной проверке, и при ошибке workflow.

### API Gateway

```powershell
Set-Location C:\Projects\Andruha\services\api-gateway

docker build --target validation --tag andruha/api-gateway:validation .
docker build --target runtime --tag andruha/api-gateway:ci .
```

Первый build выполняет `nginx -t` внутри validation stage. Второй доказывает,
что итоговый runtime image действительно собирается.

Gateway smoke test проверяет:

- `/health/live` и `/health/ready` возвращают `200`;
- оба ответа содержат gateway-generated `X-Request-Id`;
- неизвестный маршрут возвращает JSON `404` и request ID;
- конфигурация содержит ожидаемые route prefixes;
- `/ws` содержит Upgrade/Connection headers и увеличенные timeout;
- upstream не может подменить публичный `X-Request-Id`.

## 15. Проверка Alembic migrations

### Где эта проверка нужна

| Репозиторий | Alembic сейчас | Целевая политика |
|---|---:|---|
| Identity Service | Нет | Добавить после появления SQLAlchemy models и первой PostgreSQL migration |
| User Profile Service | Нет | Добавить после появления SQLAlchemy models и первой PostgreSQL migration |
| Messages and Dialogues Service | Не применим | Основное хранилище в skeleton — Cassandra; Alembic не управляет Cassandra |
| WebSocket Gateway Service | Не применим | Нет PostgreSQL ownership |
| Object Storage Service | Не определено | Добавить только если сервис станет владельцем SQL metadata |
| API Gateway | Не применим | NGINX не имеет БД |

Пустой каталог `alembic/` не создаётся ради зелёного status check.

### Как будет работать migration job

После появления миграций Identity/Profile job поднимает отдельный disposable
PostgreSQL и выполняет:

1. ожидание готовности PostgreSQL через `pg_isready`;
2. проверку, что migration graph имеет ровно одну голову;
3. `alembic upgrade head` на полностью пустой базе;
4. `alembic check`, чтобы найти изменения моделей без migration;
5. integration tests на схеме `head`;
6. удаление test database вместе с runner.

Надёжная проверка количества heads:

```powershell
poetry run python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; heads = ScriptDirectory.from_config(Config('alembic.ini')).get_heads(); assert len(heads) == 1, heads"
```

Основные команды:

```powershell
poetry run alembic upgrade head
poetry run alembic check
```

Downgrade test вводится отдельным решением. Не каждая production migration
обязана быть автоматически обратимой, но необратимость должна быть явно
документирована вместе с rollback procedure.

## 16. Contract tests

### Текущее правило

Пока в `contracts/` нет схем, contract job имеет статус **N/A**, а не passed.
Workflow, который проверяет только наличие пустого каталога и становится
зелёным, не является contract testing.

### Будущие уровни проверки

1. **Schema validation** — OpenAPI/AsyncAPI/event schema синтаксически валидна.
2. **Breaking-change detection** — новая версия не удаляет и не сужает
   публичный контракт без versioning decision.
3. **Provider conformance** — реальное приложение выдаёт ответы, совместимые со
   своей схемой.
4. **Consumer examples** — потребитель умеет прочитать минимальные, полные и
   совместимые со старой версией сообщения.
5. **Root integration** — главный репозиторий проверяет согласованный набор
   submodule commits и канонических контрактов.

### Владение контрактами по сервисам

| Репозиторий | Что проверять после появления контрактов |
|---|---|
| Identity Service | HTTP provider contract аутентификации; только фактически реализованные endpoints |
| User Profile Service | HTTP provider contract профилей и ссылки на media objects |
| Messages and Dialogues Service | HTTP contracts плюс схемы публикуемых/потребляемых Kafka events |
| WebSocket Gateway Service | WebSocket protocol messages плюс совместимость потребляемых Kafka events |
| Object Storage Service | HTTP upload/access contracts; поведение S3 адаптера проверяется integration tests, а не публичным S3 contract |
| API Gateway | Соответствие route prefixes каноническим HTTP contracts; gateway не переопределяет business schema |
| Main repository | Синтаксис, compatibility diff и cross-service contract matrix |

Названия будущих событий и API-файлов не фиксируются этим документом: их пока
нет в source of truth. Они появятся отдельным контрактным решением.

## 17. Особенности каждого репозитория

### 17.1 `andruha-identity-service`

Обязательные проверки сейчас:

- общий Python quality/test/security pipeline;
- coverage `src/app >= 80%`;
- runnable image и health smoke test.

Добавляются вместе с persistence task:

- PostgreSQL service container;
- single-head Alembic check;
- upgrade пустой БД до `head`;
- model/migration drift check;
- repository adapter integration tests.

Contract job включается после появления реального auth OpenAPI.

### 17.2 `andruha-user-profile-service`

Обязательные проверки сейчас идентичны Identity.

После persistence task добавляются PostgreSQL/Alembic checks. Object Storage не
должен становиться обязательным внешним dependency для unit tests: связь между
профилем и media object тестируется через application port/fake, а реальная
межсервисная совместимость — в integration/contract suite.

### 17.3 `andruha-messages-dialogues-service`

Обязательные проверки сейчас:

- общий Python pipeline;
- тесты HTTP operational bootstrap;
- тесты пустой messaging package не нужны: отсутствие поведения не тестируется;
- Docker build и health smoke.

После добавления adapters:

- Cassandra integration tests запускаются против disposable Cassandra;
- Kafka producer/consumer tests запускаются против disposable broker;
- проверяются retry, duplicate delivery и malformed event cases;
- Alembic не добавляется.

### 17.4 `andruha-websocket-gateway-service`

Обязательные проверки сейчас — общий Python pipeline и HTTP health smoke.

После реализации realtime boundary добавляются:

- WebSocket handshake, close codes и malformed message tests;
- несколько одновременных соединений одного пользователя;
- disconnect/context cleanup;
- Valkey integration для ephemeral routing/presence;
- Kafka consumer compatibility;
- отсутствие durable message ownership.

### 17.5 `andruha-object-storage-service`

Обязательные проверки сейчас — общий Python pipeline и HTTP health smoke.

После S3 adapter task добавляются integration tests с disposable MinIO:

- upload/download round trip;
- отсутствующий object;
- content type и size constraints;
- недоступность MinIO;
- очистка созданных test objects.

Alembic не добавляется, пока отдельным решением не подтверждено владение SQL
metadata.

### 17.6 `andruha-api-gateway`

Python-инструменты здесь не запускаются. CI содержит:

1. secret scan;
2. validation-stage build с `nginx -t`;
3. runtime-stage build;
4. container health/404/request-ID smoke tests;
5. проверку будущих маршрутов на тестовых upstreams;
6. публикацию GHCR image только по release tag.

Coverage threshold к NGINX-конфигурации не применяется. Вместо процента
используется явная таблица routing scenarios.

### 17.7 `andruha-messenger`

Главный репозиторий не повторяет unit tests сервисов. Его pipeline проверяет
интеграцию конкретных submodule commits:

```powershell
git submodule sync --recursive
git submodule update --init --recursive
docker compose config --quiet
docker compose build
```

Текущий root workflow выполняет Compose smoke suite:

- все шесть application containers достигают healthy без запуска внешней
  инфраструктуры, которая пока не используется operational skeleton;
- public `/health/live` и `/health/ready` доступны через gateway;
- gateway возвращает созданный им `X-Request-Id`;
- `docker compose down --volumes` выполняется в cleanup disposable CI stack.

Когда появятся реальные adapters, suite расширяется healthchecks PostgreSQL,
Cassandra, Kafka, Valkey и MinIO, проверкой route prefixes до upstream и
сквозной корреляцией request ID.

Удаление volumes допустимо только для одноразового CI-проекта с уникальным
Compose project name. Эта команда не должна использоваться против локального
developer stack или shared environment.

## 18. Реализованные GitHub Actions workflows

Фактические файлы `.github/workflows/ci.yml` являются источником истины. Пять
Python-сервисов используют один и тот же проверенный baseline:

1. checkout;
2. Python 3.14 и Node.js 24;
3. Poetry 2.4.1 и poetry-plugin-export 1.10.0;
4. `poetry check --lock` и `poetry sync`;
5. Ruff lint/format;
6. Pyright 1.1.413 strict;
7. unit и integration tests с общим coverage gate 80%;
8. runtime-only export и `pip-audit`;
9. отдельный full-history Gitleaks job;
10. Docker build с `load: true` и container health smoke.

Закреплённые Actions:

| Action | Release | Полный commit SHA |
|---|---:|---|
| `actions/checkout` | 7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-python` | 7.0.0 | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| `actions/setup-node` | 6.5.0 | `249970729cb0ef3589644e2896645e5dc5ba9c38` |
| `gitleaks/gitleaks-action` | 3.0.0 | `e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e` |
| `docker/setup-buildx-action` | 4.2.0 | `bb05f3f5519dd87d3ba754cc423b652a5edd6d2c` |
| `docker/build-push-action` | 7.3.0 | `53b7df96c91f9c12dcc8a07bcb9ccacbed38856a` |
| `docker/login-action` | 4.6.0 | `dbcb813823bdd20940b903addbd779551569679f` |
| `docker/metadata-action` | 6.2.0 | `dc802804100637a589fabce1cb79ff13a1411302` |

`GITLEAKS_ENABLE_COMMENTS=false` и artifact upload отключён, поэтому secret
scanner работает с минимальным `contents: read`. Репозитории принадлежат
личному аккаунту, поэтому Gitleaks license key не нужен.

Root `integration.yml` использует уникальные `COMPOSE_PROJECT_NAME` и
`ANDRUHA_NETWORK_NAME`, чтобы параллельные PR не делили контейнеры и сеть.

## 19. Публикация Docker images в GHCR

Release workflow запускается только для тегов согласованного формата, например
`v0.1.0`.

Правила:

- workflow повторяет обязательные CI checks или вызывает тот же reusable
  workflow;
- login в `ghcr.io` выполняется через `${{ github.actor }}` и
  `${{ secrets.GITHUB_TOKEN }}`;
- только publish job получает `packages: write`;
- PR workflows всегда используют `push: false`;
- образ получает SemVer tag и immutable commit-SHA tag;
- `latest` на первом этапе не публикуется;
- Dockerfile содержит OCI label `org.opencontainers.image.source` со ссылкой
  на репозиторий;
- после push digest сохраняется в summary workflow.

Имена образов:

```text
ghcr.io/yemeal/andruha-api-gateway
ghcr.io/yemeal/andruha-identity-service
ghcr.io/yemeal/andruha-user-profile-service
ghcr.io/yemeal/andruha-messages-dialogues-service
ghcr.io/yemeal/andruha-websocket-gateway-service
ghcr.io/yemeal/andruha-object-storage-service
```

Главный `andruha-messenger` image не публикует: superproject не имеет своего
Dockerfile.

## 20. Безопасность GitHub Actions

Общие обязательные правила:

1. каждое стороннее `uses:` закрепляется полным commit SHA;
2. tag версии оставляется рядом комментарием для читаемости;
3. default permissions задаются как `contents: read`;
4. `packages: write` выдаётся только publish job;
5. CI для PR не получает deployment secrets;
6. не используется `pull_request_target` для исполнения кода из PR;
7. shell не интерполирует title/body PR напрямую в команду;
8. workflow не печатает environment и secrets;
9. зависимости и Actions обновляются отдельными проверяемыми PR;
10. failed security check нельзя обходить `continue-on-error`.

## 21. Ruleset для `main`

После первого успешного запуска создать repository ruleset:

```text
Repository -> Settings -> Rules -> Rulesets -> New branch ruleset
```

Рекомендуемые требования:

- target branch: `main`;
- изменения только через pull request;
- required status checks:
  - quality and tests;
  - secret scan;
  - Docker build;
  - migration check только для Identity/Profile после появления миграций;
  - contract check только после появления реальных contracts;
- branch must be up to date before merge;
- force push запрещён;
- deletion `main` запрещено.

Если над проектом работает один владелец, обязательное approval другого
пользователя не включается: иначе владелец заблокирует собственные PR. Это не
отменяет обязательные автоматические checks.

## 22. Как полностью воспроизвести CI локально

### Python-сервис

```powershell
Set-Location C:\Projects\Andruha\services\identity-service

poetry check --lock
poetry sync --with dev --no-root

poetry run ruff check --output-format=github .
poetry run ruff format --check .

npm install --global pyright@1.1.413
pyright

poetry run coverage erase
poetry run pytest tests/unit --cov=app --cov-branch --cov-report=
poetry run pytest tests/integration --cov=app --cov-branch --cov-append --cov-report=
poetry run coverage report --show-missing --fail-under=80

poetry export --only main --format requirements.txt --output requirements-ci.txt
poetry run pip-audit --requirement requirements-ci.txt --progress-spinner off
Remove-Item -LiteralPath requirements-ci.txt

docker build --target runtime --tag andruha/identity-service:ci .
```

Для другого сервиса меняются только каталог и Docker tag.

### Главный репозиторий

```powershell
Set-Location C:\Projects\Andruha

git submodule sync --recursive
git submodule update --init --recursive
docker compose config --quiet
docker compose build
```

Для точного повтора текущего app-only smoke используйте отдельные имена проекта
и сети. Это не затронет обычный локальный stack:

```powershell
$env:COMPOSE_PROJECT_NAME = "andruha-ci-local"
$env:ANDRUHA_NETWORK_NAME = "andruha-ci-local-network"

try {
    docker compose up `
      --detach `
      --wait `
      --wait-timeout 180 `
      api-gateway `
      identity-service `
      user-profile-service `
      messages-dialogues-service `
      websocket-gateway-service `
      object-storage-service

    Invoke-WebRequest -UseBasicParsing `
      http://127.0.0.1:8080/health/live
    Invoke-WebRequest -UseBasicParsing `
      http://127.0.0.1:8080/health/ready
    docker compose ps
}
finally {
    docker compose down --volumes --remove-orphans
    Remove-Item Env:COMPOSE_PROJECT_NAME
    Remove-Item Env:ANDRUHA_NETWORK_NAME
}
```

Перед запуском убедитесь, что порт `8080` свободен. `down --volumes` здесь
безопасен только потому, что имена проекта и сети одноразовые и явно заданы.

## 23. Диагностика типовых падений

| Симптом | Что проверить | Правильное исправление |
|---|---|---|
| `poetry.lock` устарел | Изменён ли `pyproject.toml` без lock | Локально выполнить `poetry lock`, изучить diff, commit оба файла |
| Ruff lint failed | Конкретный rule code и строка | Исправить код или локально применить `ruff check --fix`; не отключать весь rule set |
| Ruff format failed | Показываемый formatting diff | Выполнить `ruff format .` и commit результата |
| Pyright failed | Unknown/Any, отсутствующий stub, неверный Optional | Исправить boundary type; suppression делать минимальным и объяснённым |
| Coverage ниже 80% | `coverage report --show-missing` | Добавить тест поведения для непокрытой ветки; не исключать модуль целиком |
| `pip-audit` finding | Advisory ID и fixed versions | Обновить constraint/lock, затем повторить tests/build |
| Secret scan failed | Реальный ли credential | Сначала revoke/rotate, затем удалить из истории безопасной процедурой |
| Несколько Alembic heads | Параллельные migrations | Создать осмысленную merge migration; не выбирать одну голову случайно |
| `alembic check` failed | Model metadata расходится с head | Создать и проверить новую migration |
| Docker build failed | Builder stage, lock, platform | Воспроизвести той же командой локально; не устанавливать undeclared package вручную |
| Root Compose failed | Какой submodule SHA и какой service image | Исправить сервис, обновить его pointer в отдельном root PR |

## 24. Порядок внедрения

Внедрение лучше разбить на проверяемые изменения:

1. **Выполнено локально — Identity**: dependencies, lock, config, meaningful
   tests, local green checks, Docker smoke.
2. **Выполнено локально — остальные Python-сервисы**: применён тот же baseline
   с собственными lock-файлами.
3. **Выполнено локально — API Gateway**: `nginx -t`, runtime image и smoke;
   найден и исправлен duplicate WebSocket timeout.
4. **Выполнено локально — root integration**: Compose config/build и app-only
   stack smoke, 6/6 containers healthy.
5. **Выполнено — service workflows**: CI и GHCR release опубликованы во всех
   сервисах; шесть CI runs успешно прошли на GitHub.
6. **Выполнено — root workflow**: Compose integration workflow с новыми
   submodule pointers успешно прошёл на GitHub.
7. **Следующий внешний шаг — rulesets**: включить обязательные checks после
   первого успешного root run, чтобы не заблокировать setup commit.
8. **Migration и contract jobs**: включать вместе с первой реальной migration
   или contract, а не заранее.

## 25. Definition of Done

CI/CD baseline завершён только если:

- [x] пять Python-репозиториев имеют **committed и pushed** `poetry.lock`;
- [x] все импортируемые runtime packages объявлены напрямую;
- [x] Ruff lint и format checks проходят локально и в GitHub Actions;
- [x] Pyright strict проходит для `src` пяти сервисов;
- [x] unit и integration suites содержат проверки поведения;
- [x] branch coverage каждого Python-сервиса не ниже 80%;
- [x] `pip-audit` проверяет только runtime dependency export;
- [x] GitHub Secret scanning и Push protection активны во всех семи
  репозиториях;
- [x] Gitleaks локально проходит по полной истории всех семи репозиториев и по
  текущему workspace; все семь jobs также прошли в GitHub Actions;
- [x] шесть runtime Docker images собираются;
- [x] health smoke tests проходят для каждого image;
- [x] root `docker compose config --quiet`, build и изолированный app-only smoke
  проходят с текущими submodules;
- [ ] обязательные status checks включены в ruleset `main`;
- [ ] release tag публикует образ в GHCR с SemVer и commit-SHA tags;
- [x] migration/contract checks явно N/A до появления реальных артефактов — они
  не изображают фиктивный success;
- [x] автоматический deployment не заявлен как готовый без deployment target и
  rollback procedure.

## 26. Официальные источники

- [GitHub: reusable workflows](https://docs.github.com/en/actions/concepts/workflows-and-actions/reusing-workflow-configurations)
- [GitHub: безопасное использование Actions](https://docs.github.com/en/actions/reference/security/secure-use)
- [GitHub: security features и secret scanning](https://docs.github.com/en/code-security/getting-started/github-security-features)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [Ruff в GitHub Actions](https://docs.astral.sh/ruff/integrations/)
- [Pyright: установка официального CLI](https://github.com/microsoft/pyright/blob/main/docs/installation.md)
- [Pyright: конфигурация strict mode](https://github.com/microsoft/pyright/blob/main/docs/configuration.md)
- [pytest-cov](https://pytest-cov.readthedocs.io/)
- [pip-audit](https://github.com/pypa/pip-audit)
- [Alembic command API](https://alembic.sqlalchemy.org/en/latest/api/commands.html)
- [Docker Build с GitHub Actions](https://docs.docker.com/build/ci/github-actions/)
