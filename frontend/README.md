# Андрюха frontend

Vue 3 + TypeScript + Vite. Публичный лендинг ведёт к регистрации и входу. Авторизация и профиль работают через существующий API gateway. Диалоги пока представлены отдельным, явно помеченным демо: в текущем `messages-dialogues-service` нет продуктовых HTTP-маршрутов для списка диалогов и отправки сообщений.

## Локальный запуск

```powershell
cd C:\Projects\Andruha\frontend
npm install
npm run dev -- --port 5173
```

Открыть `http://127.0.0.1:5173/`. Vite проксирует `/api` и `/ws` на `http://127.0.0.1:8080`. Другой адрес gateway можно задать через `ANDRUHA_GATEWAY_URL` до запуска Vite. В production frontend должен обслуживаться с того же origin, что и gateway, либо через reverse proxy с маршрутами `/api` и `/ws`.

Для локальной авторизации из корня Andruha запустить gateway, Identity, Profile и их зависимости:

```powershell
docker compose up -d --build --wait api-gateway identity-service user-profile-service identity-registration-reconciler
```

Локальный Compose выставляет `AUTH_COOKIE_SECURE=false` для HTTP-разработки. Для HTTPS-окружения использовать защищённые cookie.

## Проверки

```powershell
npm run build
```

Команда выполняет `vue-tsc --noEmit` и production-сборку. Демо-чаты хранятся только в памяти вкладки. Живой `/app` не подменяет отсутствие серверных диалогов вымышленными сообщениями; доступны настоящий вход, профиль и поиск профиля по нику.

## Изображения

`public/fox-hero.png`, `fox-front.png`, `fox-right.png`, `fox-envelope.png` и `fox-plane.png` созданы встроенным imagegen для Андрюхи. `fox-sleeping.png` и локальные файлы шрифта Onest взяты из существующего `design/andruha-concept`. Генерация использовала исходную лису как стилевой референс; у новой базовой позы хвост выходит из задней части туловища.
