# Загрузка ZRG Oblivion Bot на Amvera (cloud.amvera.ru)

Пошагово для твоего бота.

Ссылки:
- Панель: https://cloud.amvera.ru/
- Регистрация: https://amvera.ru/
- Генератор yaml: https://manifest.amvera.ru/
- Доки: https://docs.amvera.ru/

---

## Что уже готово в папке `pubg_clan_bot`

Обязательно загрузить:
- `bot.py`
- `requirements.txt`
- `amvera.yaml`

Баннеры можно загрузить двумя способами:
- папкой `assets/`, если интерфейс позволяет;
- или JPG прямо в корень рядом с `bot.py`: `about.jpg`, `admin.jpg`, `apply.jpg`, `menu.jpg`, `support.jpg`, `unmute.jpg`.

Папки `assets/` и `data/` вручную создавать не обязательно — бот сам создаст их при старте.

Не обязательно / лучше не грузить:
- `.env` (токен лучше в переменных окружения Amvera)
- `bot.log`, `*.pid`, `__pycache__`

Токен бот читает из:
1. env `BOT_TOKEN` (предпочтительно)
2. или файла `.env`

Данные (заявки/БД) пишутся в `/data` на Amvera.

---

## 1) Регистрация

1. Открой https://cloud.amvera.ru/
2. Зарегистрируйся (телефон + SMS + почта)
3. Войди в кабинет

---

## 2) Создай проект

1. Кнопка **Создать** / **Создать первый**
2. Имя проекта (латиницей лучше): `zrg-oblivion-bot`
3. Тариф: самый простой / trial (стартовых бонусов часто хватает на тест)
4. Регион: **Москва** или **Варшава** (любой ок)

---

## 3) Конфигурация запуска

### Вариант A — через готовый `amvera.yaml` (рекомендую)

В корне проекта уже есть `amvera.yaml`:

```yaml
meta:
  environment: python
  toolchain:
    name: pip
    version: "3.11"

build:
  requirementsPath: requirements.txt

run:
  scriptName: bot.py
  persistenceMount: /data
  containerPort: 80
```

### Вариант B — через генератор

1. https://manifest.amvera.ru/
2. Environment: **Python**
3. Version: **3.11**
4. requirements.txt: `requirements.txt`
5. Entry script: `bot.py`
6. Persistence folder: `/data` (или data)
7. Generate YAML → положи в корень как `amvera.yaml`

---

## 4) Переменные окружения (токен)

В проекте Amvera найди **Переменные окружения / Environment**:

| Имя | Значение |
|-----|----------|
| `BOT_TOKEN` | токен от @BotFather |
| `ADMIN_IDS` | Telegram ID админов через запятую |

Пример:
```text
BOT_TOKEN=8626829471:AAE................
```

Сохрани.

> Не публикуй токен. Если светился — сделай revoke в BotFather.

---

## 5) Загрузка файлов

### Способ 1 — через интерфейс Amvera (проще)

1. В проекте: **Файлы / Загрузка**
2. Загрузи:
   - `bot.py`
   - `requirements.txt`
   - `amvera.yaml`
   - баннеры: либо папку `assets/`, либо JPG-файлы прямо в корень
3. Папку `data/` не создавай — бот создаст её сам
4. Сохрани / задеплой

### Способ 2 — через Git push (как в Amvera)

На странице проекта будет команда вида:

```bash
git remote add amvera https://git.amvera.ru/ТВОЙ_ЛОГИН/zrg-oblivion-bot
```

Дальше на ПК в папке бота:

```bash
cd pubg_clan_bot
git init
git add bot.py requirements.txt amvera.yaml assets .gitignore
# Если папки assets нет, но JPG лежат в корне:
# git add about.jpg admin.jpg apply.jpg menu.jpg support.jpg unmute.jpg
git commit -m "deploy zrg bot"
git remote add amvera https://git.amvera.ru/ТВОЙ_ЛОГИН/ИМЯ_ПРОЕКТА
git push amvera master
```

Если у тебя ветка `main`:
```bash
git push amvera main:master
```

Логин/пароль — от аккаунта Amvera.

---

## 6) Запуск

После push/загрузки статус:
1. **Сборка**
2. **Развертывание**
3. **Успешно развернуто** / Running

Открой **Логи приложения**. Должно быть:

```text
ONLINE @ZRG_Oblivion_bot
POLL READY
```

---

## 7) Проверка в Telegram

1. Открой @ZRG_Oblivion_bot
2. `/start`
3. Должно ответить меню/капча

---

## 8) Защита от `Conflict getUpdates`

В код добавлена защита:
- две копии на одном сервере не стартуют из-за `data/bot.lock`;
- если где-то уже работает другая удалённая копия с тем же `BOT_TOKEN`, эта копия уйдёт в passive standby и перестанет опрашивать Telegram.

Чтобы активной была именно Amvera-копия:
1. выключи бота на ПК / Render / Koyeb / Arena;
2. перезапусти деплой на Amvera.

---

## 9) Что писать в настройках (шпаргалка)

| Параметр | Значение |
|----------|----------|
| Язык | Python |
| Версия | 3.11 |
| requirements | `requirements.txt` |
| Скрипт запуска | `bot.py` |
| Persistent folder | `/data` |
| Env | `BOT_TOKEN=...`, `ADMIN_IDS=...` |
| Порт | любой (не важен для polling) |

---

## 10) Частые ошибки

### `BOT_TOKEN not set`
- Не добавил переменную `BOT_TOKEN`
- Или имя не `BOT_TOKEN` (с пробелами/маленькими буквами иначе)

### Сборка висит / failed
- Нет `amvera.yaml` в корне
- Неверный `scriptName: bot.py`
- Нет `requirements.txt`

### Running, но бот молчит
1. Смотри логи приложения
2. Проверь `BOT_TOKEN`
3. Выключи другие копии бота
4. Напиши `/start` в личку

### Данные сбрасываются
- Не включён persistence `/data`
- В `amvera.yaml` должно быть: `persistenceMount: /data`

---

## Мини-чеклист

- [ ] Аккаунт cloud.amvera.ru
- [ ] Проект создан
- [ ] `amvera.yaml` в корне
- [ ] `bot.py` + `requirements.txt` загружены
- [ ] Env `BOT_TOKEN`
- [ ] Статус: успешно развернуто
- [ ] В логах: ONLINE / POLL READY
- [ ] `/start` работает
- [ ] Другие копии бота выключены

---

## Файлы, которые загружать (коротко)

```text
bot.py
requirements.txt
amvera.yaml
assets/        (если можешь загрузить папку)
```

Если папки нельзя загрузить — вместо `assets/` загрузи JPG в корень:

```text
about.jpg
admin.jpg
apply.jpg
menu.jpg
support.jpg
unmute.jpg
```

`data/` загружать не нужно — бот создаст её сам.

Опционально:
```text
AMVERA_RU.md
.gitignore
```

Не загружать:
```text
.env
bot.log
*.pid
```

Готово.
