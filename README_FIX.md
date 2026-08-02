# ZRG OBLIVION Bot - FIXED версия с БД внутри

Эта версия исправляет проблему "на хостинге ничего не сохраняется".

## Быстрый старт

### 1. Залить на Amvera (самый простой, бесплатно, данные сохраняются)
- Залей файлы: `bot.py`, `requirements.txt`, `amvera.yaml`, папку `assets/` или jpg в корне
- В переменных окружения добавь `BOT_TOKEN` и `ADMIN_IDS`
- В `amvera.yaml` уже есть `persistenceMount: /data` — данные будут в `/data/bot.db`

### 2. Залить на Render
- Подключи репозиторий
- Render автоматически подхватит `render.yaml` с диском `/data`
- Добавь env `BOT_TOKEN`
- В Settings -> Disk убедись что диск подключен 1GB

### 3. Локально / VPS
```bash
git clone https://github.com/nuruk12611/ZRG_OBLIVION.git
cd ZRG_OBLIVION
# замени bot.py на новый из FIXED версии
python bot.py
```
Данные будут в `data/bot.db`

## Что внутри?

- `bot.py` — основной бот, теперь с SQLite (bot.db)
- `data/bot.db` — создается автоматически, содержит всё
- `data/backups/` — автобэкапы каждый час
- `assets/*.jpg` — баннеры

## Важно

- Если раньше были `data/*.json` — бот их сам импортирует в `bot.db` при первом запуске
- Для сохранения на хостингах нужен persistent disk / volume (настроено в yaml)
- Без диска — делай экспорт через админку регулярно

Смотри `DATABASE_FIX_RU.md` для подробностей.
