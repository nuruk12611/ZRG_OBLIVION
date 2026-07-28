# Как запустить ZRG Oblivion Bot на Render (dashboard.render.com)

Пошагово, что нажимать.

> Важно:  
> - Ссылка: **https://dashboard.render.com**  
> - Для Telegram-бота нужен **Background Worker**, не обычный Website.  
> - Free Worker на Render иногда ограничен/платный — если Free Worker нет, Render предложит платный план.  
> - На Free Web Service бот будет **засыпать** — для polling это плохо.

---

## 0) Что нужно заранее

1. Папка `pubg_clan_bot` (уже есть)
2. Аккаунт GitHub: https://github.com/signup
3. Аккаунт Render: https://dashboard.render.com
4. Токен бота из `.env` / BotFather

---

## 1) Залей код на GitHub

### Через сайт (проще)

1. Открой https://github.com/new
2. Repository name: `zrg-oblivion-bot`
3. Create repository
4. Нажми **uploading an existing file**
5. Загрузи файлы:
   - `bot.py` (обязательно)
   - `requirements.txt`
   - `Procfile`
   - `render.yaml` (если есть)
   - баннеры: либо папку `assets/`, либо JPG прямо в корень (`about.jpg`, `admin.jpg`, `apply.jpg`, `menu.jpg`, `support.jpg`, `unmute.jpg`)
   - `RENDER_RU.md` (необязательно)
6. Папку `data/` загружать не нужно — бот создаст её сам на хостинге
7. **Не загружай** (лучше):
   - `.env`
   - `bot.log`
   - `*.pid`
7. Commit changes

---

## 2) Войди в Render

1. Открой: https://dashboard.render.com
2. Sign in (лучше через GitHub)

---

## 3) Создай Background Worker

1. На Dashboard нажми **New +**
2. Выбери **Background Worker**
   - если Background Worker недоступен на Free — см. раздел «Если нет Free Worker»
3. Подключи GitHub (Connect account), если попросит
4. Выбери репозиторий `zrg-oblivion-bot`
5. Branch: `main`

---

## 4) Заполни настройки

### Name
```text
zrg-oblivion-bot
```

### Region
```text
Frankfurt (EU Central)
```
(или ближайший EU)

### Runtime
```text
Python 3
```

### Build Command
```text
pip install -r requirements.txt
```

### Start Command
```text
python bot.py
```

> Не используй `run_forever.py` на Render.  
> У Render свой restart.

### Instance Type
- Если есть **Free** — выбери Free
- Если только Starter/paid — это уже платно

---

## 5) Environment Variables (токен)

1. Раздел **Environment**
2. Add Environment Variable:

| Key | Value |
|-----|--------|
| `BOT_TOKEN` | твой токен от BotFather |
| `ADMIN_IDS` | Telegram ID админов через запятую |

Пример:
```text
BOT_TOKEN=8626829471:AAE................
```

3. Save

---

## 6) Deploy

1. Нажми **Create Background Worker** / **Deploy**
2. Открой вкладку **Logs**
3. Должно появиться примерно:

```text
ONLINE @ZRG_Oblivion_bot
POLL READY
```

---

## 7) Проверка в Telegram

1. Открой @ZRG_Oblivion_bot
2. Напиши `/start`
3. Должен ответить

---

## 8) Защита от `Conflict getUpdates`

В код добавлена защита:
- две копии на одном сервере не стартуют из-за `data/bot.lock`;
- если где-то уже работает другая удалённая копия с тем же `BOT_TOKEN`, эта копия уйдёт в passive standby и перестанет опрашивать Telegram.

Чтобы активной была именно Render-копия:
1. выключи бота на ПК / Amvera / Koyeb / Arena;
2. сделай Manual Deploy / Restart на Render.

---

## Если нет Free Worker / просит оплату

Тогда варианты:

1. **Koyeb Free** (часто проще для worker): https://app.koyeb.com/
2. **Свой ПК**: `start_windows.bat`
3. **Дешёвый VPS РФ** (Timeweb/FirstVDS/VDSina)

---

## Если выбрал обычный Web Service по ошибке

Можно, но хуже:
- Start Command всё равно: `python bot.py`
- Free Web засыпает → бот будет отваливаться

Лучше именно **Background Worker**.

---

## Частые ошибки

### `BOT_TOKEN not set`
- Не добавил env `BOT_TOKEN`
- Добавь → Manual Deploy → Deploy latest commit

### `Conflict getUpdates`
- Код уже уводит лишнюю копию в passive standby
- Если хочешь, чтобы работал именно Render: останови другие копии и перезапусти Render

### Deploy failed / Build failed
- Проверь, что в репо есть `bot.py` и `requirements.txt`
- Build Command: `pip install -r requirements.txt`
- Start Command: `python bot.py`

### Running, но не отвечает
1. Logs → ищи `ONLINE` и `POLL READY`
2. Напиши `/start` в личку боту
3. Проверь, что токен правильный

---

## Мини-чеклист

- [ ] Код на GitHub
- [ ] Render → New → Background Worker
- [ ] Repo выбран
- [ ] Start: `python bot.py`
- [ ] Env: `BOT_TOKEN=...`
- [ ] Deploy Running
- [ ] Logs: ONLINE / POLL READY
- [ ] `/start` в Telegram работает
- [ ] Другие копии бота выключены

---

## После деплоя

Обновления:
1. Меняешь файлы
2. Upload/push в GitHub
3. Render → Manual Deploy (или авто)

Готово.
