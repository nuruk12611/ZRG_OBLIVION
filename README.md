# ZRG Oblivion Bot

Telegram-бот для PUBG Mobile клана **ZRG OBLIVION**.

## Что умеет

- `/start` + антибот-капча на inline-кнопках.
- Главное меню с баннерами:
  - 🛡️ О клане
  - 📝 Заявка в клан
  - 🎓 Академия
  - 🎧 Техподдержка
  - 📣 Обжалование мута
  - 🔐 Админ-панель
- Анкета заявки в клан: никнейм, ID, уровень, K/D, роль.
- Техподдержка: текст + фото/документ.
- Обжалование мута: форма + возможный скриншот.
- Админ-панель:
  - статистика
  - просмотр новых заявок/тикетов/обжалований
  - принятие/отклонение заявок
  - закрытие тикетов
  - одобрение/отклонение обжалований
  - экспорт JSON-данных в ZIP.

## Файлы

```text
bot.py               основной бот, стандартная библиотека Python
run_forever.py       авто-рестарт для ПК/VPS
requirements.txt     пустой файл-заглушка для хостингов
.env.example         пример переменных окружения
assets/              баннеры jpg
data/                база JSON, создаётся/пополняется автоматически
amvera.yaml          конфиг Amvera
render.yaml          конфиг Render worker
koyeb.yaml           пример для Koyeb
Procfile             worker-команда
start_windows.bat    запуск на Windows
```

## Быстрый запуск на ПК

1. Установи Python 3.11+.
2. Скопируй `.env.example` в `.env`.
3. Впиши токен и ID админов:

```env
BOT_TOKEN=твой_токен_от_BotFather
ADMIN_IDS=твой_telegram_id
```

Чтобы узнать Telegram ID, запусти бота и напиши ему `/id`.

4. Запусти:

```bash
python bot.py
```

Или с авто-рестартом:

```bash
python run_forever.py
```

На Windows можно дважды открыть `start_windows.bat`.

## Запуск на хостинге / GitHub без папок

Бот теперь сам создаёт все нужные папки при старте:

```text
data/
assets/
```

Также он сам создаёт пустые JSON-базы:

```text
users.json
states.json
counters.json
applications.json
tickets.json
appeals.json
```

Если GitHub/телефон не даёт залить папки — загружай файлы **прямо в корень репозитория**:

```text
bot.py
requirements.txt
about.jpg
admin.jpg
apply.jpg
menu.jpg
support.jpg
unmute.jpg
```

При запуске хостинг сам создаст `assets/` и `data/`. JPG-баннеры, лежащие рядом с `bot.py`, бот найдёт сам и при возможности скопирует в `assets/`.

Переменные окружения:

```env
BOT_TOKEN=токен_бота
ADMIN_IDS=123456789,987654321
CLAN_NAME=ZRG OBLIVION
```

Команда запуска:

```bash
python bot.py
```

Для подробностей смотри:

- `AMVERA_RU.md`
- `RENDER_RU.md`
- `KOYEB_RU.md`
- `PC_INSTALL_RU.txt`

## Защита от `Conflict getUpdates`

В бот добавлена защита от случайного двойного запуска:

- на одном ПК/VPS/container второй процесс не стартует из-за файла `data/bot.lock`;
- если Telegram увидит другую удалённую копию с тем же `BOT_TOKEN`, эта копия уйдёт в passive standby и перестанет опрашивать Telegram, чтобы не было бесконечной драки `Conflict getUpdates`;
- чтобы активировать именно эту копию, останови старую копию и перезапусти эту.

Опционально можно поставить `CONFLICT_MODE=exit`, тогда при конфликте процесс завершится с кодом 75.

Файл `.env` нельзя публиковать. Если токен утёк — сделай `/revoke` в @BotFather.
