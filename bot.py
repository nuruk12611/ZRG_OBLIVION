#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZRG Oblivion Telegram Bot

Функции:
- /start + антибот-капча на inline-кнопках
- главное меню с баннерами
- заявка в клан
- техподдержка
- обжалование мута
- админ-панель: просмотр, принятие/отклонение, закрытие, экспорт JSON

Зависимости: только стандартная библиотека Python 3.10+.
Telegram API вызывается напрямую через HTTPS long polling.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import random
import re
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
ASSET_FILES = ("about.jpg", "admin.jpg", "apply.jpg", "menu.jpg", "support.jpg", "unmute.jpg")


# ---------------------------------------------------------------------------
# ENV / CONFIG
# ---------------------------------------------------------------------------


def load_dotenv() -> None:
    """Мини-чтение .env без внешних зависимостей."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def parse_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in re.split(r"[,\s;]+", raw.strip()):
        if part and re.fullmatch(r"-?\d+", part):
            ids.add(int(part))
    return ids


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = parse_ids(os.getenv("ADMIN_IDS", ""))
CLAN_NAME = os.getenv("CLAN_NAME", "ZRG OBLIVION").strip() or "ZRG OBLIVION"
BOT_TITLE = os.getenv("BOT_TITLE", "ZRG Oblivion Bot").strip() or "ZRG Oblivion Bot"

# Для хостингов с persistent volume можно поставить DATA_DIR=/data.
# Если /data уже есть и доступна на запись — используем её автоматически.
if os.getenv("DATA_DIR"):
    DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
elif Path("/data").exists() and os.access("/data", os.W_OK):
    DATA_DIR = Path("/data")
else:
    DATA_DIR = BASE_DIR / "data"


def bootstrap_runtime_dirs() -> None:
    """Create all folders/files needed at runtime.

    This is important for GitHub/hosting deploys: Git does not keep empty
    folders, and some users upload files flat without the assets/data folders.
    The bot self-heals on start:
    - creates data/ and assets/;
    - creates empty JSON databases;
    - if JPG banners were uploaded next to bot.py, copies them into assets/.
    """
    global DATA_DIR

    # Make sure DATA_DIR is writable. If the app folder is read-only on a
    # hosting platform, fall back to /tmp so the bot still starts.
    candidates = [DATA_DIR]
    tmp_fallback = Path(os.getenv("TMPDIR") or "/tmp") / "zrg_oblivion_bot_data"
    if tmp_fallback != DATA_DIR:
        candidates.append(tmp_fallback)

    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            DATA_DIR = candidate
            break
        except Exception as exc:
            last_error = exc
    else:
        raise RuntimeError(f"Cannot create writable data directory: {last_error}")

    try:
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        # Not fatal: send_local_photo() can use JPG files from the project root.
        pass

    defaults: Dict[str, Any] = {
        "users.json": {},
        "states.json": {},
        "counters.json": {},
        "applications.json": [],
        "tickets.json": [],
        "appeals.json": [],
    }
    for filename, default in defaults.items():
        path = DATA_DIR / filename
        if not path.exists():
            path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")

    # If GitHub upload was flat, banners may be in the project root.
    # Copy them into assets/ when possible. If copying fails, send_local_photo()
    # still has a root-file fallback.
    for filename in ASSET_FILES:
        dst = ASSETS_DIR / filename
        if dst.exists():
            continue
        for src in (BASE_DIR / filename, BASE_DIR / "uploads" / filename):
            if src.exists() and src.is_file():
                try:
                    dst.write_bytes(src.read_bytes())
                except Exception:
                    pass
                break


bootstrap_runtime_dirs()

LOG_FILE = DATA_DIR / "bot.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/"

# Exit codes used by run_forever.py
EXIT_TELEGRAM_CONFLICT = 75
EXIT_ALREADY_RUNNING = 76

# If another remote copy is already polling Telegram, this instance goes into
# passive standby by default instead of fighting/restarting forever.
# Set CONFLICT_MODE=exit if you prefer the process to stop immediately.
CONFLICT_MODE = os.getenv("CONFLICT_MODE", "standby").strip().lower() or "standby"

_LOCK_HANDLE: Any = None


def acquire_single_instance_lock() -> bool:
    """Prevent two copies on the same PC/VPS/container.

    Telegram still allows only one active long-polling instance globally per
    token. This lock fixes accidental double-clicks / two processes on the
    same machine; remote duplicates are handled by conflict standby below.
    """
    global _LOCK_HANDLE
    lock_path = DATA_DIR / "bot.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _LOCK_HANDLE = open(lock_path, "a+", encoding="utf-8")
    try:
        _LOCK_HANDLE.seek(0)
        if os.name == "nt":
            import msvcrt  # type: ignore

            msvcrt.locking(_LOCK_HANDLE.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # type: ignore

            fcntl.flock(_LOCK_HANDLE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            _LOCK_HANDLE.close()
        except Exception:
            pass
        _LOCK_HANDLE = None
        return False

    _LOCK_HANDLE.seek(0)
    _LOCK_HANDLE.truncate()
    _LOCK_HANDLE.write(f"pid={os.getpid()}\nstarted_at={now_str()}\ndata_dir={DATA_DIR}\n")
    _LOCK_HANDLE.flush()
    return True


def conflict_standby(reason: str) -> None:
    """Stop polling when Telegram reports a duplicate getUpdates consumer."""
    message = (
        "DUPLICATE BOT INSTANCE DETECTED: another copy is already using "
        "getUpdates for this BOT_TOKEN. This instance will not poll Telegram. "
        "Stop the duplicate copy or restart this instance after the active copy is stopped."
    )
    print("\n" + "=" * 72, flush=True)
    print(message, flush=True)
    print(f"Telegram error: {reason}", flush=True)
    print("=" * 72 + "\n", flush=True)
    logging.error("%s Telegram error: %s", message, reason)

    if CONFLICT_MODE == "exit":
        sys.exit(EXIT_TELEGRAM_CONFLICT)

    print("STANDBY MODE: sleeping forever to avoid Conflict getUpdates loop.", flush=True)
    while True:
        time.sleep(3600)


# ---------------------------------------------------------------------------
# JSON STORAGE
# ---------------------------------------------------------------------------


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def json_path(name: str) -> Path:
    return DATA_DIR / name


def read_json(name: str, default: Any) -> Any:
    path = json_path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logging.exception("Cannot read JSON: %s", path)
        return default


def write_json(name: str, data: Any) -> None:
    path = json_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def next_id(kind: str) -> int:
    counters = read_json("counters.json", {})
    counters[kind] = int(counters.get(kind, 0)) + 1
    write_json("counters.json", counters)
    return counters[kind]


def append_record(filename: str, item: Dict[str, Any]) -> None:
    items = read_json(filename, [])
    items.append(item)
    write_json(filename, items)


def update_record(filename: str, item_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    items = read_json(filename, [])
    found: Optional[Dict[str, Any]] = None
    for item in items:
        if int(item.get("id", -1)) == int(item_id):
            item.update(updates)
            found = item
            break
    if found is not None:
        write_json(filename, items)
    return found


def get_state(user_id: int) -> Optional[Dict[str, Any]]:
    states = read_json("states.json", {})
    state = states.get(str(user_id))
    return state if isinstance(state, dict) else None


def set_state(user_id: int, state: Dict[str, Any]) -> None:
    states = read_json("states.json", {})
    states[str(user_id)] = state
    write_json("states.json", states)


def clear_state(user_id: int) -> None:
    states = read_json("states.json", {})
    if str(user_id) in states:
        del states[str(user_id)]
        write_json("states.json", states)


def get_user(user_id: int) -> Dict[str, Any]:
    users = read_json("users.json", {})
    rec = users.get(str(user_id))
    if not isinstance(rec, dict):
        rec = {"captcha_ok": False, "created_at": now_str()}
        users[str(user_id)] = rec
        write_json("users.json", users)
    return rec


def save_user(user_id: int, rec: Dict[str, Any]) -> None:
    users = read_json("users.json", {})
    users[str(user_id)] = rec
    write_json("users.json", users)


def is_verified(user_id: int) -> bool:
    return bool(get_user(user_id).get("captcha_ok"))


def set_verified(user_id: int, value: bool) -> None:
    rec = get_user(user_id)
    rec["captcha_ok"] = bool(value)
    if value:
        rec.pop("captcha", None)
        rec["verified_at"] = now_str()
    save_user(user_id, rec)


def is_admin(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS


# ---------------------------------------------------------------------------
# TELEGRAM API
# ---------------------------------------------------------------------------


class BotAPIError(RuntimeError):
    pass


def multipart_body(params: Dict[str, Any], files: Dict[str, Tuple[str, bytes, str]]) -> Tuple[bytes, str]:
    boundary = "----ZRGOblivion" + uuid.uuid4().hex
    chunks: List[bytes] = []

    def add(line: str | bytes) -> None:
        if isinstance(line, str):
            chunks.append(line.encode("utf-8"))
        else:
            chunks.append(line)

    for key, value in params.items():
        if value is None:
            continue
        add(f"--{boundary}\r\n")
        add(f'Content-Disposition: form-data; name="{key}"\r\n\r\n')
        add(str(value))
        add("\r\n")

    for key, (filename, data, content_type) in files.items():
        add(f"--{boundary}\r\n")
        add(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"\r\n')
        add(f"Content-Type: {content_type}\r\n\r\n")
        add(data)
        add("\r\n")

    add(f"--{boundary}--\r\n")
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def api(method: str, params: Optional[Dict[str, Any]] = None, files: Optional[Dict[str, Tuple[str, bytes, str]]] = None) -> Any:
    if not BOT_TOKEN:
        raise BotAPIError("BOT_TOKEN not set")

    params = params or {}
    url = API_URL + method

    if files:
        body, content_type = multipart_body(params, files)
        headers = {"Content-Type": content_type}
    else:
        body = urllib.parse.urlencode(params).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=70) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise BotAPIError(f"{method}: HTTP {e.code}: {raw}") from e
    except Exception as e:
        raise BotAPIError(f"{method}: {e}") from e

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BotAPIError(f"{method}: invalid JSON: {raw[:500]}") from e

    if not data.get("ok"):
        raise BotAPIError(f"{method}: {data}")
    return data.get("result")


def dumps_markup(markup: Optional[Dict[str, Any]]) -> Optional[str]:
    if not markup:
        return None
    return json.dumps(markup, ensure_ascii=False)


def safe_caption(text: str, limit: int = 1000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def send_message(chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "HTML") -> Any:
    params: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_markup:
        params["reply_markup"] = dumps_markup(reply_markup)
    return api("sendMessage", params)


def edit_message_reply_markup(chat_id: int, message_id: int) -> None:
    try:
        api(
            "editMessageReplyMarkup",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": json.dumps({"inline_keyboard": []}, ensure_ascii=False),
            },
        )
    except Exception:
        logging.exception("Cannot edit reply markup")


def resolve_asset_path(image_name: str) -> Path:
    """Find a banner in assets/ or in the project root.

    Root fallback lets the bot work even if files were uploaded to GitHub
    without folders: about.jpg, admin.jpg, etc. can lie next to bot.py.
    """
    for path in (ASSETS_DIR / image_name, BASE_DIR / image_name, BASE_DIR / "uploads" / image_name):
        if path.exists() and path.is_file():
            return path
    return ASSETS_DIR / image_name


def send_local_photo(
    chat_id: int,
    image_name: str,
    caption: str = "",
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: str = "HTML",
) -> Any:
    path = resolve_asset_path(image_name)
    if not path.exists():
        return send_message(chat_id, caption or "Изображение не найдено.", reply_markup=reply_markup, parse_mode=parse_mode)

    content_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    params: Dict[str, Any] = {"chat_id": chat_id}
    if caption:
        params["caption"] = safe_caption(caption)
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_markup:
        params["reply_markup"] = dumps_markup(reply_markup)

    return api("sendPhoto", params, files={"photo": (path.name, path.read_bytes(), content_type)})


def send_photo_id(
    chat_id: int,
    file_id: str,
    caption: str = "",
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: str = "HTML",
) -> Any:
    params: Dict[str, Any] = {"chat_id": chat_id, "photo": file_id}
    if caption:
        params["caption"] = safe_caption(caption)
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_markup:
        params["reply_markup"] = dumps_markup(reply_markup)
    return api("sendPhoto", params)


def send_document_id(
    chat_id: int,
    file_id: str,
    caption: str = "",
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: str = "HTML",
) -> Any:
    params: Dict[str, Any] = {"chat_id": chat_id, "document": file_id}
    if caption:
        params["caption"] = safe_caption(caption)
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_markup:
        params["reply_markup"] = dumps_markup(reply_markup)
    return api("sendDocument", params)


def send_local_document(chat_id: int, path: Path, caption: str = "") -> Any:
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    params: Dict[str, Any] = {"chat_id": chat_id}
    if caption:
        params["caption"] = safe_caption(caption)
        params["parse_mode"] = "HTML"
    return api("sendDocument", params, files={"document": (path.name, path.read_bytes(), content_type)})


def answer_callback(callback_id: str, text: str = "", show_alert: bool = False) -> None:
    params = {"callback_query_id": callback_id, "text": text, "show_alert": "true" if show_alert else "false"}
    try:
        api("answerCallbackQuery", params)
    except Exception:
        logging.exception("answerCallbackQuery failed")


# ---------------------------------------------------------------------------
# KEYBOARDS / TEXT HELPERS
# ---------------------------------------------------------------------------


def btn(text: str, data: Optional[str] = None, url: Optional[str] = None) -> Dict[str, str]:
    button: Dict[str, str] = {"text": text}
    if url:
        button["url"] = url
    else:
        button["callback_data"] = data or "noop"
    return button


def kb(rows: List[List[Dict[str, str]]]) -> Dict[str, Any]:
    return {"inline_keyboard": rows}


def menu_keyboard(user_id: int) -> Dict[str, Any]:
    rows = [
        [btn("🛡️ О клане", "menu:about"), btn("📝 Заявка в клан", "menu:apply")],
        [btn("🎓 Академия", "menu:academy"), btn("🎧 Техподдержка", "menu:support")],
        [btn("📣 Обжалование мута", "menu:unmute")],
    ]
    if is_admin(user_id):
        rows.append([btn("🔐 Админ панель", "admin:panel")])
    return kb(rows)


def cancel_keyboard() -> Dict[str, Any]:
    return kb([[btn("❌ Отмена", "form:cancel"), btn("🏠 Меню", "menu:home")]])


def back_keyboard(user_id: int) -> Dict[str, Any]:
    rows = [[btn("🏠 Главное меню", "menu:home")]]
    if is_admin(user_id):
        rows.append([btn("🔐 Админ панель", "admin:panel")])
    return kb(rows)


def user_display(user: Dict[str, Any]) -> str:
    first = user.get("first_name") or ""
    last = user.get("last_name") or ""
    name = " ".join([x for x in [first, last] if x]).strip() or user.get("username") or str(user.get("id", ""))
    username = user.get("username")
    if username:
        return f"{escape(name)} (@{escape(username)})"
    return escape(name)


def user_link(user_id: int, label: Optional[str] = None) -> str:
    return f'<a href="tg://user?id={int(user_id)}">{escape(label or str(user_id))}</a>'


def get_text(message: Dict[str, Any]) -> str:
    return (message.get("text") or message.get("caption") or "").strip()


def get_attachment(message: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """Возвращает (type, file_id) для фото/документа."""
    if message.get("photo"):
        photo = message["photo"][-1]
        return "photo", photo.get("file_id")
    if message.get("document"):
        return "document", message["document"].get("file_id")
    return None, None


# ---------------------------------------------------------------------------
# CAPTCHA
# ---------------------------------------------------------------------------


CAPTCHA = [
    ("helmet", "🪖"),
    ("target", "🎯"),
    ("fire", "🔥"),
    ("bolt", "⚡"),
    ("shield", "🛡️"),
    ("gem", "💎"),
]
CAPTCHA_MAP = {key: emoji for key, emoji in CAPTCHA}


def send_captcha(chat_id: int, user_id: int) -> None:
    sequence = [key for key, _ in random.sample(CAPTCHA, 4)]
    rec = get_user(user_id)
    rec["captcha_ok"] = False
    rec["captcha"] = {"sequence": sequence, "progress": 0, "created_at": time.time()}
    save_user(user_id, rec)

    buttons = CAPTCHA[:]
    random.shuffle(buttons)
    rows: List[List[Dict[str, str]]] = []
    for i in range(0, len(buttons), 3):
        rows.append([btn(emoji, f"cap:{key}") for key, emoji in buttons[i : i + 3]])

    order = "  ".join(CAPTCHA_MAP[key] for key in sequence)
    text = (
        f"<b>🛡️ Антибот-проверка {escape(CLAN_NAME)}</b>\n\n"
        "Нажми кнопки <b>строго в таком порядке</b>:\n\n"
        f"<code>{escape(order)}</code>\n\n"
        "Если ошибёшься — бот выдаст новую комбинацию."
    )
    send_message(chat_id, text, reply_markup=kb(rows))


def handle_captcha_callback(cq: Dict[str, Any]) -> None:
    data = cq.get("data", "")
    callback_id = cq.get("id", "")
    choice = data.split(":", 1)[1] if ":" in data else ""
    user = cq.get("from", {})
    user_id = int(user.get("id"))
    message = cq.get("message", {})
    chat_id = int(message.get("chat", {}).get("id", user_id))

    rec = get_user(user_id)
    if rec.get("captcha_ok"):
        answer_callback(callback_id, "✅ Проверка уже пройдена")
        return

    captcha = rec.get("captcha") or {}
    sequence = captcha.get("sequence") or []
    progress = int(captcha.get("progress") or 0)

    if not sequence or progress >= len(sequence):
        answer_callback(callback_id, "Капча устарела. Новая проверка.", True)
        send_captcha(chat_id, user_id)
        return

    expected = sequence[progress]
    if choice == expected:
        progress += 1
        if progress >= len(sequence):
            set_verified(user_id, True)
            clear_state(user_id)
            answer_callback(callback_id, "✅ Доступ открыт")
            send_main_menu(chat_id, user_id)
        else:
            rec["captcha"]["progress"] = progress
            save_user(user_id, rec)
            answer_callback(callback_id, f"Верно: {progress}/{len(sequence)}")
    else:
        rec["captcha"] = {"sequence": [], "progress": 0, "created_at": time.time()}
        save_user(user_id, rec)
        answer_callback(callback_id, "❌ Ошибка. Выдана новая капча.", True)
        send_captcha(chat_id, user_id)


def ensure_access(chat_id: int, user_id: int) -> bool:
    if is_verified(user_id):
        return True
    send_captcha(chat_id, user_id)
    return False


# ---------------------------------------------------------------------------
# MENU SECTIONS
# ---------------------------------------------------------------------------


def send_main_menu(chat_id: int, user_id: int) -> None:
    text = (
        f"<b>⚔️ {escape(CLAN_NAME)}</b>\n"
        "PUBG Mobile clan bot\n\n"
        "Выбери нужный раздел:\n"
        "• информация о клане\n"
        "• заявка в состав\n"
        "• академия\n"
        "• техподдержка\n"
        "• обжалование мута\n\n"
        "Команды: /menu, /id, /cancel"
    )
    send_local_photo(chat_id, "about.jpg", text, reply_markup=menu_keyboard(user_id))


def send_about(chat_id: int, user_id: int) -> None:
    text = (
        f"<b>🛡️ О клане {escape(CLAN_NAME)}</b>\n\n"
        "ZRG Oblivion — игровое сообщество PUBG Mobile с упором на командную игру, дисциплину и развитие состава.\n\n"
        "<b>Что ценим:</b>\n"
        "• активность и адекватность\n"
        "• уважение к тиммейтам\n"
        "• желание играть и расти\n"
        "• соблюдение правил клана и чата\n\n"
        "Хочешь к нам? Нажми «Заявка в клан»."
    )
    send_local_photo(chat_id, "about.jpg", text, reply_markup=kb([[btn("📝 Заявка в клан", "menu:apply")], [btn("🏠 Меню", "menu:home")]]))


def send_academy(chat_id: int, user_id: int) -> None:
    text = (
        f"<b>🎓 {escape(CLAN_NAME)} Академия</b>\n\n"
        "Академия — место для игроков, которые хотят подтянуть игру, командное взаимодействие и дисциплину.\n\n"
        "<b>Подходит, если:</b>\n"
        "• хочешь попасть в основной состав\n"
        "• готов тренироваться\n"
        "• нужен опыт игры в команде\n\n"
        "Чтобы начать — подай заявку, а администраторы решат, куда тебя направить."
    )
    send_local_photo(chat_id, "menu.jpg", text, reply_markup=kb([[btn("📝 Подать заявку", "menu:apply")], [btn("🏠 Меню", "menu:home")]]))


def send_admin_denied(chat_id: int, user_id: int) -> None:
    setup_hint = ""
    if not ADMIN_IDS:
        setup_hint = (
            "\n\n<b>Админы ещё не настроены.</b>\n"
            f"Твой Telegram ID: <code>{user_id}</code>\n"
            "Добавь в переменные окружения:\n"
            f"<code>ADMIN_IDS={user_id}</code>"
        )
    text = "<b>🔒 Доступ ограничен</b>\nТолько для авторизованных администраторов." + setup_hint
    send_local_photo(chat_id, "admin.jpg", text, reply_markup=back_keyboard(user_id))


# ---------------------------------------------------------------------------
# APPLICATION FORM
# ---------------------------------------------------------------------------


APPLICATION_FIELDS = [
    ("nickname", "Никнейм (IGN)", "Напиши игровой никнейм (IGN):"),
    ("game_id", "ID в игре", "Напиши числовой ID в PUBG Mobile:"),
    ("level", "Уровень (LVL)", "Напиши уровень аккаунта (LVL):"),
    ("kd", "K/D ratio", "Напиши K/D ratio, например: 2.15"),
    ("role", "Роль (Role)", "Выбери роль кнопкой или напиши свою:"),
]
FIELD_INDEX = {key: i for i, (key, _, _) in enumerate(APPLICATION_FIELDS)}
ROLE_OPTIONS = {
    "assault": "Штурмовик",
    "sniper": "Снайпер",
    "support": "Поддержка",
    "universal": "Универсал",
}


def role_keyboard() -> Dict[str, Any]:
    return kb(
        [
            [btn("⚔️ Штурмовик", "role:assault"), btn("🎯 Снайпер", "role:sniper")],
            [btn("🛡️ Поддержка", "role:support"), btn("🔄 Универсал", "role:universal")],
            [btn("❌ Отмена", "form:cancel")],
        ]
    )


def start_application(chat_id: int, user_id: int) -> None:
    state = {"flow": "application", "step": "nickname", "answers": {}, "created_at": now_str()}
    set_state(user_id, state)
    text = (
        "<b>📝 Заявка в клан</b>\n\n"
        "Ответь на несколько вопросов. После заполнения бот покажет анкету для подтверждения.\n\n"
        "1/5 — <b>Никнейм (IGN)</b>\n"
        "Напиши игровой никнейм:"
    )
    send_local_photo(chat_id, "apply.jpg", text, reply_markup=cancel_keyboard())


def validate_application_field(key: str, value: str) -> Tuple[bool, str, str]:
    value = value.strip()
    if key == "nickname":
        if not (2 <= len(value) <= 32):
            return False, value, "Ник должен быть от 2 до 32 символов. Попробуй ещё раз:"
        return True, value, ""
    if key == "game_id":
        cleaned = value.replace(" ", "")
        if not cleaned.isdigit() or not (5 <= len(cleaned) <= 15):
            return False, value, "ID должен быть числом, обычно 5–15 цифр. Напиши ID ещё раз:"
        return True, cleaned, ""
    if key == "level":
        if not value.isdigit():
            return False, value, "Уровень должен быть числом. Напиши LVL ещё раз:"
        lvl = int(value)
        if not (1 <= lvl <= 150):
            return False, value, "Уровень выглядит странно. Напиши число от 1 до 150:"
        return True, str(lvl), ""
    if key == "kd":
        normalized = value.replace(",", ".")
        try:
            kd = float(normalized)
        except ValueError:
            return False, value, "K/D должен быть числом, например 2.15. Попробуй ещё раз:"
        if not (0 <= kd <= 100):
            return False, value, "K/D выглядит странно. Напиши корректное число:"
        return True, f"{kd:.2f}".rstrip("0").rstrip("."), ""
    if key == "role":
        if not value or len(value) > 40:
            return False, value, "Роль должна быть коротким текстом. Напиши роль ещё раз:"
        return True, value, ""
    return True, value, ""


def application_summary(answers: Dict[str, Any], title: str = "Анкета") -> str:
    lines = [f"<b>{escape(title)}</b>"]
    for key, label, _ in APPLICATION_FIELDS:
        lines.append(f"<b>{escape(label)}:</b> {escape(str(answers.get(key, '—')))}")
    return "\n".join(lines)


def ask_next_application_step(chat_id: int, user_id: int, state: Dict[str, Any]) -> None:
    step = state.get("step")
    idx = FIELD_INDEX[step]
    _, label, prompt = APPLICATION_FIELDS[idx]
    prefix = f"{idx + 1}/5 — <b>{escape(label)}</b>\n"
    if step == "role":
        send_message(chat_id, prefix + escape(prompt), reply_markup=role_keyboard())
    else:
        send_message(chat_id, prefix + escape(prompt), reply_markup=cancel_keyboard())


def process_application_message(message: Dict[str, Any], state: Dict[str, Any]) -> None:
    user = message.get("from", {})
    user_id = int(user.get("id"))
    chat_id = int(message["chat"]["id"])
    text = get_text(message)

    step = state.get("step")
    if step == "confirm":
        send_message(chat_id, "Проверь анкету и нажми кнопку подтверждения ниже.", reply_markup=confirm_application_keyboard())
        return
    if step not in FIELD_INDEX:
        clear_state(user_id)
        send_message(chat_id, "Анкета сброшена. Начни заново через меню.", reply_markup=menu_keyboard(user_id))
        return
    if not text:
        send_message(chat_id, "Нужно отправить ответ текстом.", reply_markup=cancel_keyboard())
        return

    ok, value, error = validate_application_field(step, text)
    if not ok:
        send_message(chat_id, escape(error), reply_markup=cancel_keyboard())
        return

    answers = state.setdefault("answers", {})
    answers[step] = value
    idx = FIELD_INDEX[step]
    if idx + 1 < len(APPLICATION_FIELDS):
        state["step"] = APPLICATION_FIELDS[idx + 1][0]
        set_state(user_id, state)
        ask_next_application_step(chat_id, user_id, state)
    else:
        state["step"] = "confirm"
        set_state(user_id, state)
        send_message(chat_id, application_summary(answers, "Проверь заявку"), reply_markup=confirm_application_keyboard())


def confirm_application_keyboard() -> Dict[str, Any]:
    return kb([[btn("✅ Отправить", "form:app:confirm"), btn("❌ Отмена", "form:cancel")]])


def process_role_callback(cq: Dict[str, Any]) -> None:
    callback_id = cq.get("id", "")
    data = cq.get("data", "")
    role_key = data.split(":", 1)[1] if ":" in data else ""
    role = ROLE_OPTIONS.get(role_key)
    user = cq.get("from", {})
    user_id = int(user.get("id"))
    chat_id = int(cq.get("message", {}).get("chat", {}).get("id", user_id))

    state = get_state(user_id)
    if not state or state.get("flow") != "application" or state.get("step") != "role" or not role:
        answer_callback(callback_id, "Эта кнопка уже неактивна.")
        return
    state.setdefault("answers", {})["role"] = role
    state["step"] = "confirm"
    set_state(user_id, state)
    answer_callback(callback_id, "Роль выбрана")
    send_message(chat_id, application_summary(state["answers"], "Проверь заявку"), reply_markup=confirm_application_keyboard())


def finalize_application(cq: Dict[str, Any]) -> None:
    callback_id = cq.get("id", "")
    user = cq.get("from", {})
    user_id = int(user.get("id"))
    chat_id = int(cq.get("message", {}).get("chat", {}).get("id", user_id))
    state = get_state(user_id)

    if not state or state.get("flow") != "application" or state.get("step") != "confirm":
        answer_callback(callback_id, "Заявка не найдена или уже отправлена.", True)
        return

    answers = state.get("answers") or {}
    app_id = next_id("application")
    item = {
        "id": app_id,
        "status": "new",
        "created_at": now_str(),
        "user_id": user_id,
        "username": user.get("username"),
        "full_name": (" ".join(x for x in [user.get("first_name"), user.get("last_name")] if x)).strip(),
        "answers": answers,
    }
    append_record("applications.json", item)
    clear_state(user_id)
    answer_callback(callback_id, "Заявка отправлена")
    send_message(
        chat_id,
        f"✅ Заявка <b>#{app_id}</b> отправлена администраторам.\nОжидай решения в Telegram.",
        reply_markup=back_keyboard(user_id),
    )
    notify_admins_application(item)


# ---------------------------------------------------------------------------
# SUPPORT / UNMUTE FORMS
# ---------------------------------------------------------------------------


def start_support(chat_id: int, user_id: int) -> None:
    set_state(user_id, {"flow": "support", "step": "message", "created_at": now_str()})
    text = (
        "<b>🎧 Техподдержка</b>\n\n"
        "Опиши проблему одним сообщением. Можно приложить фото/скриншот с подписью.\n\n"
        "Пример: что случилось, где, когда, какой ник/ID."
    )
    send_local_photo(chat_id, "support.jpg", text, reply_markup=cancel_keyboard())


def finalize_support(message: Dict[str, Any], state: Dict[str, Any]) -> None:
    user = message.get("from", {})
    user_id = int(user.get("id"))
    chat_id = int(message["chat"]["id"])
    text = get_text(message)
    att_type, file_id = get_attachment(message)
    if not text and not file_id:
        send_message(chat_id, "Опиши проблему текстом или отправь скриншот с подписью.", reply_markup=cancel_keyboard())
        return

    ticket_id = next_id("ticket")
    item = {
        "id": ticket_id,
        "status": "new",
        "created_at": now_str(),
        "user_id": user_id,
        "username": user.get("username"),
        "full_name": (" ".join(x for x in [user.get("first_name"), user.get("last_name")] if x)).strip(),
        "text": text or "Скриншот без подписи",
        "attachment_type": att_type,
        "file_id": file_id,
    }
    append_record("tickets.json", item)
    clear_state(user_id)
    send_message(chat_id, f"✅ Обращение в техподдержку <b>#{ticket_id}</b> создано. Админы ответят при первой возможности.", reply_markup=back_keyboard(user_id))
    notify_admins_ticket(item)


UNMUTE_FIELDS = [
    ("nickname", "Никнейм / ID", "Напиши никнейм и игровой ID:"),
    ("where", "Где и когда мут", "Где и когда получил мут? Укажи чат, дату и примерное время:"),
    ("reason", "Причина обжалования", "Опиши ситуацию и почему мут нужно снять. Можно приложить скриншот."),
]
UNMUTE_INDEX = {key: i for i, (key, _, _) in enumerate(UNMUTE_FIELDS)}


def start_unmute(chat_id: int, user_id: int) -> None:
    set_state(user_id, {"flow": "unmute", "step": "nickname", "answers": {}, "created_at": now_str()})
    text = (
        "<b>📣 Обжалование мута</b>\n\n"
        "Заполни короткую форму. Админы получат обращение и примут решение.\n\n"
        "1/3 — <b>Никнейм / ID</b>\n"
        "Напиши никнейм и игровой ID:"
    )
    send_local_photo(chat_id, "unmute.jpg", text, reply_markup=cancel_keyboard())


def process_unmute_message(message: Dict[str, Any], state: Dict[str, Any]) -> None:
    user = message.get("from", {})
    user_id = int(user.get("id"))
    chat_id = int(message["chat"]["id"])
    text = get_text(message)
    att_type, file_id = get_attachment(message)
    step = state.get("step")

    if step not in UNMUTE_INDEX:
        clear_state(user_id)
        send_message(chat_id, "Форма сброшена. Начни заново через меню.", reply_markup=menu_keyboard(user_id))
        return

    if not text and not file_id:
        send_message(chat_id, "Нужно отправить текст. На последнем шаге можно также приложить скриншот.", reply_markup=cancel_keyboard())
        return

    answers = state.setdefault("answers", {})
    answers[step] = text or "Скриншот без подписи"
    if file_id:
        state["attachment_type"] = att_type
        state["file_id"] = file_id

    idx = UNMUTE_INDEX[step]
    if idx + 1 < len(UNMUTE_FIELDS):
        state["step"] = UNMUTE_FIELDS[idx + 1][0]
        set_state(user_id, state)
        _, label, prompt = UNMUTE_FIELDS[idx + 1]
        send_message(chat_id, f"{idx + 2}/3 — <b>{escape(label)}</b>\n{escape(prompt)}", reply_markup=cancel_keyboard())
        return

    appeal_id = next_id("appeal")
    item = {
        "id": appeal_id,
        "status": "new",
        "created_at": now_str(),
        "user_id": user_id,
        "username": user.get("username"),
        "full_name": (" ".join(x for x in [user.get("first_name"), user.get("last_name")] if x)).strip(),
        "answers": answers,
        "attachment_type": state.get("attachment_type"),
        "file_id": state.get("file_id"),
    }
    append_record("appeals.json", item)
    clear_state(user_id)
    send_message(chat_id, f"✅ Обжалование мута <b>#{appeal_id}</b> отправлено администраторам.", reply_markup=back_keyboard(user_id))
    notify_admins_appeal(item)


# ---------------------------------------------------------------------------
# ADMIN NOTIFICATIONS / PANEL
# ---------------------------------------------------------------------------


STATUS_LABELS = {
    "new": "🟡 новая",
    "approved": "✅ принято",
    "rejected": "❌ отклонено",
    "closed": "✅ закрыто",
}


def admin_action_keyboard(kind: str, item: Dict[str, Any]) -> Dict[str, Any]:
    item_id = int(item["id"])
    user_id = int(item.get("user_id") or 0)
    rows: List[List[Dict[str, str]]] = []
    if kind == "application":
        rows.append([btn("✅ Принять", f"admin:application:approve:{item_id}"), btn("❌ Отклонить", f"admin:application:reject:{item_id}")])
    elif kind == "ticket":
        rows.append([btn("✅ Закрыть", f"admin:ticket:close:{item_id}")])
    elif kind == "appeal":
        rows.append([btn("✅ Одобрить", f"admin:appeal:approve:{item_id}"), btn("❌ Отклонить", f"admin:appeal:reject:{item_id}")])
    if user_id:
        rows.append([btn("👤 Написать пользователю", url=f"tg://user?id={user_id}")])
    rows.append([btn("🔐 Админ панель", "admin:panel")])
    return kb(rows)


def format_application_item(item: Dict[str, Any]) -> str:
    answers = item.get("answers") or {}
    user_id = int(item.get("user_id") or 0)
    status = STATUS_LABELS.get(item.get("status", "new"), item.get("status", "new"))
    text = [
        f"<b>📝 Заявка #{item.get('id')}</b>",
        f"<b>Статус:</b> {escape(status)}",
        f"<b>Дата:</b> {escape(str(item.get('created_at', '—')))}",
        f"<b>Пользователь:</b> {user_link(user_id, item.get('full_name') or str(user_id))}",
    ]
    if item.get("username"):
        text.append(f"<b>Username:</b> @{escape(str(item.get('username')))}")
    text.append("")
    text.append(application_summary(answers, "Анкета"))
    return "\n".join(text)


def format_ticket_item(item: Dict[str, Any]) -> str:
    user_id = int(item.get("user_id") or 0)
    status = STATUS_LABELS.get(item.get("status", "new"), item.get("status", "new"))
    text = [
        f"<b>🎧 Тикет #{item.get('id')}</b>",
        f"<b>Статус:</b> {escape(status)}",
        f"<b>Дата:</b> {escape(str(item.get('created_at', '—')))}",
        f"<b>Пользователь:</b> {user_link(user_id, item.get('full_name') or str(user_id))}",
    ]
    if item.get("username"):
        text.append(f"<b>Username:</b> @{escape(str(item.get('username')))}")
    text.extend(["", f"<b>Сообщение:</b>\n{escape(str(item.get('text', '—')))}"])
    return "\n".join(text)


def format_appeal_item(item: Dict[str, Any]) -> str:
    answers = item.get("answers") or {}
    user_id = int(item.get("user_id") or 0)
    status = STATUS_LABELS.get(item.get("status", "new"), item.get("status", "new"))
    labels = dict((k, v) for k, v, _ in UNMUTE_FIELDS)
    text = [
        f"<b>📣 Обжалование мута #{item.get('id')}</b>",
        f"<b>Статус:</b> {escape(status)}",
        f"<b>Дата:</b> {escape(str(item.get('created_at', '—')))}",
        f"<b>Пользователь:</b> {user_link(user_id, item.get('full_name') or str(user_id))}",
    ]
    if item.get("username"):
        text.append(f"<b>Username:</b> @{escape(str(item.get('username')))}")
    text.append("")
    for key, label in labels.items():
        text.append(f"<b>{escape(label)}:</b> {escape(str(answers.get(key, '—')))}")
    return "\n".join(text)


def notify_admins(text: str, keyboard: Optional[Dict[str, Any]] = None, attachment_type: Optional[str] = None, file_id: Optional[str] = None) -> None:
    if not ADMIN_IDS:
        logging.warning("ADMIN_IDS is empty; admin notification was not sent")
        return
    for admin_id in ADMIN_IDS:
        try:
            if attachment_type == "photo" and file_id:
                if len(text) <= 1000:
                    send_photo_id(admin_id, file_id, text, reply_markup=keyboard)
                else:
                    send_photo_id(admin_id, file_id, "📎 Скриншот к обращению")
                    send_message(admin_id, text, reply_markup=keyboard)
            elif attachment_type == "document" and file_id:
                send_document_id(admin_id, file_id, "📎 Документ к обращению")
                send_message(admin_id, text, reply_markup=keyboard)
            else:
                send_message(admin_id, text, reply_markup=keyboard)
        except Exception as e:
            logging.error("Cannot notify admin %s: %s", admin_id, e)


def notify_admins_application(item: Dict[str, Any]) -> None:
    notify_admins(format_application_item(item), keyboard=admin_action_keyboard("application", item))


def notify_admins_ticket(item: Dict[str, Any]) -> None:
    notify_admins(format_ticket_item(item), keyboard=admin_action_keyboard("ticket", item), attachment_type=item.get("attachment_type"), file_id=item.get("file_id"))


def notify_admins_appeal(item: Dict[str, Any]) -> None:
    notify_admins(format_appeal_item(item), keyboard=admin_action_keyboard("appeal", item), attachment_type=item.get("attachment_type"), file_id=item.get("file_id"))


def stats_text() -> str:
    apps = read_json("applications.json", [])
    tickets = read_json("tickets.json", [])
    appeals = read_json("appeals.json", [])

    def count_new(items: Iterable[Dict[str, Any]]) -> int:
        return sum(1 for x in items if x.get("status") == "new")

    return (
        "<b>🔐 Админ панель</b>\n\n"
        f"<b>Заявки в клан:</b> {count_new(apps)} новых / {len(apps)} всего\n"
        f"<b>Техподдержка:</b> {count_new(tickets)} новых / {len(tickets)} всего\n"
        f"<b>Обжалования мута:</b> {count_new(appeals)} новых / {len(appeals)} всего\n\n"
        f"<b>Админы:</b> {', '.join(str(x) for x in sorted(ADMIN_IDS)) or 'не настроены'}\n"
        f"<b>DATA_DIR:</b> <code>{escape(str(DATA_DIR))}</code>"
    )


def admin_panel_keyboard() -> Dict[str, Any]:
    apps = read_json("applications.json", [])
    tickets = read_json("tickets.json", [])
    appeals = read_json("appeals.json", [])

    def new_count(items: Iterable[Dict[str, Any]]) -> int:
        return sum(1 for x in items if x.get("status") == "new")

    return kb(
        [
            [btn(f"📝 Заявки ({new_count(apps)})", "admin:list:applications")],
            [btn(f"🎧 Тикеты ({new_count(tickets)})", "admin:list:tickets")],
            [btn(f"📣 Муты ({new_count(appeals)})", "admin:list:appeals")],
            [btn("📦 Экспорт JSON", "admin:export"), btn("🔄 Обновить", "admin:panel")],
            [btn("🏠 Главное меню", "menu:home")],
        ]
    )


def send_admin_panel(chat_id: int, user_id: int) -> None:
    if not is_admin(user_id):
        send_admin_denied(chat_id, user_id)
        return
    send_local_photo(chat_id, "admin.jpg", stats_text(), reply_markup=admin_panel_keyboard())


def admin_send_list(chat_id: int, kind: str) -> None:
    mapping = {
        "applications": ("applications.json", "application", "📝 Заявки"),
        "tickets": ("tickets.json", "ticket", "🎧 Тикеты"),
        "appeals": ("appeals.json", "appeal", "📣 Обжалования мута"),
    }
    if kind not in mapping:
        send_message(chat_id, "Неизвестный список.", reply_markup=admin_panel_keyboard())
        return
    filename, item_kind, title = mapping[kind]
    items = read_json(filename, [])
    if not items:
        send_message(chat_id, f"<b>{title}</b>\nСписок пуст.", reply_markup=admin_panel_keyboard())
        return

    def sort_key(x: Dict[str, Any]) -> Tuple[int, int]:
        return (0 if x.get("status") == "new" else 1, -int(x.get("id") or 0))

    shown = sorted(items, key=sort_key)[:10]
    send_message(chat_id, f"<b>{title}</b>\nПоказываю до 10 актуальных записей.", reply_markup=admin_panel_keyboard())
    for item in shown:
        if item_kind == "application":
            text = format_application_item(item)
        elif item_kind == "ticket":
            text = format_ticket_item(item)
        else:
            text = format_appeal_item(item)
        keyboard = admin_action_keyboard(item_kind, item) if item.get("status") == "new" else admin_panel_keyboard()
        att_type = item.get("attachment_type")
        file_id = item.get("file_id")
        if att_type == "photo" and file_id:
            send_photo_id(chat_id, file_id, text, reply_markup=keyboard)
        elif att_type == "document" and file_id:
            send_document_id(chat_id, file_id, "📎 Документ")
            send_message(chat_id, text, reply_markup=keyboard)
        else:
            send_message(chat_id, text, reply_markup=keyboard)


def handle_admin_action(cq: Dict[str, Any]) -> None:
    callback_id = cq.get("id", "")
    user = cq.get("from", {})
    admin_id = int(user.get("id"))
    message = cq.get("message", {})
    chat_id = int(message.get("chat", {}).get("id", admin_id))
    message_id = int(message.get("message_id", 0) or 0)
    data = cq.get("data", "")

    if not is_admin(admin_id):
        answer_callback(callback_id, "Нет доступа", True)
        send_admin_denied(chat_id, admin_id)
        return

    parts = data.split(":")
    if data == "admin:panel":
        answer_callback(callback_id, "Админ панель")
        send_admin_panel(chat_id, admin_id)
        return
    if data.startswith("admin:list:"):
        kind = parts[2] if len(parts) > 2 else ""
        answer_callback(callback_id, "Список")
        admin_send_list(chat_id, kind)
        return
    if data == "admin:export":
        answer_callback(callback_id, "Готовлю экспорт")
        export_data(chat_id)
        return

    # admin:<kind>:<action>:<id>
    if len(parts) != 4:
        answer_callback(callback_id, "Неизвестная команда", True)
        return

    kind, action, raw_id = parts[1], parts[2], parts[3]
    try:
        item_id = int(raw_id)
    except ValueError:
        answer_callback(callback_id, "Неверный ID", True)
        return

    if kind == "application":
        filename = "applications.json"
        if action == "approve":
            status, user_text, admin_text = "approved", "✅ Твоя заявка в клан принята. Администратор свяжется с тобой.", "Заявка принята."
        elif action == "reject":
            status, user_text, admin_text = "rejected", "❌ Твоя заявка в клан отклонена. Можно попробовать позже.", "Заявка отклонена."
        else:
            answer_callback(callback_id, "Неизвестное действие", True)
            return
    elif kind == "ticket":
        filename = "tickets.json"
        if action == "close":
            status, user_text, admin_text = "closed", "✅ Твоё обращение в техподдержку закрыто администратором.", "Тикет закрыт."
        else:
            answer_callback(callback_id, "Неизвестное действие", True)
            return
    elif kind == "appeal":
        filename = "appeals.json"
        if action == "approve":
            status, user_text, admin_text = "approved", "✅ Обжалование мута одобрено. Ожидай восстановления доступа к чату.", "Обжалование одобрено."
        elif action == "reject":
            status, user_text, admin_text = "rejected", "❌ Обжалование мута отклонено. Решение администрации оставлено в силе.", "Обжалование отклонено."
        else:
            answer_callback(callback_id, "Неизвестное действие", True)
            return
    else:
        answer_callback(callback_id, "Неизвестный тип", True)
        return

    current_items = read_json(filename, [])
    current = next((x for x in current_items if int(x.get("id", -1)) == item_id), None)
    if not current:
        answer_callback(callback_id, "Запись не найдена", True)
        return
    if current.get("status") != "new":
        answer_callback(callback_id, "Запись уже обработана", True)
        return

    item = update_record(
        filename,
        item_id,
        {"status": status, "admin_id": admin_id, "updated_at": now_str(), "admin_username": user.get("username")},
    )
    if not item:
        answer_callback(callback_id, "Запись не найдена", True)
        return

    answer_callback(callback_id, admin_text)
    if message_id:
        edit_message_reply_markup(chat_id, message_id)
    send_message(chat_id, f"✅ {escape(admin_text)} #{item_id}", reply_markup=admin_panel_keyboard())

    target_user = item.get("user_id")
    if target_user:
        try:
            send_message(int(target_user), f"<b>{escape(CLAN_NAME)}</b>\n{escape(user_text)}", reply_markup=back_keyboard(int(target_user)))
        except Exception as e:
            logging.error("Cannot notify user %s: %s", target_user, e)


def export_data(chat_id: int) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = DATA_DIR / f"zrg_export_{ts}.zip"
    files = ["users.json", "applications.json", "tickets.json", "appeals.json", "counters.json"]
    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            path = json_path(name)
            if path.exists():
                zf.write(path, arcname=name)
    send_local_document(chat_id, export_path, "📦 Экспорт данных ZRG Bot")


# ---------------------------------------------------------------------------
# UPDATE ROUTING
# ---------------------------------------------------------------------------


def handle_callback(cq: Dict[str, Any]) -> None:
    data = cq.get("data", "")
    user = cq.get("from", {})
    user_id = int(user.get("id"))
    message = cq.get("message", {})
    chat_id = int(message.get("chat", {}).get("id", user_id))
    callback_id = cq.get("id", "")

    if data.startswith("cap:"):
        handle_captcha_callback(cq)
        return

    if not ensure_access(chat_id, user_id):
        answer_callback(callback_id, "Сначала пройди капчу", True)
        return

    if data == "noop":
        answer_callback(callback_id)
        return
    if data == "menu:home":
        answer_callback(callback_id, "Меню")
        clear_state(user_id)
        send_main_menu(chat_id, user_id)
        return
    if data == "menu:about":
        answer_callback(callback_id, "О клане")
        clear_state(user_id)
        send_about(chat_id, user_id)
        return
    if data == "menu:academy":
        answer_callback(callback_id, "Академия")
        clear_state(user_id)
        send_academy(chat_id, user_id)
        return
    if data == "menu:apply":
        answer_callback(callback_id, "Заявка")
        start_application(chat_id, user_id)
        return
    if data == "menu:support":
        answer_callback(callback_id, "Техподдержка")
        start_support(chat_id, user_id)
        return
    if data == "menu:unmute":
        answer_callback(callback_id, "Обжалование мута")
        start_unmute(chat_id, user_id)
        return
    if data == "form:cancel":
        answer_callback(callback_id, "Отменено")
        clear_state(user_id)
        send_message(chat_id, "❌ Действие отменено.", reply_markup=menu_keyboard(user_id))
        return
    if data == "form:app:confirm":
        finalize_application(cq)
        return
    if data.startswith("role:"):
        process_role_callback(cq)
        return
    if data.startswith("admin:"):
        handle_admin_action(cq)
        return

    answer_callback(callback_id, "Неизвестная кнопка", True)


def handle_message(message: Dict[str, Any]) -> None:
    chat = message.get("chat", {})
    chat_id = int(chat.get("id"))
    chat_type = chat.get("type", "private")
    user = message.get("from", {})
    if not user:
        return
    user_id = int(user.get("id"))
    text = get_text(message)

    # Бот рассчитан на личные сообщения. В группах не шумим.
    if chat_type != "private":
        if text.startswith("/start") or text.startswith("/help"):
            send_message(chat_id, "Напиши мне в личные сообщения — там доступно меню клана.")
        return

    command = text.split()[0].split("@", 1)[0].lower() if text.startswith("/") else ""

    if command == "/start":
        clear_state(user_id)
        if is_verified(user_id):
            send_main_menu(chat_id, user_id)
        else:
            send_captcha(chat_id, user_id)
        return
    if command == "/id":
        send_message(chat_id, f"Твой Telegram ID: <code>{user_id}</code>")
        return
    if command == "/cancel":
        clear_state(user_id)
        send_message(chat_id, "❌ Действие отменено.", reply_markup=menu_keyboard(user_id))
        return

    if not ensure_access(chat_id, user_id):
        return

    if command in {"/menu", "/help"}:
        clear_state(user_id)
        send_main_menu(chat_id, user_id)
        return
    if command == "/admin":
        clear_state(user_id)
        send_admin_panel(chat_id, user_id)
        return

    state = get_state(user_id)
    if state:
        flow = state.get("flow")
        if flow == "application":
            process_application_message(message, state)
            return
        if flow == "support":
            finalize_support(message, state)
            return
        if flow == "unmute":
            process_unmute_message(message, state)
            return

    send_message(chat_id, "Выбери раздел в меню 👇", reply_markup=menu_keyboard(user_id))


def handle_update(update: Dict[str, Any]) -> None:
    if "callback_query" in update:
        handle_callback(update["callback_query"])
    elif "message" in update:
        handle_message(update["message"])


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------


def main() -> None:
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN not set. Создай .env или переменную окружения BOT_TOKEN.", file=sys.stderr)
        sys.exit(1)

    if not acquire_single_instance_lock():
        print(
            "ERROR: This bot is already running on this machine/container. "
            "Second copy was stopped to prevent Conflict getUpdates.",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(EXIT_ALREADY_RUNNING)

    try:
        api("deleteWebhook", {"drop_pending_updates": "false"})
    except Exception as e:
        logging.warning("deleteWebhook failed: %s", e)

    try:
        me = api("getMe")
        username = me.get("username", "unknown")
        print(f"ONLINE @{username}", flush=True)
        print("POLL READY", flush=True)
        logging.info("ONLINE @%s | DATA_DIR=%s | ADMINS=%s", username, DATA_DIR, sorted(ADMIN_IDS))
    except Exception:
        logging.exception("Cannot get bot info")
        raise

    offset: Optional[int] = None
    while True:
        try:
            params: Dict[str, Any] = {
                "timeout": 30,
                "allowed_updates": json.dumps(["message", "callback_query"]),
            }
            if offset is not None:
                params["offset"] = offset
            updates = api("getUpdates", params)
            for update in updates:
                offset = int(update["update_id"]) + 1
                try:
                    handle_update(update)
                except Exception:
                    logging.error("Update failed:\n%s\nUpdate: %s", traceback.format_exc(), json.dumps(update, ensure_ascii=False)[:2000])
        except KeyboardInterrupt:
            print("Stopped by user", flush=True)
            break
        except BotAPIError as e:
            logging.error("Polling error: %s", e)
            if "Conflict" in str(e) or "terminated by other getUpdates" in str(e):
                conflict_standby(str(e))
            time.sleep(3)
        except Exception:
            logging.exception("Unexpected polling error")
            time.sleep(5)


if __name__ == "__main__":
    main()
