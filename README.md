# notion-telegram-notifier

**Notion → Telegram notifications.** Get an instant personal Telegram push the moment a Notion
task is assigned to you or its status changes. Built for teams moved to Notion **guest** seats,
where Notion's native notifications stop working.

**Уведомления из Notion в Telegram.** Мгновенный личный пуш в Telegram, как только вам назначили
задачу в Notion или сменился её статус. Для команд на **гостевых** местах Notion, где родные
уведомления Notion не работают.

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-3.12-blue">
  <img alt="aiogram" src="https://img.shields.io/badge/aiogram-3.x-2CA5E0">
  <img alt="Notion API" src="https://img.shields.io/badge/Notion-API-black">
  <img alt="SQLite" src="https://img.shields.io/badge/storage-SQLite-003B57">
  <img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-green">
</p>

**Language / Язык:** [Русский](#русский) · [English](#english)

---

## Русский

Бот опрашивает базу Notion и отправляет сотрудникам личные пуши в Telegram, когда
их назначают на задачу или меняется её статус. Нужен, когда команда переведена в
guest-статус Notion и нативные уведомления Notion перестают работать.

### Как это работает

- **Poller** — каждые 90 с опрашивает Notion, сравнивает снэпшоты, маршрутизирует
  события привязанным сотрудникам.
- **Bot** — самостоятельная регистрация сотрудников (флоу «сначала код») и админ-команды.
- **Storage** — один файл SQLite, единственный компонент с состоянием.

Входящего трафика нет: бот работает на long-polling, базе Notion достаточно
read-доступа. Один процесс, один контейнер, любой VPS.

### Требования

- Docker + Docker Compose
- Внутренняя интеграция Notion с правом чтения базы задач
- Токен Telegram-бота от [@BotFather](https://t.me/BotFather)

### Установка

**1. Настройте окружение**

```bash
cp .env.example .env
# Отредактируйте .env — заполните NOTION_TOKEN, TELEGRAM_TOKEN,
# NOTION_DATABASE_ID, ADMIN_CHAT_IDS
```

**2. Запустите**

```bash
docker compose up -d
docker compose logs -f
```

**3. Проверьте**

```bash
docker compose ps                                    # status: healthy
docker compose exec notify_bot python -c "print('ok')"
```

### Переменные окружения

| Переменная | Обязательна | По умолчанию | Описание |
|---|---|---|---|
| `NOTION_TOKEN` | да | — | Токен внутренней интеграции Notion |
| `TELEGRAM_TOKEN` | да | — | Токен Telegram-бота |
| `NOTION_DATABASE_ID` | да | — | UUID базы «All Tasks» |
| `ADMIN_CHAT_IDS` | да | — | Telegram chat_id админов через запятую |
| `DB_PATH` | нет | `/data/bot.db` | Путь к SQLite внутри контейнера |
| `POLL_INTERVAL` | нет | `90` | Секунд между циклами опроса |
| `OVERLAP_SECONDS` | нет | `300` | Окно перекрытия инкрементального фильтра |
| `DISPLAY_TZ` | нет | `Europe/Moscow` | Таймзона для отображения дат |
| `PROP_TITLE` | нет | `Name` | Имя свойства-заголовка в Notion |
| `PROP_ASSIGNEE` | нет | `Assign_new` | Свойство-исполнитель (multi-select) |
| `PROP_REPORTER` | нет | `Заказчик_new` | Свойство-постановщик |
| `PROP_STATUS` | нет | `Status` | Свойство-статус |
| `PROP_PROJECT` | нет | `Проект` | Свойство-связь с проектом |
| `PROP_DUE` | нет | `Дата` | Свойство-дедлайн |
| `DONE_STATUS` | нет | `Готово` | Статус, при котором события назначения подавляются |
| `PROJECT_CACHE_TTL` | нет | `86400` | TTL кэша названий проектов (сек) |
| `INVITE_TTL` | нет | `86400` | TTL кода-приглашения (сек) |
| `INVITE_MAX_ATTEMPTS` | нет | `3` | Неверных вводов кода за одну сессию регистрации до отмены диалога (отдельный механизм: 10 неудач с одного chat_id → мьют на 1 час) |
| `HEARTBEAT_PATH` | нет | `/tmp/notify_bot_heartbeat` | Файл heartbeat (должен совпадать с healthcheck) |
| `NOTION_BASE_URL` | нет | — | Альтернативный endpoint Notion API (тесты/демо) |

### Онбординг сотрудника

1. Админ выполняет `/invite Имя Сотрудника` — бот отвечает 8-символьным кодом.
2. Админ отправляет код сотруднику в личку.
3. Сотрудник открывает бота и пишет `/start`.
4. Сотрудник вводит код.
5. Бот просит подтверждение: «Привязать вас как Имя Сотрудника?»
6. Сотрудник нажимает ✅ Да — привязка сохранена, уведомления начнут приходить.

### Команды админа

| Команда | Описание |
|---|---|
| `/invite <Имя>` | Сгенерировать код-приглашение для имени сотрудника |
| `/list` | Показать всех сотрудников, их chat_id и дату привязки |
| `/rename Старое Имя -> Новое Имя` | Переименовать сотрудника (обновляет снэпшоты, не портит имена-подстроки) |
| `/unbind <Имя>` | Снять привязку Telegram (сотрудник перестаёт получать уведомления) |
| `/pause` | Поставить уведомления на паузу (события во время паузы НЕ досылаются) |
| `/resume` | Возобновить уведомления |

> **Важно после `/rename`:** сразу переименуйте соответствующую метку в multi-select
> Notion, иначе будущие страницы будут использовать старое имя и останутся без адресата.

### Резервное копирование и восстановление

**Бэкап**

```bash
# Основной сценарий (Docker). База лежит в именованном томе bot_data.
# В образе python:3.12-slim нет sqlite3 CLI, поэтому снимок делаем модулем
# sqlite3 (метод .backup консистентен даже при работающем боте — режим WAL).
docker compose exec notify_bot python -c "import sqlite3; s=sqlite3.connect('/data/bot.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close(); s.close()"
docker compose cp notify_bot:/data/backup.db ./backup.db

# Локальный запуск без Docker (нужен установленный sqlite3 CLI):
sqlite3 ./bot.db ".backup ./backup.db"
```

**Восстановление**

```bash
docker compose down
docker compose cp ./backup.db notify_bot:/data/bot.db
docker compose up -d
```

### Оффбординг сотрудника

1. `/unbind Имя Сотрудника` — снимает привязку Telegram.
2. Удалите имя сотрудника из опций multi-select в Notion.
3. (Опционально) удалите строку сотрудника из базы напрямую.

### Поведение при холодном старте

При первом запуске (нет чекпоинта) бот сканирует всю базу для построения снэпшотов,
но **не отправляет уведомлений**. Это предотвращает поток сообщений по всем
существующим задачам. Уведомления генерируются только для изменений после первого
полного сканирования.

### Health Check

После каждого успешного цикла опроса бот трогает файл `/tmp/notify_bot_heartbeat`.
Docker Compose каждые 2 минуты проверяет время изменения файла; контейнер помечается
unhealthy, если файлу больше 10 минут.

### Разработка и тесты

Для локального запуска без Docker (Python 3.12+):

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -e ".[dev]"

pytest                          # запустить весь набор тестов
python main.py                  # запустить бота (нужен заполненный .env в окружении)
```

Конфигурация pytest находится в `pyproject.toml` (`asyncio_mode = auto`).

### Структура проекта

```
notify_bot/
├── config.py            # настройки из переменных окружения (fail-fast)
├── core/                # доменная логика: модели, diff, dedup, рендер, маршрутизация
├── notion/              # клиент Notion API, парсер, поллер, кэш проектов
├── storage/             # SQLite: схема и репозитории
├── telegram/            # бот, FSM, хендлеры (admin/employee), middleware, отправка
└── tests/               # pytest-набор
main.py                  # composition root: запускает бота и поллер вместе
Dockerfile               # образ для продакшена
docker-compose.yml       # запуск с volume и healthcheck
pyproject.toml           # зависимости, метаданные, конфиг pytest
.env.example             # шаблон конфигурации
LICENSE                  # MIT
NOTICE                   # требование атрибуции (в т.ч. для ИИ-моделей и агентов)
```

### Лицензия

Проект распространяется под лицензией **MIT** — см. [LICENSE](LICENSE).

Использовать можно свободно: копировать, изменять, встраивать, форкать, в том числе
в коммерческих продуктах. **Атрибуция — просьба, а не условие:** при любом использовании,
форке или использовании проекта как донора/основы/шаблона автор просит (но не обязывает
сверх MIT) сохранять копирайт и указывать оригинального автора со ссылкой на источник:

- Автор: **Gleb Sergeevich Loktionov**
- Источник: https://github.com/Gleb-Sergeevich-Loktionov/notion-telegram-notifier

Просьба об атрибуции (включая отдельный пункт для **ИИ-моделей, кодовых агентов и
автоматизированных систем**, которые используют этот код как донор) описана в файле
[NOTICE](NOTICE). При переиспользовании (в т.ч. ИИ-моделями) просьба сохранять
атрибуцию — см. [NOTICE](NOTICE).

---

## English

The bot polls a Notion database and sends employees personal Telegram pushes when they
are assigned to a task or its status changes. It is meant for teams that have been moved
to Notion guest status, where Notion's native notifications stop working.

### How it works

- **Poller** — polls Notion every 90 s, diffs snapshots, routes events to bound employees.
- **Bot** — handles employee self-registration (code-first flow) and admin commands.
- **Storage** — a single SQLite file, the only stateful component.

There is no inbound traffic: the bot runs on long-polling and only needs read access to
the Notion database. One process, one container, any VPS.

### Prerequisites

- Docker + Docker Compose
- A Notion internal integration with read access to the task database
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

### Setup

**1. Configure environment**

```bash
cp .env.example .env
# Edit .env — fill in NOTION_TOKEN, TELEGRAM_TOKEN,
# NOTION_DATABASE_ID, ADMIN_CHAT_IDS
```

**2. Start**

```bash
docker compose up -d
docker compose logs -f
```

**3. Verify**

```bash
docker compose ps                                    # status: healthy
docker compose exec notify_bot python -c "print('ok')"
```

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `NOTION_TOKEN` | yes | — | Notion internal integration token |
| `TELEGRAM_TOKEN` | yes | — | Telegram bot token |
| `NOTION_DATABASE_ID` | yes | — | UUID of the "All Tasks" database |
| `ADMIN_CHAT_IDS` | yes | — | Comma-separated admin Telegram chat IDs |
| `DB_PATH` | no | `/data/bot.db` | SQLite path inside the container |
| `POLL_INTERVAL` | no | `90` | Seconds between poll cycles |
| `OVERLAP_SECONDS` | no | `300` | Incremental filter overlap window |
| `DISPLAY_TZ` | no | `Europe/Moscow` | Timezone for date display |
| `PROP_TITLE` | no | `Name` | Notion title property name |
| `PROP_ASSIGNEE` | no | `Assign_new` | Notion assignee multi-select property |
| `PROP_REPORTER` | no | `Заказчик_new` | Notion reporter property |
| `PROP_STATUS` | no | `Status` | Notion status property |
| `PROP_PROJECT` | no | `Проект` | Notion project relation property |
| `PROP_DUE` | no | `Дата` | Notion due date property |
| `DONE_STATUS` | no | `Готово` | Status value that suppresses new-assignee events |
| `PROJECT_CACHE_TTL` | no | `86400` | Project title cache TTL (seconds) |
| `INVITE_TTL` | no | `86400` | Invite code TTL (seconds) |
| `INVITE_MAX_ATTEMPTS` | no | `3` | Wrong code entries per registration session before the dialog aborts (separate mechanism: 10 failures per chat_id → 1-hour mute) |
| `HEARTBEAT_PATH` | no | `/tmp/notify_bot_heartbeat` | Heartbeat file (must match the healthcheck) |
| `NOTION_BASE_URL` | no | — | Alternative Notion API endpoint (tests/demo) |

### Employee onboarding flow

1. Admin runs `/invite Имя Сотрудника` — bot replies with an 8-character code.
2. Admin sends the code to the employee privately.
3. Employee opens the bot and sends `/start`.
4. Employee enters the code.
5. Bot asks for confirmation: "Привязать вас как Имя Сотрудника?"
6. Employee taps ✅ Да — binding saved, notifications will start arriving.

### Admin commands

| Command | Description |
|---|---|
| `/invite <Имя>` | Generate invite code for an employee name |
| `/list` | Show all employees, their chat_id and bind date |
| `/rename Старое Имя -> Новое Имя` | Rename employee (updates snapshots, does NOT corrupt substring names) |
| `/unbind <Имя>` | Remove Telegram binding (employee stops receiving notifications) |
| `/pause` | Pause all notifications (events during pause are NOT retroactively sent) |
| `/resume` | Resume notifications |

> **Important after `/rename`:** rename the corresponding label in the Notion multi-select
> property immediately, otherwise future pages will use the old name and go unmatched.

### Backup and restore

**Backup**

```bash
# Primary (Docker). The database lives in the named volume bot_data.
# The python:3.12-slim image has no sqlite3 CLI, so take the snapshot via the
# sqlite3 module (.backup is consistent even while the bot runs — WAL mode).
docker compose exec notify_bot python -c "import sqlite3; s=sqlite3.connect('/data/bot.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close(); s.close()"
docker compose cp notify_bot:/data/backup.db ./backup.db

# Local run without Docker (requires the sqlite3 CLI installed):
sqlite3 ./bot.db ".backup ./backup.db"
```

**Restore**

```bash
docker compose down
docker compose cp ./backup.db notify_bot:/data/bot.db
docker compose up -d
```

### Offboarding an employee

1. `/unbind Имя Сотрудника` — removes the Telegram binding.
2. Remove the employee's name from the Notion multi-select property options.
3. (Optional) delete the employee row from the database directly.

### Cold-start behaviour

On first launch (no checkpoint), the bot scans the entire database to build snapshots but
sends **no notifications**. This prevents a flood of messages for all existing tasks. Only
changes after the first full scan generate notifications.

### Health check

The bot touches `/tmp/notify_bot_heartbeat` after each successful poll cycle. Docker Compose
checks this file's modification time every 2 minutes; the container is marked unhealthy if
the file is more than 10 minutes old.

### Development and tests

To run locally without Docker (Python 3.12+):

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -e ".[dev]"

pytest                          # run the full test suite
python main.py                  # run the bot (requires a populated .env in the environment)
```

The pytest configuration lives in `pyproject.toml` (`asyncio_mode = auto`).

### Project structure

```
notify_bot/
├── config.py            # settings from environment variables (fail-fast)
├── core/                # domain logic: models, diff, dedup, rendering, routing
├── notion/              # Notion API client, parser, poller, project cache
├── storage/             # SQLite: schema and repositories
├── telegram/            # bot, FSM, handlers (admin/employee), middleware, sending
└── tests/               # pytest suite
main.py                  # composition root: runs bot and poller together
Dockerfile               # production image
docker-compose.yml       # run with volume and healthcheck
pyproject.toml           # dependencies, metadata, pytest config
.env.example             # configuration template
LICENSE                  # MIT
NOTICE                   # attribution requirement (incl. AI models and agents)
```

### License

Released under the **MIT License** — see [LICENSE](LICENSE).

You may use it freely: copy, modify, embed, fork, including in commercial products.
**Attribution is requested, not required:** for any use, fork, or use of this project as a
donor/base/template the author kindly asks (but does not require beyond MIT) that you
retain the copyright notice and credit the original author with a link to the source:

- Author: **Gleb Sergeevich Loktionov**
- Source: https://github.com/Gleb-Sergeevich-Loktionov/notion-telegram-notifier

The attribution request — including a note to **AI models, coding agents, and automated
systems** that use this code as a donor — is described in the [NOTICE](NOTICE) file.
Reuse (including by AI models) is asked to keep attribution — see [NOTICE](NOTICE).
