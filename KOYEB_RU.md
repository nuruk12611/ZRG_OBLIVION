# Перенос ZRG Oblivion Bot на Koyeb Free

Пошагово: что скачать, куда нажать, что вписать.

---

## 0) Что понадобится

- Аккаунт GitHub: https://github.com/signup  
- Аккаунт Koyeb: https://app.koyeb.com/auth/signup  
- Токен бота (у тебя уже есть в `.env`)

---

## 1) Подготовь папку бота на компьютере

Нужна папка `pubg_clan_bot` с файлами:

- `bot.py`
- `run_forever.py` (не обязателен на Koyeb)
- `requirements.txt`
- баннеры: либо `assets/`, либо JPG прямо в корень (`about.jpg`, `admin.jpg`, `apply.jpg`, `menu.jpg`, `support.jpg`, `unmute.jpg`)
- `KOYEB_RU.md` (эта инструкция)

Папку `data/` создавать и загружать не нужно — бот создаст её сам на хостинге.

**Важно:** файл `.env` на Koyeb лучше НЕ заливать.  
Токен вставим в настройках Koyeb как секрет.

Если `.env` уже есть — ок для ПК, но в Git его не коммить  
(он в `.gitignore`).

---

## 2) Залей код на GitHub

### Вариант A — через сайт GitHub (без команд)

1. Зайди: https://github.com/new  
2. Repository name: `zrg-oblivion-bot`  
3. Public или Private — как хочешь  
4. **Create repository**

5. На странице репо: **uploading an existing file**  
6. Перетащи все файлы из `pubg_clan_bot`  
   (кроме `.env`, `bot.log`, `*.pid` если можно)  
7. Commit changes

### Вариант B — через Git (если умеешь)

```bash
cd pubg_clan_bot
git init
git add bot.py requirements.txt Procfile koyeb.yaml KOYEB_RU.md START_HERE.txt run_forever.py assets .gitignore
# Если папки assets нет, но JPG лежат в корне:
# git add about.jpg admin.jpg apply.jpg menu.jpg support.jpg unmute.jpg
git commit -m "ZRG bot for Koyeb"
git branch -M main
git remote add origin https://github.com/ТВОЙ_ЛОГИН/zrg-oblivion-bot.git
git push -u origin main
```

---

## 3) Создай сервис на Koyeb

1. Открой: https://app.koyeb.com/  
2. **Create Service** / **Create Web Service**  
3. Выбери **GitHub**  
4. Подключи GitHub-аккаунт (Authorize)  
5. Выбери репозиторий `zrg-oblivion-bot`  
6. Branch: `main`

---

## 4) Важные настройки сервиса

### Service type
Выбери **Worker** (не Web), если есть выбор.  
Если только Web — тоже можно, но Worker правильнее для Telegram-бота.

### Build / Run
- Build command:  
  `pip install -r requirements.txt`  
  (можно оставить auto)
- Run command:  
  **`python bot.py`**

> На Koyeb лучше `python bot.py`, не `run_forever.py`  
> (у Koyeb сам есть Restart policy)

### Instance
- Region: **Frankfurt (fra)** — ближайший к DE/RU  
- Instance type: **Free** / Nano free

### Environment variables
Добавь переменную:

| Key | Value |
|-----|--------|
| `BOT_TOKEN` | `твой_токен_от_BotFather` |
| `ADMIN_IDS` | `Telegram ID админов через запятую` |

Пример вида токена:  
`8626829471:AAE................`

**Не публикуй токен** нигде.

---

## 5) Deploy

1. Нажми **Deploy** / **Create Service**  
2. Жди статус **Healthy / Running**  
3. Открой **Logs** — должно быть примерно:

```text
ONLINE @ZRG_Oblivion_bot
POLL READY
```

---

## 6) Проверка в Telegram

1. Открой @ZRG_Oblivion_bot  
2. Напиши `/start`  
3. Должно ответить меню/капча

Если не отвечает — смотри Logs на Koyeb.

---

## 7) Если ошибка в логах

### `BOT_TOKEN not set`
- Проверь Environment variable `BOT_TOKEN`
- Redeploy

### `Conflict: terminated by other getUpdates`
- Код уже уводит лишнюю копию в passive standby
- Если хочешь, чтобы работал именно Koyeb: останови другие копии и перезапусти Koyeb

### Бот засыпает / перезапускается
- Free tier иногда рестартит
- В настройках service: Restart = Always / On Failure

---

## 8) Group Privacy (чтобы группа не грузила бота)

1. @BotFather  
2. `/mybots` → @ZRG_Oblivion_bot  
3. Bot Settings → **Group Privacy → ON**  
4. Добавь бота в группу админом (если нужен счётчик входов)

---

## 9) Обновление бота потом

1. Меняешь файлы  
2. Upload / git push в GitHub  
3. Koyeb сам задеплоит (или кнопка Redeploy)

---

## Команда запуска (кратко)

```text
python bot.py
```

Env:

```text
BOT_TOKEN=XXXX:YYYY
```

---

## Мини-чеклист

- [ ] Код на GitHub  
- [ ] Koyeb service создан  
- [ ] Run: `python bot.py`  
- [ ] Env: `BOT_TOKEN`  
- [ ] Free instance  
- [ ] Deploy Running  
- [ ] `/start` в Telegram работает  
- [ ] Другие копии бота выключены  

Готово.
