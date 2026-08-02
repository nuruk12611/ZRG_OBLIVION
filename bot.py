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


def parse_usernames(raw: str) -> set[str]:
    names: set[str] = set()
    for part in re.split(r"[,\s;]+", raw.strip()):
        name = part.strip().lstrip("@").lower()
        if name:
            names.add(name)
    return names


load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = parse_ids(os.getenv("ADMIN_IDS", ""))
# Username-admins get access after they open the bot once, because Telegram
# sends username only inside user messages/callbacks. Default owner username:
# @Simba253
ADMIN_USERNAMES = parse_usernames(os.getenv("ADMIN_USERNAMES", "Simba253"))
CLAN_NAME = os.getenv("CLAN_NAME", "ZRG OBLIVION").strip() or "ZRG OBLIVION"
BOT_TITLE = os.getenv("BOT_TITLE", "ZRG Oblivion Bot").strip() or "ZRG Oblivion Bot"
CLAN_TAG = os.getenv("CLAN_TAG", "ZRG").strip() or "ZRG"
ADMIN_TAG = os.getenv("ADMIN_TAG", "admin").strip() or "admin"
ACCEPT_INVITE_LINK = os.getenv("ACCEPT_INVITE_LINK", "https://t.me/+mY85Yv-Z0iAwN2Ni").strip() or "https://t.me/+mY85Yv-Z0iAwN2Ni"
DEFAULT_CLAN_MEMBERS = int(os.getenv("CLAN_MEMBERS", "59") or "59")
ANTIFLOOD_SECONDS = int(os.getenv("ANTIFLOOD_SECONDS", "5") or "5")
AUTO_ACCEPT_SECONDS = int(os.getenv("AUTO_ACCEPT_SECONDS", str(3 * 60 * 60)) or str(3 * 60 * 60))
REAPPLY_COOLDOWN_SECONDS = int(os.getenv("REAPPLY_COOLDOWN_SECONDS", str(2 * 60 * 60)) or str(2 * 60 * 60))
KEEP_PROCESSED_SECONDS = int(os.getenv("KEEP_PROCESSED_SECONDS", str(3 * 24 * 60 * 60)) or str(3 * 24 * 60 * 60))
BOT_VERSION = "zrg_oblivion3_no_academy_min5_2026_07_28"

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
        "roles.json": {"admins": {}, "owners": []},
        "moderation.json": {"users": {}},
        "settings.json": {"clan_members": DEFAULT_CLAN_MEMBERS, "last_event": "—"},
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


# ---------------------------------------------------------------------------
# SQLITE DATABASE (встроенная БД внутри бота) + JSON fallback
# ---------------------------------------------------------------------------
import sqlite3

DB_PATH = DATA_DIR / "bot.db"
DB_BACKUP_DIR = DATA_DIR / "backups"
SQLITE_INIT_DONE = False

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), timeout=20, isolation_level=None, check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA temp_store=MEMORY;")
    except Exception:
        pass
    return conn

def _init_sqlite_db() -> None:
    global SQLITE_INIT_DONE
    if SQLITE_INIT_DONE:
        return
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        DB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        conn = _get_conn()
        conn.execute("CREATE TABLE IF NOT EXISTS kv_store (name TEXT PRIMARY KEY, data TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS counters (kind TEXT PRIMARY KEY, value INTEGER NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.commit()
        cur = conn.execute("SELECT COUNT(*) FROM kv_store")
        count = cur.fetchone()[0]
        if count == 0:
            json_files = ["users.json", "states.json", "counters.json", "applications.json", "tickets.json", "appeals.json", "roles.json", "moderation.json", "settings.json"]
            for fname in json_files:
                fpath = DATA_DIR / fname
                if fpath.exists():
                    try:
                        data = json.loads(fpath.read_text(encoding="utf-8"))
                        j = json.dumps(data, ensure_ascii=False, indent=2)
                        conn.execute("INSERT OR REPLACE INTO kv_store (name, data) VALUES (?,?)", (fname, j))
                        if fname == "counters.json" and isinstance(data, dict):
                            for k, v in data.items():
                                try:
                                    conn.execute("INSERT OR REPLACE INTO counters (kind, value) VALUES (?,?)", (str(k), int(v)))
                                except Exception:
                                    pass
                    except Exception as e:
                        logging.warning(f"Migration failed for {fname}: {e}")
            conn.commit()
        cur = conn.execute("SELECT COUNT(*) FROM counters")
        if cur.fetchone()[0] == 0:
            try:
                cur2 = conn.execute("SELECT data FROM kv_store WHERE name='counters.json'")
                row = cur2.fetchone()
                if row:
                    cdata = json.loads(row[0])
                    for k, v in cdata.items():
                        try:
                            conn.execute("INSERT OR REPLACE INTO counters (kind, value) VALUES (?,?)", (str(k), int(v)))
                        except Exception:
                            pass
                    conn.commit()
            except Exception:
                pass
        conn.close()
        SQLITE_INIT_DONE = True
        logging.info(f"SQLite DB ready: {DB_PATH} (WAL mode)")
        try:
            backup_database(force=True)
        except Exception as e:
            logging.warning(f"Initial backup failed: {e}")
    except Exception:
        logging.exception("Failed to init SQLite DB")
        SQLITE_INIT_DONE = True

def backup_database(force: bool = False) -> Optional[Path]:
    try:
        DB_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        last_backup_file = DB_BACKUP_DIR / "last_backup.txt"
        if not force and last_backup_file.exists():
            try:
                last_ts = float(last_backup_file.read_text().strip())
                if time.time() - last_ts < 3600:
                    return None
            except Exception:
                pass
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_db = DB_BACKUP_DIR / f"bot_{ts}.db"
        if DB_PATH.exists():
            import shutil
            shutil.copy2(str(DB_PATH), str(backup_db))
        json_dump_path = DB_BACKUP_DIR / f"dump_{ts}.json"
        try:
            conn = _get_conn()
            cur = conn.execute("SELECT name, data FROM kv_store")
            rows = cur.fetchall()
            conn.close()
            dump = {}
            for name, data in rows:
                try:
                    dump[name] = json.loads(data)
                except Exception:
                    dump[name] = data
            json_dump_path.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        try:
            all_backups = sorted(DB_BACKUP_DIR.glob("bot_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in all_backups[20:]:
                try:
                    old.unlink()
                except Exception:
                    pass
            all_dumps = sorted(DB_BACKUP_DIR.glob("dump_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old in all_dumps[20:]:
                try:
                    old.unlink()
                except Exception:
                    pass
        except Exception:
            pass
        last_backup_file.write_text(str(time.time()), encoding="utf-8")
        return backup_db
    except Exception:
        logging.exception("backup_database failed")
        return None

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def json_path(name: str) -> Path:
    return DATA_DIR / name

def read_json(name: str, default: Any) -> Any:
    try:
        _init_sqlite_db()
        conn = _get_conn()
        cur = conn.execute("SELECT data FROM kv_store WHERE name=?", (name,))
        row = cur.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception:
        logging.exception(f"read_json SQLite failed for {name}")
    path = json_path(name)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logging.exception("Cannot read JSON file: %s", path)
        return default

def write_json(name: str, data: Any) -> None:
    try:
        _init_sqlite_db()
        j = json.dumps(data, ensure_ascii=False, indent=2)
        conn = _get_conn()
        conn.execute("INSERT OR REPLACE INTO kv_store (name, data) VALUES (?,?)", (name, j))
        conn.commit()
        conn.close()
    except Exception:
        logging.exception(f"write_json SQLite failed for {name}")
    try:
        path = json_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        logging.exception(f"write_json file backup failed for {name}")

def next_id(kind: str) -> int:
    try:
        _init_sqlite_db()
        conn = _get_conn()
        cur = conn.execute("SELECT value FROM counters WHERE kind=?", (kind,))
        row = cur.fetchone()
        if row:
            new_val = int(row[0]) + 1
            conn.execute("UPDATE counters SET value=? WHERE kind=?", (new_val, kind))
        else:
            try:
                cur2 = conn.execute("SELECT data FROM kv_store WHERE name='counters.json'")
                r2 = cur2.fetchone()
                base = 0
                if r2:
                    c = json.loads(r2[0])
                    base = int(c.get(kind, 0))
                new_val = base + 1
            except Exception:
                new_val = 1
            conn.execute("INSERT OR REPLACE INTO counters (kind, value) VALUES (?,?)", (kind, new_val))
        cur_all = conn.execute("SELECT kind, value FROM counters")
        all_counters = {k: v for k, v in cur_all.fetchall()}
        j = json.dumps(all_counters, ensure_ascii=False, indent=2)
        conn.execute("INSERT OR REPLACE INTO kv_store (name, data) VALUES (?,?)", ("counters.json", j))
        conn.commit()
        conn.close()
        try:
            path = DATA_DIR / "counters.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(j, encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            pass
        return new_val
    except Exception:
        logging.exception(f"next_id failed for {kind}, fallback to JSON")
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


def parse_time_str(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not value:
        return 0.0
    text = str(value).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:19], fmt).timestamp()
        except Exception:
            pass
    return 0.0


def human_wait(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    if minutes:
        return f"{minutes} мин"
    return f"{seconds} сек"


def get_settings() -> Dict[str, Any]:
    settings = read_json("settings.json", {})
    if not isinstance(settings, dict):
        settings = {}
    if "clan_members" not in settings:
        settings["clan_members"] = DEFAULT_CLAN_MEMBERS
    if "last_event" not in settings:
        settings["last_event"] = "—"
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    write_json("settings.json", settings)


def get_clan_members() -> int:
    try:
        return int(get_settings().get("clan_members", DEFAULT_CLAN_MEMBERS))
    except Exception:
        return DEFAULT_CLAN_MEMBERS


def set_clan_members(count: int, event: str = "—") -> None:
    settings = get_settings()
    settings["clan_members"] = int(count)
    settings["last_event"] = event or f"Обновлено: {now_str()}"
    save_settings(settings)


def get_roles() -> Dict[str, Any]:
    roles = read_json("roles.json", {"admins": {}, "owners": []})
    if not isinstance(roles, dict):
        roles = {"admins": {}, "owners": []}
    roles.setdefault("admins", {})
    roles.setdefault("owners", [])
    return roles


def save_roles(roles: Dict[str, Any]) -> None:
    write_json("roles.json", roles)


def is_username_admin(user_id: int) -> bool:
    if not ADMIN_USERNAMES:
        return False
    rec = get_user(user_id)
    username = str(rec.get("username") or "").lstrip("@").lower()
    return bool(username and username in ADMIN_USERNAMES)


def is_owner(user_id: int) -> bool:
    roles = get_roles()
    return (
        int(user_id) in ADMIN_IDS
        or is_username_admin(user_id)
        or int(user_id) in {int(x) for x in roles.get("owners", []) if str(x).lstrip("-").isdigit()}
    )


def grant_admin(user_id: int, by_admin: Optional[int] = None, username: Optional[str] = None) -> None:
    roles = get_roles()
    admins = roles.setdefault("admins", {})
    admins[str(int(user_id))] = {"tag": ADMIN_TAG, "granted_by": by_admin, "username": username, "created_at": now_str()}
    save_roles(roles)


def revoke_admin(user_id: int) -> None:
    roles = get_roles()
    roles.setdefault("admins", {}).pop(str(int(user_id)), None)
    save_roles(roles)


def is_admin(user_id: int) -> bool:
    roles = get_roles()
    return is_owner(user_id) or str(int(user_id)) in roles.get("admins", {})


def all_admin_ids() -> List[int]:
    roles = get_roles()
    ids = set(int(x) for x in ADMIN_IDS)
    for key in roles.get("admins", {}).keys():
        if str(key).lstrip("-").isdigit():
            ids.add(int(key))

    # Include username-admins after they have written to the bot at least once.
    users = read_json("users.json", {})
    for uid, rec in users.items():
        if not str(uid).lstrip("-").isdigit() or not isinstance(rec, dict):
            continue
        username = str(rec.get("username") or "").lstrip("@").lower()
        if username and username in ADMIN_USERNAMES:
            ids.add(int(uid))
    return sorted(ids)


def remember_user(user: Dict[str, Any]) -> None:
    if not user or user.get("is_bot"):
        return
    try:
        user_id = int(user.get("id"))
    except Exception:
        return
    rec = get_user(user_id)
    rec["username"] = user.get("username")
    rec["first_name"] = user.get("first_name")
    rec["last_name"] = user.get("last_name")
    rec["last_seen_at"] = now_str()
    save_user(user_id, rec)


def find_user_by_target(target: str) -> Optional[int]:
    target = (target or "").strip()
    if not target:
        return None
    m = re.fullmatch(r"id\s+(-?\d+)", target, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    if re.fullmatch(r"-?\d+", target):
        return int(target)
    if target.startswith("@"):
        username = target[1:].lower()
        users = read_json("users.json", {})
        for uid, rec in users.items():
            if isinstance(rec, dict) and str(rec.get("username") or "").lower() == username:
                return int(uid)
    return None


def get_moderation() -> Dict[str, Any]:
    data = read_json("moderation.json", {"users": {}})
    if not isinstance(data, dict):
        data = {"users": {}}
    data.setdefault("users", {})
    return data


def save_moderation(data: Dict[str, Any]) -> None:
    write_json("moderation.json", data)


def set_user_moderation(user_id: int, **updates: Any) -> None:
    data = get_moderation()
    rec = data.setdefault("users", {}).setdefault(str(int(user_id)), {})
    rec.update(updates)
    rec["updated_at"] = now_str()
    save_moderation(data)


def clear_user_moderation(user_id: int) -> None:
    data = get_moderation()
    data.setdefault("users", {}).pop(str(int(user_id)), None)
    save_moderation(data)


def check_user_allowed(chat_id: int, user_id: int) -> bool:
    if is_admin(user_id):
        return True
    rec = get_moderation().get("users", {}).get(str(int(user_id)), {})
    if rec.get("banned"):
        send_message(chat_id, "🚫 Вам заблокирован доступ к боту.")
        return False
    if rec.get("disabled"):
        send_message(chat_id, "⛔️ Доступ к боту для вас отключён администрацией.")
        return False
    muted_until = float(rec.get("muted_until") or 0)
    if muted_until > time.time():
        send_message(chat_id, f"🔇 У вас мут. Осталось: {escape(human_wait(int(muted_until - time.time())))}.")
        return False
    return True


def antiflood_ok(chat_id: int, user_id: int) -> bool:
    if is_admin(user_id):
        return True
    rec = get_user(user_id)
    last = float(rec.get("last_action_ts") or 0)
    now = time.time()
    if now - last < ANTIFLOOD_SECONDS:
        wait = int(ANTIFLOOD_SECONDS - (now - last)) + 1
        send_message(chat_id, f"⏱️ Антифлуд: подожди {wait} сек.")
        return False
    rec["last_action_ts"] = now
    save_user(user_id, rec)
    return True


def user_name_from_rec(user_id: int) -> str:
    rec = get_user(user_id)
    return rec.get("first_name") or rec.get("username") or "Игрок"


def user_rejection_count(user_id: int) -> int:
    apps = read_json("applications.json", [])
    return sum(1 for app in apps if int(app.get("user_id") or 0) == int(user_id) and app.get("status") == "rejected")


def can_submit_application(user_id: int) -> Tuple[bool, str]:
    apps = read_json("applications.json", [])
    user_apps = [x for x in apps if int(x.get("user_id") or 0) == int(user_id)]
    if any(x.get("status") in {"new", "reviewing"} for x in user_apps):
        return False, "⏳ У тебя уже есть заявка на рассмотрении. Дождись решения администрации."
    rejected = [x for x in user_apps if x.get("status") == "rejected"]
    if len(rejected) >= 2:
        return False, "🚫 Тебе запрещено подавать заявки в клан после повторного отказа. Обратись в техподдержку."
    if rejected:
        last = max(parse_time_str(x.get("updated_at") or x.get("created_at")) for x in rejected)
        left = int(REAPPLY_COOLDOWN_SECONDS - (time.time() - last))
        if left > 0:
            return False, f"⏳ После отказа новую заявку можно подать через {human_wait(left)}."
    return True, ""




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
        [btn("🎧 Техподдержка", "menu:support")],
        [btn("📣 Обжалование мута", "menu:unmute")],
    ]
    if is_admin(user_id):
        rows.append([btn("🛡 Админ-панель", "admin:panel")])
    return kb(rows)


def cancel_keyboard() -> Dict[str, Any]:
    return kb([[btn("❌ Отмена", "form:cancel"), btn("🏠 Меню", "menu:home")]])


def back_keyboard(user_id: int) -> Dict[str, Any]:
    rows = [[btn("🏠 Главное меню", "menu:home")]]
    if is_admin(user_id):
        rows.append([btn("🛡 Админ-панель", "admin:panel")])
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
    ("yellow", "🟡"),
    ("purple", "🟣"),
    ("black", "⚫"),
    ("blue", "🔵"),
    ("red", "🔴"),
    ("green", "🟢"),
]
CAPTCHA_MAP = {key: emoji for key, emoji in CAPTCHA}
CAPTCHA_LENGTH = 4


def edit_message_text(
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: str = "HTML",
) -> None:
    params: Dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        params["parse_mode"] = parse_mode
    if reply_markup is not None:
        params["reply_markup"] = dumps_markup(reply_markup)
    try:
        api("editMessageText", params)
    except Exception:
        logging.exception("Cannot edit message text")


def captcha_progress_bar(progress: int, total: int = CAPTCHA_LENGTH) -> str:
    progress = max(0, min(int(progress), int(total)))
    return "🟩" * progress + "⬜" * (total - progress)


def captcha_order_text(sequence: List[str]) -> str:
    return " → ".join(CAPTCHA_MAP.get(key, "❔") for key in sequence)


def captcha_text(sequence: List[str], progress: int = 0, status: str = "normal") -> str:
    progress = max(0, min(int(progress), len(sequence) or CAPTCHA_LENGTH))
    total = len(sequence) or CAPTCHA_LENGTH
    status_line = "⚠️ Ошибка — будет новая капча."
    if status == "error":
        status_line = "❌ Ошибка — будет новая капча."
    elif status == "success":
        status_line = "✅ Вы успешно прошли проверку."

    return (
        "<b>🛡 Проверка: ты не бот</b>\n\n"
        "Нажми кнопки строго в этом порядке:\n\n"
        f"{escape(captcha_order_text(sequence))}\n\n"
        f"Прогресс: {captcha_progress_bar(progress, total)} ({progress}/{total})\n\n"
        f"{status_line}"
    )


def captcha_keyboard(button_order: Optional[List[str]] = None) -> Dict[str, Any]:
    if not button_order:
        buttons = CAPTCHA[:]
        random.shuffle(buttons)
        button_order = [key for key, _ in buttons]

    rows: List[List[Dict[str, str]]] = []
    for i in range(0, len(button_order), 3):
        rows.append([btn(CAPTCHA_MAP.get(key, "❔"), f"cap:{key}") for key in button_order[i : i + 3]])
    return kb(rows)


def send_captcha(chat_id: int, user_id: int) -> None:
    sequence = [key for key, _ in random.sample(CAPTCHA, CAPTCHA_LENGTH)]
    buttons = CAPTCHA[:]
    random.shuffle(buttons)
    button_order = [key for key, _ in buttons]

    rec = get_user(user_id)
    rec["captcha_ok"] = False
    rec["captcha"] = {
        "sequence": sequence,
        "progress": 0,
        "buttons": button_order,
        "created_at": time.time(),
    }
    save_user(user_id, rec)

    send_message(chat_id, captcha_text(sequence, 0), reply_markup=captcha_keyboard(button_order))


def handle_captcha_callback(cq: Dict[str, Any]) -> None:
    data = cq.get("data", "")
    callback_id = cq.get("id", "")
    choice = data.split(":", 1)[1] if ":" in data else ""
    user = cq.get("from", {})
    user_id = int(user.get("id"))
    message = cq.get("message", {})
    chat_id = int(message.get("chat", {}).get("id", user_id))
    message_id = int(message.get("message_id", 0) or 0)

    rec = get_user(user_id)
    if rec.get("captcha_ok"):
        answer_callback(callback_id, "✅ Проверка уже пройдена")
        return

    captcha = rec.get("captcha") or {}
    sequence = captcha.get("sequence") or []
    progress = int(captcha.get("progress") or 0)
    button_order = captcha.get("buttons") or [key for key, _ in CAPTCHA]

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
            answer_callback(callback_id, "✅ Проверка пройдена")
            if message_id:
                edit_message_text(chat_id, message_id, captcha_text(sequence, progress, "success"), reply_markup=kb([]))
            else:
                send_message(chat_id, captcha_text(sequence, progress, "success"))
            send_main_menu(chat_id, user_id)
        else:
            rec["captcha"]["progress"] = progress
            save_user(user_id, rec)
            answer_callback(callback_id, f"✅ Верно: {progress}/{len(sequence)}")
            if message_id:
                edit_message_text(chat_id, message_id, captcha_text(sequence, progress), reply_markup=captcha_keyboard(button_order))
    else:
        rec["captcha"] = {"sequence": [], "progress": 0, "created_at": time.time()}
        save_user(user_id, rec)
        answer_callback(callback_id, "❌ Ошибка — будет новая капча.", True)
        if message_id:
            edit_message_text(chat_id, message_id, captcha_text(sequence, progress, "error"), reply_markup=kb([]))
        else:
            send_message(chat_id, "❌ Ошибка — будет новая капча.")
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
    name = user_name_from_rec(user_id)
    text = (
        f"👋 <b>{escape(name)}</b>, с возвращением!\n\n"
        "🏷 <b>Клан ZRG_Oblivion</b>\n"
        "Бот для <b>подачи заявок в клан</b>.\n"
        "Также есть <b>техподдержка</b> и <b>обжалование мута</b>.\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "📌 <b>ВАЖНАЯ ИНФОРМАЦИЯ</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "📝 <b>Заявка в клан</b>\n"
        "Заполняешь анкету — её смотрит руководство\n\n"
        "🛠 <b>Техподдержка</b>\n"
        "Вопросы по клану и боту\n\n"
        "🔇 <b>Обжалование мута</b>\n"
        "Если считаешь мут несправедливым\n\n"
        "🏟 Клан: <b>ZRG_Oblivion</b>\n\n"
        "Жми кнопки <b>внизу экрана</b> 👇"
    )
    send_local_photo(chat_id, "about.jpg", text, reply_markup=menu_keyboard(user_id))


def send_about(chat_id: int, user_id: int) -> None:
    settings = get_settings()
    members = get_clan_members()
    last_event = str(settings.get("last_event") or "—")
    text = (
        "🏷 <b>О клане ZRG_Oblivion</b>\n\n"
        f"🏟 Тег: <b>{escape(CLAN_TAG)}</b>\n"
        f"👥 Участников сейчас: <b>{members}</b>\n"
        f"🕒 Последнее событие: {escape(last_event)}\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🎮 <b>Во что играем</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "• PUBG Mobile — основной режим\n"
        "• Ranked / классика\n"
        "• Метро (Metro Royale)\n"
        "• TDM и кастомки\n"
        "• Сквады, дуо, совместные замесы\n\n"
        "━━━━━━━━━━━━━━━━\n"
        "🔥 <b>Что есть в клане</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "• Активный состав и общий чат\n"
        "• Игры вместе и набор в отряд\n"
        "• Помощь новичкам\n"
        "• Свои правила и модерация\n"
        "• Заявки через бота\n"
        "• Техподдержка\n"
        "• Обжалование мутов\n\n"
        "Хочешь к нам — жми «📝 Подать заявку в клан»"
    )
    send_local_photo(chat_id, "about.jpg", text, reply_markup=kb([[btn("📝 Подать заявку в клан", "menu:apply")], [btn("🏠 Меню", "menu:home")]]))


def send_academy(chat_id: int, user_id: int) -> None:
    # Раздел «Академия» убран: теперь у нас только заявки в клан.
    text = (
        "📝 <b>Заявка в клан ZRG_Oblivion</b>\n\n"
        "Раздел «Академия» больше не используется.\n"
        "Если хочешь вступить — подай заявку в клан."
    )
    send_local_photo(chat_id, "apply.jpg", text, reply_markup=kb([[btn("📝 Подать заявку в клан", "menu:apply")], [btn("🏠 Меню", "menu:home")]]))


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
    (
        "nickname",
        "Ник в PUBG",
        "📝 <b>Заявка в клан</b>\n\n"
        "<b>Шаг 1/5</b>\n"
        "Напиши свой <b>ник в PUBG</b>:\n\n"
        "Отмена — /cancel",
    ),
    (
        "age",
        "Возраст",
        "📝 <b>Шаг 2/5</b>\n"
        "Сколько тебе <b>лет</b>?\n"
        "⚠️ В клан только с <b>16+</b>",
    ),
    (
        "experience",
        "Часы / опыт PUBG Mobile",
        "📝 <b>Шаг 3/5</b>\n"
        "Сколько примерно <b>часов / опыт</b> в PUBG Mobile?",
    ),
    (
        "mode",
        "Режим",
        "📝 <b>Шаг 4/5</b>\n"
        "Режим?\n"
        "• Ranked\n"
        "• Метро\n"
        "• TDM\n"
        "• соло/дуо/сквад+",
    ),
    (
        "motivation",
        "Почему хотите к нам",
        "📝 <b>Шаг 5/5</b>\n"
        "Теперь опишите, почему вы хотите именно к нам в клан.\n\n"
        "После ответа появится кнопка <b>✅ Отправить</b>.\n"
        "Минимум <b>5 слов</b>. Если хочешь — можешь написать больше, до <b>100 слов</b>.",
    ),
]
FIELD_INDEX = {key: i for i, (key, _, _) in enumerate(APPLICATION_FIELDS)}
GAME_MODE_OPTIONS = {
    "ranked": "Ranked",
    "metro": "Метро",
    "tdm": "TDM",
    "squad_plus": "Соло/дуо/сквад+",
}


def application_step_keyboard(step: str) -> Optional[Dict[str, Any]]:
    """Keyboard for application steps.

    No cancel/menu buttons here by request. /cancel still works as a command.
    """
    if step == "nickname":
        return None
    return kb([[btn("⬅️ Вернуться", "form:app:back")]])


def role_keyboard() -> Dict[str, Any]:
    return kb(
        [
            [btn("🏆 Ranked", "role:ranked"), btn("🚇 Метро", "role:metro")],
            [btn("⚔️ TDM", "role:tdm"), btn("👥 Соло/дуо/сквад+", "role:squad_plus")],
            [btn("⬅️ Вернуться", "form:app:back")],
        ]
    )


def application_prompt(step: str, state: Optional[Dict[str, Any]] = None) -> str:
    prompt = "Ответь на вопрос анкеты:"
    for key, _, item_prompt in APPLICATION_FIELDS:
        if key == step:
            prompt = item_prompt
            break
    if state:
        current = (state.get("answers") or {}).get(step)
        if current:
            prompt += f"\n\n<b>Текущий ответ:</b> {escape(str(current))}\nНапиши новый ответ, если хочешь изменить."
    return prompt


def start_application(chat_id: int, user_id: int) -> None:
    allowed, reason = can_submit_application(user_id)
    if not allowed:
        send_message(chat_id, reason, reply_markup=back_keyboard(user_id))
        return
    state = {"flow": "application", "step": "nickname", "answers": {}, "created_at": now_str()}
    set_state(user_id, state)
    send_local_photo(chat_id, "apply.jpg", application_prompt("nickname", state), reply_markup=application_step_keyboard("nickname"))


def validate_application_field(key: str, value: str) -> Tuple[bool, str, str]:
    value = value.strip()
    if key == "nickname":
        if not (2 <= len(value) <= 32):
            return False, value, "Ник должен быть от 2 до 32 символов. Попробуй ещё раз:"
        return True, value, ""
    if key == "age":
        match = re.search(r"\d+", value)
        if not match:
            return False, value, "Напиши возраст числом, например: 16"
        age = int(match.group(0))
        if age < 16:
            return False, value, "❌ В клан строго с 16+. Если тебе уже есть 16 — напиши возраст правильно."
        if age > 80:
            return False, value, "Напиши реальный возраст числом."
        return True, str(age), ""
    if key == "experience":
        words = re.findall(r"\S+", value)
        if not words:
            return False, value, "Напиши примерно часы или опыт в PUBG Mobile. Например: 1200 часов / играю 2 года."
        if len(value) > 200:
            return False, value, "Ответ слишком длинный. Коротко напиши часы или опыт в PUBG Mobile:"
        return True, value, ""
    if key == "mode":
        if not value or len(value) > 80:
            return False, value, "Напиши коротко режим: Ranked, Метро, TDM или соло/дуо/сквад+."
        return True, value, ""
    if key == "motivation":
        words = re.findall(r"\S+", value)
        if len(words) < 5:
            return False, value, "Опишите чуть подробнее, почему вы хотите попасть к нам в клан. Нужно минимум 5 слов."
        if len(words) > 100:
            return False, value, f"Слишком длинно: {len(words)} слов. Максимум 100 слов. Сократи текст и отправь ещё раз:"
        return True, value, ""
    return True, value, ""


def application_summary(answers: Dict[str, Any], title: str = "Анкета") -> str:
    lines = [f"<b>{escape(title)}</b>"]
    for key, label, _ in APPLICATION_FIELDS:
        lines.append(f"<b>{escape(label)}:</b> {escape(str(answers.get(key, '—')))}")
    return "\n".join(lines)


def ask_next_application_step(chat_id: int, user_id: int, state: Dict[str, Any]) -> None:
    step = state.get("step")
    if step == "mode":
        send_message(chat_id, application_prompt(step, state), reply_markup=role_keyboard())
    else:
        send_message(chat_id, application_prompt(step, state), reply_markup=application_step_keyboard(step))


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
        send_message(chat_id, "Нужно отправить ответ текстом.", reply_markup=application_step_keyboard(step))
        return

    ok, value, error = validate_application_field(step, text)
    if not ok:
        send_message(chat_id, escape(error), reply_markup=application_step_keyboard(step))
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
    return kb([[btn("✅ Отправить", "form:app:confirm")], [btn("⬅️ Вернуться и изменить", "form:app:back")]])


def handle_application_back(cq: Dict[str, Any]) -> None:
    callback_id = cq.get("id", "")
    user = cq.get("from", {})
    user_id = int(user.get("id"))
    chat_id = int(cq.get("message", {}).get("chat", {}).get("id", user_id))

    state = get_state(user_id)
    if not state or state.get("flow") != "application":
        answer_callback(callback_id, "Активная заявка не найдена.", True)
        return

    step = state.get("step")
    if step == "confirm":
        prev_step = APPLICATION_FIELDS[-1][0]
    elif step in FIELD_INDEX and FIELD_INDEX[step] > 0:
        prev_step = APPLICATION_FIELDS[FIELD_INDEX[step] - 1][0]
    else:
        answer_callback(callback_id, "Ты уже на первом шаге.")
        send_message(chat_id, application_prompt("nickname", state), reply_markup=application_step_keyboard("nickname"))
        return

    state["step"] = prev_step
    set_state(user_id, state)
    answer_callback(callback_id, "Вернулись назад")

    text = application_prompt(prev_step, state)
    if prev_step == "mode":
        send_message(chat_id, text, reply_markup=role_keyboard())
    else:
        send_message(chat_id, text, reply_markup=application_step_keyboard(prev_step))

def process_role_callback(cq: Dict[str, Any]) -> None:
    callback_id = cq.get("id", "")
    data = cq.get("data", "")
    role_key = data.split(":", 1)[1] if ":" in data else ""
    role = GAME_MODE_OPTIONS.get(role_key)
    user = cq.get("from", {})
    user_id = int(user.get("id"))
    chat_id = int(cq.get("message", {}).get("chat", {}).get("id", user_id))

    state = get_state(user_id)
    if not state or state.get("flow") != "application" or state.get("step") != "mode" or not role:
        answer_callback(callback_id, "Эта кнопка уже неактивна.")
        return
    state.setdefault("answers", {})["mode"] = role
    idx = FIELD_INDEX["mode"]
    if idx + 1 < len(APPLICATION_FIELDS):
        state["step"] = APPLICATION_FIELDS[idx + 1][0]
        set_state(user_id, state)
        answer_callback(callback_id, "Режим выбран")
        ask_next_application_step(chat_id, user_id, state)
    else:
        state["step"] = "confirm"
        set_state(user_id, state)
        answer_callback(callback_id, "Режим выбран")
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
    "reviewing": "👀 рассматривается",
    "approved": "✅ принято",
    "auto_approved": "🤖 авто-принято",
    "rejected": "❌ отклонено",
    "answered": "💬 отвечено",
    "closed": "✅ закрыто",
}


def accept_text(auto: bool = False) -> str:
    prefix = "🤖 Автоответчик" if auto else "✅ Руководство"
    return (
        f"{prefix}: вы успешно приняты в клан ZRG_Oblivion!\n\n"
        f"Ссылка для вступления: {ACCEPT_INVITE_LINK}"
    )


def rewrite_notice_text() -> str:
    return (
        "♻️ <b>Бот переписан</b>\n\n"
        "• Меню и раздел «О клане» обновлены под ZRG_Oblivion\n"
        "• Количество участников меняется командой <code>/members 59</code> в группе или личке\n"
        "• Админ-панель скрыта от обычных игроков\n"
        f"• Доступ админа выдаётся тегом <code>{escape(ADMIN_TAG)}</code> через панель\n"
        "• Бан / мут 1ч / отключение доступа / снятие ограничений\n"
        f"• Антифлуд {ANTIFLOOD_SECONDS} сек\n"
        "• Заявки можно принять, отклонить, взять в рассмотрение или ответить человеку\n"
        "• Если заявку не разобрали 3 часа — бот авто-примет и отправит ссылку\n"
        "• После отказа новая заявка доступна через 2 часа; после второго отказа заявки закрываются\n"
        "• Техподдержке можно отвечать прямо из бота\n"
        "• Локальные папки и базы создаются автоматически\n\n"
        "Нажми /start — увидишь «🛡 Админ-панель»."
    )


def admin_panel_text() -> str:
    apps = read_json("applications.json", [])
    tickets = read_json("tickets.json", [])
    appeals = read_json("appeals.json", [])

    def count(items: Iterable[Dict[str, Any]], statuses: set[str]) -> int:
        return sum(1 for x in items if x.get("status") in statuses)

    admins = all_admin_ids()
    admin_names = ", ".join("@" + name for name in sorted(ADMIN_USERNAMES))
    return (
        f"🛡 <b>Админ-панель</b>\n"
        f"Тег доступа: <code>{escape(ADMIN_TAG)}</code>\n\n"
        "Доступна <b>только</b> админам.\n\n"
        f"📥 <b>Список заявок</b>: {count(apps, {'new', 'reviewing'})} активных / {len(apps)} всего\n"
        "у каждой: принять+ссылка / отказать / ответить / бан / мут\n\n"
        "• 🚫 Бан — полный блок бота\n"
        "• 🔇 Мут 1ч — нельзя писать боту 1 час\n"
        "• ⛔️ Отключить доступ\n"
        "• ✅ Разбан / снять\n"
        "• 👑 Выдать / снять админку\n\n"
        "⏱️ <b>Авто-принятие:</b> если заявку не разобрать за 3 ч,\n"
        "бот сам напишет: «Вы успешно приняты… вот ссылка»\n"
        f"Ссылка: {ACCEPT_INVITE_LINK}\n\n"
        "Формат цели (бан/мут/admin):\n"
        "<code>id 123456789</code> или <code>@username</code>\n\n"
        f"Антифлуд: <b>{ANTIFLOOD_SECONDS} сек</b>.\n\n"
        f"🎧 Техподдержка: {count(tickets, {'new', 'reviewing', 'answered'})} активных / {len(tickets)} всего\n"
        f"📣 Муты: {count(appeals, {'new', 'reviewing'})} активных / {len(appeals)} всего\n"
        f"👑 Админы ID: {', '.join(str(x) for x in admins) or 'пока нет'}\n"
        f"👤 Админы username: {escape(admin_names) if admin_names else 'не настроены'}"
    )


def admin_panel_keyboard() -> Dict[str, Any]:
    return kb(
        [
            [btn("📥 Список заявок", "admin:list:applications"), btn("🎧 Техподдержка", "admin:list:tickets")],
            [btn("📣 Обжалования", "admin:list:appeals"), btn("♻️ Что обновлено", "admin:rewrite")],
            [btn("🚫 Бан", "admin:prompt:ban"), btn("🔇 Мут 1ч", "admin:prompt:mute")],
            [btn("⛔️ Отключить доступ", "admin:prompt:disable"), btn("✅ Разбан / снять", "admin:prompt:unban")],
            [btn("👑 Выдать админку", "admin:prompt:grant_admin"), btn("➖ Снять админку", "admin:prompt:revoke_admin")],
            [btn("👥 Участников клана", "admin:prompt:set_members"), btn("📦 Экспорт JSON", "admin:export")],
            [btn("🔄 Обновить", "admin:panel"), btn("🏠 Главное меню", "menu:home")],
        ]
    )


def admin_action_keyboard(kind: str, item: Dict[str, Any]) -> Dict[str, Any]:
    item_id = int(item["id"])
    user_id = int(item.get("user_id") or 0)
    rows: List[List[Dict[str, str]]] = []
    if kind == "application":
        status = str(item.get("status") or "new")
        if status in {"new", "reviewing", "answered"}:
            rows.append([btn("👀 Взять", f"admin:application:take:{item_id}"), btn("✅ Принять", f"admin:application:approve:{item_id}"), btn("❌ Отклонить", f"admin:application:reject:{item_id}")])
            rows.append([btn("💬 Ответить", f"admin:application:reply:{item_id}")])
        else:
            rows.append([btn("♻️ Восстановить заявку", f"admin:application:restore:{item_id}")])
            rows.append([btn("💬 Ответить", f"admin:application:reply:{item_id}")])
        rows.append([btn("⬅️ К спискам заявок", "admin:list:applications")])
    elif kind == "ticket":
        rows.append([btn("👀 Взять", f"admin:ticket:take:{item_id}"), btn("💬 Ответить", f"admin:ticket:reply:{item_id}"), btn("✅ Закрыть", f"admin:ticket:close:{item_id}")])
    elif kind == "appeal":
        rows.append([btn("👀 Взять", f"admin:appeal:take:{item_id}"), btn("✅ Одобрить", f"admin:appeal:approve:{item_id}"), btn("❌ Отклонить", f"admin:appeal:reject:{item_id}")])
        rows.append([btn("💬 Ответить", f"admin:appeal:reply:{item_id}")])
    if user_id:
        rows.append([btn("🚫 Бан", f"admin:{kind}:ban:{item_id}"), btn("🔇 Мут 1ч", f"admin:{kind}:mute:{item_id}"), btn("⛔️ Отключить", f"admin:{kind}:disable:{item_id}")])
        rows.append([btn("✅ Разбан / снять", f"admin:{kind}:unban:{item_id}"), btn("👤 Профиль", url=f"tg://user?id={user_id}")])
    rows.append([btn("🛡 Админ-панель", "admin:panel")])
    return kb(rows)


def application_visible(item: Dict[str, Any]) -> bool:
    status = item.get("status")
    if status in {"new", "reviewing"}:
        return True
    ts = parse_time_str(item.get("updated_at") or item.get("created_at"))
    return not ts or (time.time() - ts) <= KEEP_PROCESSED_SECONDS


def application_nickname(item: Dict[str, Any]) -> str:
    answers = item.get("answers") or {}
    return str(
        answers.get("nickname")
        or item.get("username")
        or item.get("full_name")
        or f"ID {item.get('user_id', item.get('id', '—'))}"
    )


def application_category_title(category: str) -> str:
    return {
        "new": "🆕 Недавно поданные",
        "approved": "✅ Принятые",
        "rejected": "❌ Отклонённые",
    }.get(category, "📥 Заявки")


def application_matches_category(item: Dict[str, Any], category: str) -> bool:
    status = str(item.get("status") or "new")
    if category == "new":
        return status in {"new", "reviewing", "answered"}
    if category == "approved":
        return status in {"approved", "auto_approved"}
    if category == "rejected":
        return status == "rejected"
    return True


def send_application_categories(chat_id: int) -> None:
    apps = read_json("applications.json", [])
    new_count = sum(1 for x in apps if application_matches_category(x, "new"))
    approved_count = sum(1 for x in apps if application_matches_category(x, "approved"))
    rejected_count = sum(1 for x in apps if application_matches_category(x, "rejected"))
    text = (
        "📥 <b>Список заявок в клан</b>\n\n"
        "Выбери список. Внутри будут только кнопки с заявками.\n"
        "После нажатия на заявку откроются кнопки принять / отклонить / ответить / мут / бан."
    )
    keyboard = kb(
        [
            [btn(f"🆕 Недавно поданные ({new_count})", "admin:apps:new")],
            [btn(f"✅ Принятые ({approved_count})", "admin:apps:approved")],
            [btn(f"❌ Отклонённые ({rejected_count})", "admin:apps:rejected")],
            [btn("🛡 Админ-панель", "admin:panel")],
        ]
    )
    send_message(chat_id, text, reply_markup=keyboard)


def send_application_category(chat_id: int, category: str) -> None:
    apps = read_json("applications.json", [])
    items = [x for x in apps if application_matches_category(x, category)]
    items = sorted(items, key=lambda x: -int(x.get("id") or 0))
    title = application_category_title(category)
    if not items:
        send_message(chat_id, f"<b>{title}</b>\n\nЗаявок в этом списке нет.", reply_markup=kb([[btn("⬅️ Назад к спискам", "admin:list:applications")], [btn("🛡 Админ-панель", "admin:panel")]]))
        return

    rows: List[List[Dict[str, str]]] = []
    for item in items[:50]:
        item_id = int(item.get("id") or 0)
        nick = application_nickname(item)
        status = str(item.get("status") or "new")
        if status == "reviewing" and item.get("reviewer_id"):
            text = f"👀 Заявка уже рассматривается администратором — {nick}"
        elif category == "new":
            text = f"📝 Нажмите чтобы рассмотреть заявку — {nick}"
        elif category == "approved":
            text = f"✅ Принятая заявка — {nick}"
        else:
            text = f"❌ Отклонённая заявка — {nick}"
        if len(text) > 60:
            text = text[:57] + "…"
        rows.append([btn(text, f"admin:appview:{item_id}")])
    rows.append([btn("⬅️ Назад к спискам", "admin:list:applications")])
    rows.append([btn("🛡 Админ-панель", "admin:panel")])
    send_message(chat_id, f"<b>{title}</b>\n\nНажмите на заявку, чтобы открыть карточку.", reply_markup=kb(rows))


def send_application_detail(chat_id: int, item_id: int) -> None:
    item = get_item("applications.json", item_id)
    if not item:
        send_message(chat_id, "Заявка не найдена.", reply_markup=kb([[btn("⬅️ Назад к спискам", "admin:list:applications")]]))
        return
    send_message(chat_id, format_application_item(item), reply_markup=admin_action_keyboard("application", item))

def format_application_item(item: Dict[str, Any]) -> str:
    answers = item.get("answers") or {}
    user_id = int(item.get("user_id") or 0)
    status = STATUS_LABELS.get(item.get("status", "new"), item.get("status", "new"))
    text = [
        f"<b>📝 Заявка в клан #{item.get('id')}</b>",
        f"<b>Статус:</b> {escape(status)}",
        f"<b>Дата:</b> {escape(str(item.get('created_at', '—')))}",
        f"<b>Пользователь:</b> {user_link(user_id, item.get('full_name') or str(user_id))}",
    ]
    if item.get("reviewer_id"):
        text.append(f"<b>Рассматривает:</b> {user_link(int(item.get('reviewer_id')), item.get('reviewer_name') or str(item.get('reviewer_id')))}")
    if item.get("admin_id"):
        text.append(f"<b>Решение:</b> {user_link(int(item.get('admin_id')), item.get('admin_username') or str(item.get('admin_id')))}")
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
    if item.get("reviewer_id"):
        text.append(f"<b>Рассматривает:</b> {user_link(int(item.get('reviewer_id')), item.get('reviewer_name') or str(item.get('reviewer_id')))}")
    if item.get("username"):
        text.append(f"<b>Username:</b> @{escape(str(item.get('username')))}")
    text.extend(["", f"<b>Сообщение:</b>\n{escape(str(item.get('text', '—')))}"])
    if item.get("replies"):
        text.append("\n<b>Ответы:</b>")
        for reply in item.get("replies", [])[-3:]:
            text.append(f"• {escape(str(reply.get('created_at', '')))}: {escape(str(reply.get('text', '')))}")
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
    if item.get("reviewer_id"):
        text.append(f"<b>Рассматривает:</b> {user_link(int(item.get('reviewer_id')), item.get('reviewer_name') or str(item.get('reviewer_id')))}")
    if item.get("username"):
        text.append(f"<b>Username:</b> @{escape(str(item.get('username')))}")
    text.append("")
    for key, label in labels.items():
        text.append(f"<b>{escape(label)}:</b> {escape(str(answers.get(key, '—')))}")
    if item.get("replies"):
        text.append("\n<b>Ответы:</b>")
        for reply in item.get("replies", [])[-3:]:
            text.append(f"• {escape(str(reply.get('created_at', '')))}: {escape(str(reply.get('text', '')))}")
    return "\n".join(text)


def notify_admins(text: str, keyboard: Optional[Dict[str, Any]] = None, attachment_type: Optional[str] = None, file_id: Optional[str] = None) -> None:
    admins = all_admin_ids()
    if not admins:
        logging.warning("No admins configured; admin notification was not sent")
        return
    for admin_id in admins:
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


def send_admin_panel(chat_id: int, user_id: int) -> None:
    if not is_admin(user_id):
        send_admin_denied(chat_id, user_id)
        return
    send_local_photo(chat_id, "admin.jpg", admin_panel_text(), reply_markup=admin_panel_keyboard())


def admin_send_list(chat_id: int, kind: str) -> None:
    mapping = {
        "applications": ("applications.json", "application", "📥 Заявки в клан"),
        "tickets": ("tickets.json", "ticket", "🎧 Техподдержка"),
        "appeals": ("appeals.json", "appeal", "📣 Обжалования мута"),
    }
    if kind not in mapping:
        send_message(chat_id, "Неизвестный список.", reply_markup=admin_panel_keyboard())
        return
    filename, item_kind, title = mapping[kind]
    if item_kind == "application":
        send_application_categories(chat_id)
        return
    items = read_json(filename, [])
    if not items:
        send_message(chat_id, f"<b>{title}</b>\nСписок пуст.", reply_markup=admin_panel_keyboard())
        return

    def sort_key(x: Dict[str, Any]) -> Tuple[int, int]:
        status_order = {"new": 0, "reviewing": 1, "answered": 2, "approved": 3, "auto_approved": 3, "rejected": 4, "closed": 5}
        return (status_order.get(str(x.get("status")), 9), -int(x.get("id") or 0))

    shown = sorted(items, key=sort_key)[:20]
    send_message(chat_id, f"<b>{title}</b>\nПоказываю до 20 записей. Принятые/отклонённые видны 3 дня.", reply_markup=admin_panel_keyboard())
    for item in shown:
        if item_kind == "application":
            text = format_application_item(item)
        elif item_kind == "ticket":
            text = format_ticket_item(item)
        else:
            text = format_appeal_item(item)
        keyboard = admin_action_keyboard(item_kind, item)
        att_type = item.get("attachment_type")
        file_id = item.get("file_id")
        if att_type == "photo" and file_id:
            send_photo_id(chat_id, file_id, text, reply_markup=keyboard)
        elif att_type == "document" and file_id:
            send_document_id(chat_id, file_id, "📎 Документ")
            send_message(chat_id, text, reply_markup=keyboard)
        else:
            send_message(chat_id, text, reply_markup=keyboard)


def filename_for_kind(kind: str) -> Optional[str]:
    return {"application": "applications.json", "ticket": "tickets.json", "appeal": "appeals.json"}.get(kind)


def get_item(filename: str, item_id: int) -> Optional[Dict[str, Any]]:
    items = read_json(filename, [])
    for item in items:
        if int(item.get("id", -1)) == int(item_id):
            return item
    return None


def prompt_target(chat_id: int, admin_id: int, action: str) -> None:
    titles = {
        "ban": "🚫 Бан",
        "mute": "🔇 Мут 1ч",
        "disable": "⛔️ Отключить доступ",
        "unban": "✅ Разбан / снять",
        "grant_admin": "👑 Выдать админку",
        "revoke_admin": "➖ Снять админку",
        "set_members": "👥 Участников клана",
    }
    set_state(admin_id, {"flow": "admin_target", "action": action, "created_at": now_str()})
    if action == "set_members":
        send_message(chat_id, "Напиши новое число участников, например: <code>59</code>", reply_markup=cancel_keyboard())
    else:
        send_message(chat_id, f"{titles.get(action, action)}\nОтправь цель в формате: <code>id 123456789</code> или <code>@username</code>", reply_markup=cancel_keyboard())


def apply_target_action(chat_id: int, admin_id: int, action: str, target_id: int, username: Optional[str] = None) -> None:
    if action == "ban":
        set_user_moderation(target_id, banned=True)
        send_message(chat_id, f"🚫 Пользователь {target_id} забанен.", reply_markup=admin_panel_keyboard())
        try: send_message(target_id, "🚫 Вам заблокирован доступ к боту.")
        except Exception: pass
    elif action == "mute":
        set_user_moderation(target_id, muted_until=time.time() + 3600)
        send_message(chat_id, f"🔇 Пользователю {target_id} выдан мут на 1 час.", reply_markup=admin_panel_keyboard())
        try: send_message(target_id, "🔇 Вам выдан мут на 1 час. Вы временно не можете писать боту.")
        except Exception: pass
    elif action == "disable":
        set_user_moderation(target_id, disabled=True)
        send_message(chat_id, f"⛔️ Доступ пользователю {target_id} отключён.", reply_markup=admin_panel_keyboard())
        try: send_message(target_id, "⛔️ Доступ к боту отключён администрацией.")
        except Exception: pass
    elif action == "unban":
        clear_user_moderation(target_id)
        send_message(chat_id, f"✅ Ограничения с пользователя {target_id} сняты.", reply_markup=admin_panel_keyboard())
        try: send_message(target_id, "✅ Ограничения сняты. Доступ к боту восстановлен.")
        except Exception: pass
    elif action == "grant_admin":
        grant_admin(target_id, by_admin=admin_id, username=username)
        send_message(chat_id, f"👑 Пользователю {target_id} выдан тег <code>{escape(ADMIN_TAG)}</code>.", reply_markup=admin_panel_keyboard())
        try: send_message(target_id, f"👑 Вам выдан доступ к админ-панели. Тег: <code>{escape(ADMIN_TAG)}</code>.")
        except Exception: pass
    elif action == "revoke_admin":
        if is_owner(target_id):
            send_message(chat_id, "⚠️ Нельзя снять owner из переменной ADMIN_IDS.", reply_markup=admin_panel_keyboard())
            return
        revoke_admin(target_id)
        send_message(chat_id, f"➖ У пользователя {target_id} снят тег admin.", reply_markup=admin_panel_keyboard())
        try: send_message(target_id, "➖ Доступ к админ-панели снят.")
        except Exception: pass


def process_admin_state(message: Dict[str, Any], state: Dict[str, Any]) -> bool:
    user = message.get("from", {})
    admin_id = int(user.get("id"))
    chat_id = int(message["chat"]["id"])
    text = get_text(message)
    if not is_admin(admin_id):
        return False
    flow = state.get("flow")
    if flow == "admin_target":
        action = state.get("action")
        if action == "set_members":
            if not text.isdigit():
                send_message(chat_id, "Нужно отправить число, например: <code>59</code>.", reply_markup=cancel_keyboard())
                return True
            set_clan_members(int(text), f"Обновлено админом {admin_id}: {now_str()}")
            clear_state(admin_id)
            send_message(chat_id, f"✅ Количество участников обновлено: <b>{int(text)}</b>", reply_markup=admin_panel_keyboard())
            return True
        target_id = find_user_by_target(text)
        if target_id is None:
            send_message(chat_id, "Не нашёл пользователя. Формат: <code>id 123456789</code> или <code>@username</code>. Если @username не найден — попроси человека написать /start боту.", reply_markup=cancel_keyboard())
            return True
        target_rec = get_user(target_id)
        clear_state(admin_id)
        apply_target_action(chat_id, admin_id, str(action), target_id, username=target_rec.get("username"))
        return True
    if flow == "admin_reply":
        kind = state.get("kind")
        item_id = int(state.get("item_id") or 0)
        filename = filename_for_kind(str(kind))
        if not filename:
            clear_state(admin_id)
            return False
        items = read_json(filename, [])
        found = None
        for item in items:
            if int(item.get("id", -1)) == item_id:
                found = item
                break
        if not found:
            clear_state(admin_id)
            send_message(chat_id, "Запись не найдена.", reply_markup=admin_panel_keyboard())
            return True
        reply = {"admin_id": admin_id, "admin_username": user.get("username"), "text": text, "created_at": now_str()}
        found.setdefault("replies", []).append(reply)
        if found.get("status") == "new":
            found["status"] = "answered"
        found["updated_at"] = now_str()
        write_json(filename, items)
        target_user = int(found.get("user_id") or 0)
        if target_user:
            try:
                send_message(target_user, f"💬 <b>Ответ администрации ZRG_Oblivion:</b>\n\n{escape(text)}", reply_markup=back_keyboard(target_user))
            except Exception as e:
                logging.error("Cannot send admin reply to user %s: %s", target_user, e)
        clear_state(admin_id)
        send_message(chat_id, f"✅ Ответ отправлен пользователю по записи #{item_id}.", reply_markup=admin_panel_keyboard())
        return True
    return False


def handle_admin_action(cq: Dict[str, Any]) -> None:
    callback_id = cq.get("id", "")
    user = cq.get("from", {})
    admin_id = int(user.get("id"))
    message = cq.get("message", {})
    chat_id = int(message.get("chat", {}).get("id", admin_id))
    message_id = int(message.get("message_id", 0) or 0)
    data = cq.get("data", "")
    remember_user(user)

    if not is_admin(admin_id):
        answer_callback(callback_id, "Нет доступа", True)
        send_admin_denied(chat_id, admin_id)
        return

    parts = data.split(":")
    if data == "admin:panel":
        answer_callback(callback_id, "Админ-панель")
        send_admin_panel(chat_id, admin_id)
        return
    if data == "admin:rewrite":
        answer_callback(callback_id, "Что обновлено")
        send_message(chat_id, rewrite_notice_text(), reply_markup=admin_panel_keyboard())
        return
    if data.startswith("admin:prompt:"):
        action = parts[2] if len(parts) > 2 else ""
        answer_callback(callback_id, "Введите цель")
        prompt_target(chat_id, admin_id, action)
        return
    if data.startswith("admin:apps:"):
        category = parts[2] if len(parts) > 2 else "new"
        answer_callback(callback_id, "Список заявок")
        send_application_category(chat_id, category)
        return
    if data.startswith("admin:appview:"):
        try:
            item_id = int(parts[2])
        except Exception:
            answer_callback(callback_id, "Неверный ID", True)
            return
        answer_callback(callback_id, "Заявка")
        send_application_detail(chat_id, item_id)
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
    filename = filename_for_kind(kind)
    if not filename:
        answer_callback(callback_id, "Неизвестный тип", True)
        return
    try:
        item_id = int(raw_id)
    except ValueError:
        answer_callback(callback_id, "Неверный ID", True)
        return

    items = read_json(filename, [])
    item = next((x for x in items if int(x.get("id", -1)) == item_id), None)
    if not item:
        answer_callback(callback_id, "Запись не найдена", True)
        return

    reviewer_id = int(item.get("reviewer_id") or 0)
    if reviewer_id and reviewer_id != admin_id and action in {"take", "approve", "reject", "reply", "close"}:
        answer_callback(callback_id, f"Уже рассматривает админ {reviewer_id}", True)
        send_message(chat_id, f"👀 Запись #{item_id} уже рассматривает {user_link(reviewer_id)}.")
        return

    target_user = int(item.get("user_id") or 0)

    if action in {"ban", "mute", "disable", "unban"}:
        if target_user:
            apply_target_action(chat_id, admin_id, action, target_user, username=item.get("username"))
            answer_callback(callback_id, "Готово")
        return

    if action == "take":
        item["status"] = "reviewing"
        item["reviewer_id"] = admin_id
        item["reviewer_name"] = user.get("username") or user.get("first_name") or str(admin_id)
        item["updated_at"] = now_str()
        write_json(filename, items)
        answer_callback(callback_id, "Вы взяли запись")
        notify_admins(f"👀 Админ {user_link(admin_id, item.get('reviewer_name'))} уже рассматривает запись #{item_id}.", keyboard=admin_action_keyboard(kind, item))
        return

    if action == "reply":
        set_state(admin_id, {"flow": "admin_reply", "kind": kind, "item_id": item_id, "created_at": now_str()})
        answer_callback(callback_id, "Напишите ответ")
        send_message(chat_id, f"💬 Напиши ответ пользователю по записи #{item_id}. Следующее сообщение уйдёт ему в бот.", reply_markup=cancel_keyboard())
        return

    if kind == "application":
        if action == "restore":
            old_status = str(item.get("status") or "new")
            item["status"] = "new"
            item["restored_from"] = old_status
            item["restored_by"] = admin_id
            item["restored_at"] = now_str()
            item["created_at"] = now_str()
            item.pop("admin_id", None)
            item.pop("admin_username", None)
            item.pop("reviewer_id", None)
            item.pop("reviewer_name", None)
            item["updated_at"] = now_str()
            write_json(filename, items)
            answer_callback(callback_id, "Заявка восстановлена")
            send_message(chat_id, f"♻️ Заявка #{item_id} восстановлена и снова находится в недавно поданных.", reply_markup=admin_action_keyboard("application", item))
            if target_user:
                try:
                    send_message(target_user, "♻️ Ваша заявка восстановлена администрацией и снова находится на рассмотрении.", reply_markup=back_keyboard(target_user))
                except Exception as e:
                    logging.error("Cannot notify restored user %s: %s", target_user, e)
            return
        if item.get("status") not in {"new", "reviewing", "answered"}:
            answer_callback(callback_id, "Заявка уже обработана", True)
            return
        if action == "approve":
            item.update({"status": "approved", "admin_id": admin_id, "admin_username": user.get("username") or str(admin_id), "updated_at": now_str()})
            write_json(filename, items)
            answer_callback(callback_id, "Заявка принята")
            if message_id:
                edit_message_reply_markup(chat_id, message_id)
            send_message(chat_id, f"✅ Заявка #{item_id} принята. Пользователю отправлена ссылка.", reply_markup=admin_panel_keyboard())
            if target_user:
                try: send_message(target_user, accept_text(False), reply_markup=back_keyboard(target_user))
                except Exception as e: logging.error("Cannot notify accepted user %s: %s", target_user, e)
            return
        if action == "reject":
            previous_rejects = user_rejection_count(target_user)
            item.update({"status": "rejected", "admin_id": admin_id, "admin_username": user.get("username") or str(admin_id), "updated_at": now_str()})
            write_json(filename, items)
            answer_callback(callback_id, "Заявка отклонена")
            if message_id:
                edit_message_reply_markup(chat_id, message_id)
            if target_user:
                if previous_rejects + 1 >= 2:
                    user_text = "❌ Заявка отклонена повторно. Подача заявок в клан для вас закрыта."
                else:
                    user_text = "❌ Заявка отклонена. Повторно подать заявку можно через 2 часа."
                try: send_message(target_user, user_text, reply_markup=back_keyboard(target_user))
                except Exception as e: logging.error("Cannot notify rejected user %s: %s", target_user, e)
            send_message(chat_id, f"❌ Заявка #{item_id} отклонена.", reply_markup=admin_panel_keyboard())
            return

    elif kind == "ticket":
        if action == "close":
            item.update({"status": "closed", "admin_id": admin_id, "admin_username": user.get("username") or str(admin_id), "updated_at": now_str()})
            write_json(filename, items)
            answer_callback(callback_id, "Тикет закрыт")
            if message_id:
                edit_message_reply_markup(chat_id, message_id)
            if target_user:
                try: send_message(target_user, "✅ Твоё обращение в техподдержку закрыто администратором.", reply_markup=back_keyboard(target_user))
                except Exception as e: logging.error("Cannot notify ticket user %s: %s", target_user, e)
            send_message(chat_id, f"✅ Тикет #{item_id} закрыт.", reply_markup=admin_panel_keyboard())
            return

    elif kind == "appeal":
        if action in {"approve", "reject"}:
            status = "approved" if action == "approve" else "rejected"
            user_text = "✅ Обжалование мута одобрено. Ожидай восстановления доступа к чату." if action == "approve" else "❌ Обжалование мута отклонено. Решение администрации оставлено в силе."
            item.update({"status": status, "admin_id": admin_id, "admin_username": user.get("username") or str(admin_id), "updated_at": now_str()})
            write_json(filename, items)
            answer_callback(callback_id, "Готово")
            if message_id:
                edit_message_reply_markup(chat_id, message_id)
            if target_user:
                try: send_message(target_user, user_text, reply_markup=back_keyboard(target_user))
                except Exception as e: logging.error("Cannot notify appeal user %s: %s", target_user, e)
            send_message(chat_id, f"✅ Обжалование #{item_id} обработано.", reply_markup=admin_panel_keyboard())
            return

    answer_callback(callback_id, "Неизвестное действие", True)


def auto_accept_applications() -> None:
    items = read_json("applications.json", [])
    changed = False
    for item in items:
        if item.get("status") not in {"new", "reviewing"}:
            continue
        created = parse_time_str(item.get("created_at"))
        if not created or time.time() - created < AUTO_ACCEPT_SECONDS:
            continue
        item["status"] = "auto_approved"
        item["updated_at"] = now_str()
        item["admin_id"] = 0
        item["admin_username"] = "auto"
        changed = True
        target_user = int(item.get("user_id") or 0)
        if target_user:
            try: send_message(target_user, accept_text(True), reply_markup=back_keyboard(target_user))
            except Exception as e: logging.error("Cannot auto-accept user %s: %s", target_user, e)
        notify_admins(f"🤖 Заявка #{item.get('id')} авто-принята через 3 часа. Пользователю отправлена ссылка.", keyboard=admin_action_keyboard("application", item))
    if changed:
        write_json("applications.json", items)


def send_rewrite_notice_once() -> None:
    settings = get_settings()
    if settings.get("rewrite_notice_version") == BOT_VERSION:
        return
    notify_admins(rewrite_notice_text(), keyboard=admin_panel_keyboard())
    settings["rewrite_notice_version"] = BOT_VERSION
    save_settings(settings)


def export_data(chat_id: int) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_path = DATA_DIR / f"zrg_export_{ts}.zip"
    files = ["users.json", "applications.json", "tickets.json", "appeals.json", "counters.json", "roles.json", "moderation.json", "settings.json", "states.json"]
    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # JSON файлы (из файлового бэкапа)
        for name in files:
            path = json_path(name)
            if path.exists():
                try:
                    zf.write(path, arcname=name)
                except Exception:
                    pass
        # Основной SQLite файл
        try:
            if DB_PATH.exists():
                zf.write(DB_PATH, arcname="bot.db")
        except Exception:
            pass
        # Последние бэкапы
        try:
            for p in (DB_BACKUP_DIR.glob("*.db") if DB_BACKUP_DIR.exists() else []):
                if p.stat().st_size < 20_000_000:  # не включать огромные
                    zf.write(p, arcname=f"backups/{p.name}")
            for p in (DB_BACKUP_DIR.glob("*.json") if DB_BACKUP_DIR.exists() else []):
                zf.write(p, arcname=f"backups/{p.name}")
        except Exception:
            pass
        # Также дамп из SQLite в один большой JSON для удобства
        try:
            conn = _get_conn()
            cur = conn.execute("SELECT name, data FROM kv_store")
            rows = cur.fetchall()
            conn.close()
            dump_dict = {}
            for name, data in rows:
                try:
                    dump_dict[name] = json.loads(data)
                except Exception:
                    dump_dict[name] = data
            dump_bytes = json.dumps(dump_dict, ensure_ascii=False, indent=2).encode("utf-8")
            zf.writestr(f"full_dump_{ts}.json", dump_bytes)
        except Exception:
            pass
    send_local_document(chat_id, export_path, f"📦 Экспорт данных ZRG Bot (SQLite + JSON) {ts}")
    # периодический бэкап
    try:
        backup_database(force=False)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# UPDATE ROUTING
# ---------------------------------------------------------------------------


def handle_callback(cq: Dict[str, Any]) -> None:
    data = cq.get("data", "")
    user = cq.get("from", {})
    user_id = int(user.get("id"))
    remember_user(user)
    message = cq.get("message", {})
    chat_id = int(message.get("chat", {}).get("id", user_id))
    callback_id = cq.get("id", "")

    if not check_user_allowed(chat_id, user_id):
        answer_callback(callback_id, "Доступ ограничен", True)
        return

    if data.startswith("cap:"):
        handle_captcha_callback(cq)
        return

    if not antiflood_ok(chat_id, user_id):
        answer_callback(callback_id, "Антифлуд 5 сек", True)
        return

    if data.startswith("admin:"):
        handle_admin_action(cq)
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
    if data == "form:app:back":
        handle_application_back(cq)
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

    answer_callback(callback_id, "Неизвестная кнопка", True)


def handle_message(message: Dict[str, Any]) -> None:
    chat = message.get("chat", {})
    chat_id = int(chat.get("id"))
    chat_type = chat.get("type", "private")
    user = message.get("from", {})
    if not user:
        return
    remember_user(user)
    user_id = int(user.get("id"))
    text = get_text(message)
    command = text.split()[0].split("@", 1)[0].lower() if text.startswith("/") else ""

    # Команды для группы: обновить число участников клана.
    if chat_type != "private":
        if command in {"/members", "/set_members", "/clan_members", "/set_clan_members"}:
            if not is_admin(user_id):
                send_message(chat_id, "Нет доступа. Команда только для админов бота.")
                return
            parts = text.split()
            if len(parts) < 2 or not parts[1].isdigit():
                send_message(chat_id, "Формат: <code>/members 59</code>")
                return
            set_clan_members(int(parts[1]), f"Обновлено в группе: {now_str()}")
            send_message(chat_id, f"✅ В боте обновлено число участников клана: <b>{int(parts[1])}</b>")
            return
        if text.startswith("/start") or text.startswith("/help"):
            send_message(chat_id, "Напиши мне в личные сообщения — там доступно меню клана.")
        return

    if not check_user_allowed(chat_id, user_id):
        return

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

    if not antiflood_ok(chat_id, user_id):
        return

    # Админские состояния работают даже без капчи, но только для админов.
    state = get_state(user_id)
    if state and is_admin(user_id) and process_admin_state(message, state):
        return

    if command in {"/members", "/set_members", "/clan_members", "/set_clan_members"}:
        if not is_admin(user_id):
            send_admin_denied(chat_id, user_id)
            return
        parts = text.split()
        if len(parts) < 2 or not parts[1].isdigit():
            send_message(chat_id, "Формат: <code>/members 59</code>", reply_markup=admin_panel_keyboard())
            return
        set_clan_members(int(parts[1]), f"Обновлено админом {user_id}: {now_str()}")
        send_message(chat_id, f"✅ Количество участников обновлено: <b>{int(parts[1])}</b>", reply_markup=admin_panel_keyboard())
        return

    if command == "/admin":
        clear_state(user_id)
        send_admin_panel(chat_id, user_id)
        return

    if not ensure_access(chat_id, user_id):
        return

    if command in {"/menu", "/help"}:
        clear_state(user_id)
        send_main_menu(chat_id, user_id)
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

    # Инициализируем SQLite БД сразу после проверки токена
    try:
        _init_sqlite_db()
        print(f"DB INIT: {DB_PATH} exists={DB_PATH.exists()} DATA_DIR={DATA_DIR}", flush=True)
        logging.info(f"SQLite DB initialized: {DB_PATH} size={DB_PATH.stat().st_size if DB_PATH.exists() else 0} bytes")
    except Exception as e:
        logging.exception(f"DB init error: {e}")

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
        logging.info("ONLINE @%s | DATA_DIR=%s | ADMINS=%s", username, DATA_DIR, all_admin_ids())
        try:
            send_rewrite_notice_once()
        except Exception as e:
            logging.warning("rewrite notice failed: %s", e)
    except Exception:
        logging.exception("Cannot get bot info")
        raise

    offset: Optional[int] = None
    last_maintenance = 0.0
    while True:
        try:
            if time.time() - last_maintenance >= 60:
                last_maintenance = time.time()
                auto_accept_applications()

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
