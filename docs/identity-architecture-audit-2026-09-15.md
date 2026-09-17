# Identity Service: аудит и результат рефакторинга

Аудит: 2026-09-15. Рефакторинг: 2026-09-16.

## Решение и область

Пользователь одобрил рефакторинг и отдельно подтвердил использование Pydantic в домене. Pydantic сохранён; его наличие не считается нарушением архитектуры.

Изменения реализации ограничены Identity Service. Существовавшие незакоммиченные изменения сохранены; зависимости и lock-файл не менялись. User Profile использовался как ориентир и не изменялся.

## Что исправлено

| Находка | Исходная проблема | Результат |
|---|---|---|
| I01 · Логи исключений | SQL-параметры попадали в журнал через цепочку исключений | Engine использует hide_parameters; журнал сохраняет типы и расположение кадров стека без текста исключений, исходных строк и локальных значений |
| I02 · Инварианты | Прямые присваивания, пустой хеш, naive timestamps и отрицательный TTL могли нарушить состояние | Замороженные Pydantic-модели, проверка полного перехода до применения, доменные ошибки и валидируемый model_copy |
| I03 · Классификация ошибок | Ошибки конфигурации и выпуска JWT наследовали ошибку входящего токена и давали 401 | Технические ошибки находятся в application; ошибки выпуска/ключей дают безопасный 500, неверные credentials сохраняют 401 |
| I04 · Aggregate Root | Application отдельно изменял сессию и дочерние refresh-токены | AuthSession управляет ротацией, расходованием токена и отзывом; репозиторий сохраняет агрегат в общей транзакции |
| I05 · Use cases | Общий AuthService, примитивные параметры, проверка пароля только в HTTP | Семь отдельных команд/запросов и обработчиков; входные правила работают без HTTP; CurrentUser не содержит password_hash |
| I06 · Порты | Некоторые Protocol были обычными классами; существовал неработающий revoke_all_for_user | UserRepository — настоящий Protocol; порт сессии ограничен нужными операциями; отдельный публичный CRUD-порт токена удалён |
| I07 · Persistence | В application проходили SQLAlchemy-ошибки; любая ошибка финализации считалась временной | UoW переводит ошибки хранения; восстановление различает временный сбой, конфликт транзакции и постоянный дефект |
| I08 · Сложность | Неиспользуемый prepare, повторение конфигурации и выпуска токенов | prepare удалён; маршрутизация настроек использует описания полей; выпуск пары токенов общий |
| I09 · Читаемость | Устаревшие схемы ответственности, многословные комментарии, неверный статус RETRY | Комментарии сокращены и исправлены; технические модули сгруппированы по ответственности; проверки папок заменены проверками зависимостей |
| I10 · ORM-состояние | UPDATE RETURNING мог возвращать прежний claim_token из identity map; Outbox redrive ссылался на удалённый столбец | Возвращаемые ORM-объекты принудительно обновляются; устаревший столбец удалён из запроса; добавлены проверки на настоящем PostgreSQL |

### Домен

- [User](../services/identity-service/src/app/domain/aggregates/user.py) и [AuthSession](../services/identity-service/src/app/domain/aggregates/auth_session.py) — корни агрегатов.
- [RefreshToken](../services/identity-service/src/app/domain/entities/refresh_token.py) — дочерняя сущность сессии.
- Email и непрозрачный PasswordHash — Value Objects. Алгоритмы хеширования и криптография находятся в адаптерах.
- [DomainModel](../services/identity-service/src/app/domain/base.py) проверяет кандидат целиком до изменения объекта. Отклонённый переход сохраняет прежнее состояние. Метаданные Pydantic для сериализации обновляются вместе с полями.
- Положительный TTL, timezone и порядок временных меток проверяются до сохранения.
- Повторное предъявление использованного токена отзывает сессию. Application сохраняет этот отказ как результат, чтобы исключение не откатило отзыв.

### Application

Каждый вход имеет явный контракт:

| Вход | Обработчик |
|---|---|
| RegisterUserCommand | [RegisterUserHandler](../services/identity-service/src/app/application/use_cases/register/handler.py) |
| LoginCommand | [LoginHandler](../services/identity-service/src/app/application/use_cases/login/handler.py) |
| RefreshCommand | [RefreshHandler](../services/identity-service/src/app/application/use_cases/refresh/handler.py) |
| LogoutCommand | [LogoutHandler](../services/identity-service/src/app/application/use_cases/logout/handler.py) |
| GetCurrentUserQuery | [GetCurrentUserHandler](../services/identity-service/src/app/application/use_cases/get_current_user/handler.py) |
| ResumeRegistrationCommand | [ResumeRegistrationHandler](../services/identity-service/src/app/application/use_cases/resume_registration/handler.py) |
| RedriveRegistrationCommand | [RedriveRegistrationHandler](../services/identity-service/src/app/application/use_cases/redrive_registration/handler.py) |

Login освобождает транзакцию до Argon2, затем повторно проверяет пользователя под блокировкой. Logout идемпотентен внутри use case. Регистрация нормализует email и проверяет пароль до эффектов.

Сохранены durable registration operation, подтверждение Profile перед созданием пользователя, outbox, lease/CAS, durable fence и AES-GCM replay. Техническое состояние расположено в application/infrastructure.

### Исключения и наблюдаемость

[HTTP-маппинг](../services/identity-service/src/app/entrypoints/http/routers/exception_handlers.py) использует фиксированные публичные сообщения. Внутренний текст исключения не становится ответом клиенту.

[Переводчик ошибок БД](../services/identity-service/src/app/infrastructure/database/exceptions.py) различает конфликт транзакции, недоступность, нарушение ограничений и другие сбои хранения. [UoW](../services/identity-service/src/app/infrastructure/database/uow.py) применяет этот контракт для ошибок операции и commit. Некорректное сохранённое состояние выражается через StoredStateError.

[Логирование](../services/identity-service/src/app/core/logging.py) сохраняет безопасную цепочку типов и кадров. Проверены structlog и стандартный logging, консольный и JSON-форматы. Синтетические секреты из SQL-параметров, ValidationError и вложенных причин отсутствуют в захваченном выводе.

## Проверки

На итоговом коде прошли:

| Проверка | Результат |
|---|---|
| Unit tests | 370 passed |
| Integration tests | 110 passed |
| Совместное покрытие строк и ветвей | 89%; порог 80% пройден |
| Ruff check | Пройден |
| Ruff format --check | 246 файлов, изменений не требуется |
| ty check --error-on-warning | Пройден |
| poetry check --lock | Пройден |
| git diff --check | Пройден |

Покрытие собрано последовательно: unit-тесты создали новый набор данных, интеграционные дополнили его. Проверка покрытия выполнена после обоих прогонов.

Дополнительные регрессии проверяют:

- неизменность агрегата после отказа и запрет прямого присваивания;
- корректную сериализацию после бизнес-перехода;
- нормализацию регистра email при повторной регистрации и отказ короткому паролю при прямом вызове;
- разделение временных и постоянных сбоев регистрации;
- ошибку хеширования, SQLSTATE, commit-failure и сохранение отмены операции;
- безопасные HTTP-ответы и логи;
- ротацию, replay и конкурентные refresh/logout;
- перехват просроченных регистраций и Outbox при наличии старого ORM-объекта в памяти;
- Outbox redrive и отказ устаревшему владельцу lease;
- запрет зависимостей domain/application от адаптеров.

## User Profile: оставшиеся наблюдения

[Доменная база Profile](../services/user-profile-service/src/app/domain/base.py) при аудите принимала naive datetime; смешивание с UTC в обновлении приводило к TypeError. Также updated_at мог сдвигаться назад относительно предыдущего обновления, оставаясь позже created_at. Этот контракт времени требует отдельного исправления.

Pydantic в Profile, как и в Identity, не считается дефектом. Механизм атомарного применения состояния зависит от внутренних полей библиотеки и требует сохранения регрессионных проверок при обновлении Pydantic.

## Пределы проверки

Интеграционные тесты используют настоящие временные PostgreSQL и Valkey через Testcontainers. Profile peer — тестовый HTTP-сервер. Живой User Profile, Kafka, развёртывание и remote CI не проверялись.

Синхронное создание профиля и восстановление регистрации не образуют распределённую транзакцию. Для старых аккаунтов сохраняется необходимость отдельного backfill.

Защита состояния относится к штатным конструкторам и методам. Намеренный обход Python/Pydantic через object.__setattr__, прямую правку __dict__ или model_construct не является поддерживаемым интерфейсом.

## Последующая E2E-проверка

16 сентября выполнен [Docker E2E на реальных Identity, Profile, PostgreSQL, Valkey и Kafka](identity-e2e-2026-09-16.md). Проверена итоговая консистентность, исправлена гонка регистрации с одинаковым ключом. Повторная приемка 18 сентября подтвердила закрытие трех дефектов Gateway: 39 из 39 сценариев прошли.
