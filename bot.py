import sys
import io
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import asyncio
import logging
import sqlite3
import time
import uuid
import os
import socket
import base64
from datetime import datetime

import aiohttp
from aiohttp.resolver import ThreadedResolver
from aiogram import Bot, Dispatcher, types, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Message,
    FSInputFile,
    BufferedInputFile,
    LabeledPrice,
    PreCheckoutQuery,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ----------------- CONFIG -----------------
BOT_TOKEN = "8965669865:AAHk4KKEM5AAFxj_mNyKeVs5zzq-htrGRq4"
BOT_USERNAME = "vpnbot14432_bot"
BRAND_NAME = "Welwes VPN"
SUPPORT_USERNAME = "welwesvpn"
SECRET_ADMIN_KEY = "welwes2026"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "users.db")
BANNER_PATH = os.path.join(BASE_DIR, "welwes_banner.jpg")
AVATAR_PATH = os.path.join(BASE_DIR, "welwes_avatar.png")

# Live Subscription Endpoint on Germany node:
MASTER_SUB_URL = "http://germany-d4.h1cloud.net:25132/sub/a8c648dd-96e0-4db7-a4f4-5288986f6a9a"

# Direct VLESS strings:
GERMANY_VLESS = "vless://a8c648dd-96e0-4db7-a4f4-5288986f6a9a@germany-d4.h1cloud.net:25133?type=tcp&security=reality&sni=www.microsoft.com&fp=chrome&pbk=7chjcukFlC6QB_UOdc4D5VYD1ElsdaZHHb9sGrfcvUQ&sid=7a220762ea8b1f10&spx=%2F&encryption=none#🇩🇪 Германия · YouTube 4K (100M)"
FINLAND_VLESS = "vless://a8c648dd-96e0-4db7-a4f4-5288986f6a9a@fi4.h1cloud.net:26105?type=tcp&security=reality&sni=dl.google.com&fp=chrome&pbk=j6fX9DcQuNiixZxON6sm6yulBlkys11Z8vAtIWjMwhw&sid=a01d409410c3660f&spx=%2F&encryption=none#🇫🇮 Финляндия · Игры & Discord (20ms)"

# ----------------- TARIFFS & PROMO -----------------
PROMO_DISCOUNT_PERCENT = 45
ACTIVE_PROMO_CODE = "WELWES45"

FRIEND_DISCOUNT_PERCENT = 15
FRIEND_BONUS_HOURS = 6

BASE_TARIFFS = {
    "1d": {"name": "1 день", "days": 1, "price_rub": 15, "stars": 10, "discountable": False},
    "7d": {"name": "7 дней", "days": 7, "price_rub": 39, "stars": 25, "discountable": True},
    "30d": {"name": "30 дней (Месяц)", "days": 30, "price_rub": 99, "stars": 65, "hit": True, "discountable": True},
    "90d": {"name": "90 дней (3 месяца)", "days": 90, "price_rub": 249, "stars": 160, "discountable": True},
    "180d": {"name": "180 дней (Полгода)", "days": 180, "price_rub": 449, "stars": 290, "discountable": True},
    "365d": {"name": "365 дней (1 Год)", "days": 365, "price_rub": 799, "stars": 520, "discountable": True},
}

def get_tariff_prices(tid: str, is_discount_active: bool):
    t = BASE_TARIFFS[tid]
    if is_discount_active and t.get("discountable"):
        disc_rub = max(1, int(round(t["price_rub"] * (100 - PROMO_DISCOUNT_PERCENT) / 100)))
        disc_stars = max(1, int(round(t["stars"] * (100 - PROMO_DISCOUNT_PERCENT) / 100)))
        return disc_rub, disc_stars, True
    return t["price_rub"], t["stars"], False

logging.basicConfig(level=logging.INFO)

# ----------------- RELIABLE NETWORK RESOLVER -----------------
# Bypasses RKN IP throttling for api.telegram.org by resolving to working Telegram node (2.4ms ping):
class TelegramCustomResolver(ThreadedResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host == "api.telegram.org":
            return [{
                "hostname": host,
                "host": "149.154.167.199",
                "port": port,
                "family": family,
                "proto": 0,
                "flags": socket.AI_NUMERICHOST
            }]
        return await super().resolve(host, port, family)

class DirectAiohttpSession(AiohttpSession):
    async def create_session(self) -> aiohttp.ClientSession:
        connector = aiohttp.TCPConnector(resolver=TelegramCustomResolver())
        return aiohttp.ClientSession(connector=connector)

# ----------------- DATABASE -----------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            registered_at INTEGER,
            trial_used INTEGER DEFAULT 0,
            sub_until INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT NULL,
            discount_active INTEGER DEFAULT 0
        )
    """)
    for col, ctype in [("referrer_id", "INTEGER DEFAULT NULL"), ("discount_active", "INTEGER DEFAULT 0")]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {ctype}")
        except sqlite3.OperationalError:
            pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            days INTEGER,
            created_by INTEGER,
            used_by INTEGER DEFAULT NULL,
            used_at INTEGER DEFAULT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS stars_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            days INTEGER,
            timestamp INTEGER
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS card_orders (
            order_id TEXT PRIMARY KEY,
            user_id INTEGER,
            tariff_id TEXT,
            days INTEGER,
            amount INTEGER,
            timestamp INTEGER,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, registered_at, trial_used, sub_until, is_admin, referrer_id, discount_active FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def register_user(user_id: int, username: str, first_name: str, referrer_id: int = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    exists = c.fetchone()
    if not exists:
        c.execute("""
            INSERT INTO users (user_id, username, first_name, registered_at, trial_used, sub_until, is_admin, referrer_id, discount_active)
            VALUES (?, ?, ?, ?, 0, 0, 0, ?, 0)
        """, (user_id, username or "", first_name or "", int(time.time()), referrer_id))
    conn.commit()
    conn.close()

def set_sub(user_id: int, days: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = int(time.time())
    c.execute("SELECT sub_until, referrer_id FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    current_sub = row[0] if row else 0
    ref_id = row[1] if row else None

    start_from = max(now, current_sub)
    new_sub = start_from + int(days * 86400)
    c.execute("UPDATE users SET sub_until = ? WHERE user_id = ?", (new_sub, user_id))
    conn.commit()
    conn.close()
    return new_sub, ref_id

def set_discount_active(user_id: int, active: int = 1):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET discount_active = ? WHERE user_id = ?", (active, user_id))
    conn.commit()
    conn.close()

def set_trial_used(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET trial_used = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def make_admin(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def is_admin(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT is_admin FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return bool(row and row[0] == 1)

def get_all_admins():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE is_admin = 1")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    now = int(time.time())
    c.execute("SELECT COUNT(*) FROM users WHERE sub_until > ?", (now,))
    active_subs = c.fetchone()[0]
    conn.close()
    return total_users, active_subs

def get_referral_stats(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    invited = c.fetchone()[0]
    now = int(time.time())
    c.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ? AND (sub_until > ? OR trial_used = 1)", (user_id, now))
    active_referrals = c.fetchone()[0]
    conn.close()
    return invited, active_referrals

def get_all_user_ids():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def add_stars_payment(user_id: int, amount: int, days: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO stars_payments (user_id, amount, days, timestamp) VALUES (?, ?, ?, ?)",
              (user_id, amount, days, int(time.time())))
    conn.commit()
    conn.close()

def create_card_order(order_id: str, user_id: int, tariff_id: str, days: int, amount: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO card_orders (order_id, user_id, tariff_id, days, amount, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
              (order_id, user_id, tariff_id, days, amount, int(time.time())))
    conn.commit()
    conn.close()

def get_card_order(order_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT order_id, user_id, tariff_id, days, amount, timestamp, status FROM card_orders WHERE order_id = ?", (order_id,))
    row = c.fetchone()
    conn.close()
    return row

def complete_card_order(order_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE card_orders SET status = 'completed' WHERE order_id = ?", (order_id,))
    conn.commit()
    conn.close()

def get_total_stars_earned():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT SUM(amount), COUNT(*) FROM stars_payments")
    row = c.fetchone()
    conn.close()
    total_stars = row[0] if row and row[0] else 0
    count_payments = row[1] if row and row[1] else 0
    return total_stars, count_payments

def create_promocode(code: str, days: int, creator_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO promocodes (code, days, created_by) VALUES (?, ?, ?)", (code, days, creator_id))
        conn.commit()
        success = True
    except sqlite3.IntegrityError:
        success = False
    conn.close()
    return success

def redeem_promocode(code: str, user_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT days, used_by FROM promocodes WHERE code = ?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None, "invalid"
    days, used_by = row
    if used_by is not None:
        conn.close()
        return None, "already_used"
    now = int(time.time())
    c.execute("UPDATE promocodes SET used_by = ?, used_at = ? WHERE code = ?", (user_id, now, code))
    conn.commit()
    conn.close()
    new_sub, _ = set_sub(user_id, days)
    return days, "ok"

DEFAULT_SBP_LINK = "https://www.tbank-online.com/rm/r_DxGqSWQmhe.LyaUAcktKx/RGo2I67940"

def get_setting(key: str, default: str = "") -> str:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row and row[0] else default

def set_setting(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# ----------------- RAKETA STYLE BUNDLE FORMATTER -----------------
def generate_sub_bundle_b64(user_id: int = 0) -> str:
    """Generates Raketa-style dynamic configuration with info nodes & servers"""
    lines = [
        f"vless://00000000-0000-0000-0000-000000000000@0.0.0.0:1?encryption=none&type=tcp&security=none#⚡️ Наш бот: @{BOT_USERNAME}",
        f"vless://00000000-0000-0000-0000-000000000000@0.0.0.0:1?encryption=none&type=tcp&security=none#💬 Поддержка: @{SUPPORT_USERNAME}",
        GERMANY_VLESS,
        FINLAND_VLESS
    ]
    raw_content = "\n".join(lines) + "\n"
    return base64.b64encode(raw_content.encode("utf-8")).decode("utf-8")

# ----------------- FSM STATES -----------------
class Form(StatesGroup):
    waiting_for_promocode = State()
    waiting_for_support_ticket = State()
    waiting_for_admin_reply = State()
    waiting_for_broadcast = State()
    waiting_for_sbp_link = State()

# ----------------- KEYBOARDS -----------------
def main_menu_kb(user_id: int):
    user = get_user(user_id)
    now = int(time.time())
    has_sub = user and user[5] > now
    trial_used = user and user[4] == 1
    admin = is_admin(user_id)

    kb = []
    if not has_sub and not trial_used:
        kb.append([InlineKeyboardButton(text="🎁 Попробовать бесплатно (6 часов)", callback_data="get_trial")])

    # Exact layout matching user's reference screenshot:
    kb.append([InlineKeyboardButton(text="💳 Покупка | Продление", callback_data="buy_menu")])
    kb.append([InlineKeyboardButton(text="🔑 Мои ключи", callback_data="my_keys")])
    kb.append([InlineKeyboardButton(text="👥 Партнёрская программа", callback_data="affiliate")])
    kb.append([InlineKeyboardButton(text="🎁 Пригласить друга", callback_data="invite_friend")])
    kb.append([InlineKeyboardButton(text="ℹ️ Поддержка ↗", url=f"https://t.me/{SUPPORT_USERNAME}")])

    if admin:
        kb.append([InlineKeyboardButton(text="👑 Панель Создателя (Админка)", callback_data="admin_panel")])

    return InlineKeyboardMarkup(inline_keyboard=kb)

def sub_active_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Скопировать ссылку подписки", callback_data="copy_sub")],
        [InlineKeyboardButton(text="📦 Скопировать Base64 ключ (Всё в 1)", callback_data="copy_bundle")],
        [InlineKeyboardButton(text="🇩🇪 Ключ Германия", callback_data="copy_de"), InlineKeyboardButton(text="🇫🇮 Ключ Финляндия", callback_data="copy_fi")],
        [InlineKeyboardButton(text="📁 Скачать файл подписки (.txt)", callback_data="download_sub_file")],
        [InlineKeyboardButton(text="📖 Инструкция по подключению", callback_data="instructions")],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_main")]
    ])

def buy_tariffs_kb(user_id: int):
    user = get_user(user_id)
    is_disc = bool(user and user[8] == 1)

    kb = []
    if is_disc:
        kb.append([InlineKeyboardButton(text="✅ Скидка -45% АКТИВНА (WELWES45)", callback_data="promo_already_active")])
    else:
        kb.append([InlineKeyboardButton(text="🔥 Активировать скидку -45% (WELWES45)", callback_data="activate_promo45")])

    for tid, t in BASE_TARIFFS.items():
        rub, stars, has_disc = get_tariff_prices(tid, is_disc)
        hit_mark = " 🔥" if t.get("hit") else ""
        if has_disc:
            text = f"{t['name']} — {rub} ₽ (было ~{t['price_rub']}~) / {stars} ⭐ [-45%]{hit_mark}"
        else:
            text = f"{t['name']} — {rub} ₽ / {stars} ⭐{hit_mark}"

        kb.append([InlineKeyboardButton(text=text, callback_data=f"tariff_{tid}")])

    kb.append([InlineKeyboardButton(text="🎟️ Ввести промокод / FunPay", callback_data="enter_promo")])
    kb.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_main")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def choose_payment_method_kb(user_id: int, tid: str):
    user = get_user(user_id)
    is_disc = bool(user and user[8] == 1)
    rub, stars, _ = get_tariff_prices(tid, is_disc)
    t = BASE_TARIFFS[tid]

    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⭐ Оплатить Звёздами ({stars} ⭐ в 1 клик)", callback_data=f"pay_stars_{tid}")],
        [InlineKeyboardButton(text=f"💳 Оплатить картой / СБП ({rub} ₽)", callback_data=f"pay_card_{tid}")],
        [InlineKeyboardButton(text="◀️ Назад к тарифам", callback_data="buy_menu")]
    ])

def back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_main")]
    ])

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾️ Выдать себе вечный VPN (100 дней)", callback_data="admin_self_sub")],
        [InlineKeyboardButton(text="⭐ Баланс и вывод Звёзд (Stars)", callback_data="admin_stars_balance")],
        [InlineKeyboardButton(text="🔗 Настроить ссылку СБП для оплаты", callback_data="admin_set_sbp")],
        [InlineKeyboardButton(text="🖼️ Получить официальную Аву бота", callback_data="admin_get_avatar")],
        [InlineKeyboardButton(text="🎟️ Создать промокод для FunPay", callback_data="admin_gen_promo")],
        [InlineKeyboardButton(text="📊 Статистика пользователей", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Рассылка всем пользователям", callback_data="admin_broadcast_prompt")],
        [InlineKeyboardButton(text="◀️ Выйти в меню", callback_data="back_main")]
    ])

# ----------------- BOT SETUP -----------------
session = DirectAiohttpSession()
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher(storage=MemoryStorage())

# ----------------- HANDLERS -----------------
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    
    # Check referral start:
    ref_id = None
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            potential_ref = int(args[1].replace("ref_", ""))
            if potential_ref != message.from_user.id:
                ref_id = potential_ref
        except Exception:
            pass

    register_user(message.from_user.id, message.from_user.username, message.from_user.first_name, ref_id)

    # In Raketa VPN style: clean banner with buttons directly attached:
    if os.path.exists(BANNER_PATH):
        try:
            photo = FSInputFile(BANNER_PATH)
            await message.answer_photo(photo, reply_markup=main_menu_kb(message.from_user.id))
            return
        except Exception as e:
            logging.error(f"Error sending banner: {e}")

    await message.answer(f"⚡ **Добро пожаловать в {BRAND_NAME}!**", reply_markup=main_menu_kb(message.from_user.id), parse_mode="Markdown")

@dp.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) > 1 and parts[1] == SECRET_ADMIN_KEY:
        make_admin(message.from_user.id)
        await message.answer("👑 **Поздравляю, Создатель! Права администратора успешно активированы!**", reply_markup=admin_kb(), parse_mode="Markdown")
    elif is_admin(message.from_user.id):
        await message.answer("👑 **Панель Создателя Welwes VPN:**", reply_markup=admin_kb(), parse_mode="Markdown")
    else:
        await message.answer("🔒 Введите пароль администратора в формате:\n`/admin welwes2026`", parse_mode="Markdown")

@dp.callback_query(F.data == "back_main")
async def cb_back_main(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    if os.path.exists(BANNER_PATH):
        photo = FSInputFile(BANNER_PATH)
        await call.message.answer_photo(photo, reply_markup=main_menu_kb(call.from_user.id))
    else:
        await call.message.answer(f"⚡ **Главное меню {BRAND_NAME}:**", reply_markup=main_menu_kb(call.from_user.id), parse_mode="Markdown")

# --- TRIAL ---
@dp.callback_query(F.data == "get_trial")
async def cb_get_trial(call: CallbackQuery):
    await call.answer()
    user = get_user(call.from_user.id)
    if not user:
        register_user(call.from_user.id, call.from_user.username, call.from_user.first_name)
        user = get_user(call.from_user.id)
    
    if user[4] == 1:
        await call.message.answer("Вы уже использовали бесплатный пробный период!")
        return

    _, ref_id = set_sub(call.from_user.id, 0.25) # 6 hours = 0.25 days
    set_trial_used(call.from_user.id)

    # Reward referrer if exists (+6 hours):
    if ref_id:
        try:
            set_sub(ref_id, 0.25) # +6 hours bonus
            await bot.send_message(
                ref_id,
                f"🎉 **Ваш друг {call.from_user.first_name} активировал Welwes VPN!**\nВам начислено **+6 часов** бесплатной подписки в подарок!",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    text = (
        f"🎉 **Вам выдан бесплатный тест на 6 часов!**\n\n"
        f"🔗 **Ваша универсальная ссылка-подписка:**\n"
        f"`{MASTER_SUB_URL}`\n\n"
        f"📱 **Как подключить за 1 минуту:**\n"
        f"1. Скопируйте ссылку выше (нажмите на неё).\n"
        f"2. Откройте приложение **Happ** (или Hiddify / Streisand).\n"
        f"3. Нажмите **«+» → Добавить подписку** и вставьте ссылку!\n"
        f"4. Серверы **Германия** и **Финляндия** добавятся автоматически!\n\n"
        f"💡 *Совет: если в Happ пишет 'u/a' или нет доступа к сети, в настройках Happ (DNS) выберите DoH (Cloudflare 1.1.1.1).* "
    )
    await call.message.answer(text, reply_markup=sub_active_kb(), parse_mode="Markdown")

# --- MY KEYS / SUBSCRIPTION ---
@dp.callback_query(F.data.in_(["my_keys", "my_sub"]))
async def cb_my_keys(call: CallbackQuery):
    await call.answer()
    user = get_user(call.from_user.id)
    now = int(time.time())
    if not user or user[5] <= now:
        text = (
            f"❌ **У вас пока нет активной подписки.**\n\n"
            f"Вы можете мгновенно оформить доступ со скидкой **-45%** или использовать промокод:"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Купить подписку (-45%)", callback_data="buy_menu")],
            [InlineKeyboardButton(text="🎟️ Ввести промокод / FunPay", callback_data="enter_promo")],
            [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_main")]
        ])
        await call.message.answer(text, reply_markup=kb, parse_mode="Markdown")
        return

    expire_dt = datetime.fromtimestamp(user[5]).strftime("%d.%m.%Y в %H:%M")
    days_left = max(0, int((user[5] - now) / 86400))
    hours_left = max(0, int(((user[5] - now) % 86400) / 3600))

    text = (
        f"🔑 **Ваши ключи и подписка {BRAND_NAME}:**\n\n"
        f"⏳ **Статус:** 🟢 АКТИВНА\n"
        f"📅 **Действует до:** `{expire_dt}` (осталось ~{days_left} дн. {hours_left} ч.)\n\n"
        f"🌍 **Входящие локации:**\n"
        f"• 🇩🇪 **Германия** — YouTube 4K 60FPS (100 Mbit/s)\n"
        f"• 🇫🇮 **Финляндия** — Discord & Игры (пинг 20ms)\n\n"
        f"🔗 **Ваша универсальная ссылка подписки:**\n"
        f"`{MASTER_SUB_URL}`\n\n"
        f"👇 *Используйте кнопки ниже для быстрого копирования или скачивания конфигурации:*"
    )
    await call.message.answer(text, reply_markup=sub_active_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "copy_sub")
async def cb_copy_sub(call: CallbackQuery):
    await call.answer("Ссылка подписки скопирована!")
    await call.message.answer(f"🔗 **Ваша ссылка-подписка:**\n`{MASTER_SUB_URL}`", parse_mode="Markdown")

@dp.callback_query(F.data == "copy_bundle")
async def cb_copy_bundle(call: CallbackQuery):
    await call.answer("Base64 конфигурация скопирована!")
    b64 = generate_sub_bundle_b64(call.from_user.id)
    await call.message.answer(
        f"📦 **Base64 подписка Welwes VPN (Все серверы в 1 ключе):**\n\n"
        f"`{b64}`\n\n"
        f"*(Скопируйте и нажмите «Импорт из буфера» в приложении Happ)*",
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "copy_de")
async def cb_copy_de(call: CallbackQuery):
    await call.answer("Ключ Германия отправлен!")
    await call.message.answer(f"🇩🇪 **Прямой ключ Германия (VLESS Reality):**\n`{GERMANY_VLESS}`", parse_mode="Markdown")

@dp.callback_query(F.data == "copy_fi")
async def cb_copy_fi(call: CallbackQuery):
    await call.answer("Ключ Финляндия отправлен!")
    await call.message.answer(f"🇫🇮 **Прямой ключ Финляндия (VLESS Reality):**\n`{FINLAND_VLESS}`", parse_mode="Markdown")

@dp.callback_query(F.data == "download_sub_file")
async def cb_download_sub_file(call: CallbackQuery):
    await call.answer()
    raw_content = f"{GERMANY_VLESS}\n{FINLAND_VLESS}\n"
    file_bytes = raw_content.encode("utf-8")
    doc = BufferedInputFile(file_bytes, filename=f"WelwesVPN_Config_{call.from_user.id}.txt")
    await call.message.answer_document(doc, caption="📁 **Ваш готовый файл конфигурации Welwes VPN!**\n\nОткройте его через приложение Happ или Hiddify.")

# --- BUY & PROMO ENGINE ---
@dp.callback_query(F.data == "buy_menu")
async def cb_buy_menu(call: CallbackQuery):
    await call.answer()
    user = get_user(call.from_user.id)
    is_disc = bool(user and user[8] == 1)

    disc_status = "🟢 **АКТИВИРОВАНА (-45%)**" if is_disc else "⚪ Не активирована"
    text = (
        f"💳 **Покупка | Продление подписки {BRAND_NAME}:**\n\n"
        f"🔥 **Скидка -45% по промокоду `{ACTIVE_PROMO_CODE}`:** {disc_status}\n"
        f"*(Скидка действует на ВСЕ тарифы от 7 дней и выше: 7д, 30д, 90д, 180д, 365д!)*\n\n"
        f"🚀 **Автоматическая мгновенная выдача** ключей за 1 секунду сразу после оплаты!\n\n"
        f"👇 **Выберите подходящий тариф:**"
    )
    await call.message.answer(text, reply_markup=buy_tariffs_kb(call.from_user.id), parse_mode="Markdown")

@dp.callback_query(F.data == "activate_promo45")
async def cb_activate_promo45(call: CallbackQuery):
    set_discount_active(call.from_user.id, 1)
    await call.answer("🎉 Промокод WELWES45 (-45%) успешно применён!", show_alert=True)
    await cb_buy_menu(call)

@dp.callback_query(F.data == "promo_already_active")
async def cb_promo_already_active(call: CallbackQuery):
    await call.answer("Скидка -45% уже применена ко всем вашим тарифам от 7 дней!", show_alert=False)

@dp.callback_query(F.data.startswith("tariff_"))
async def cb_choose_tariff(call: CallbackQuery):
    await call.answer()
    tid = call.data.replace("tariff_", "")
    t = BASE_TARIFFS.get(tid)
    if not t:
        return

    user = get_user(call.from_user.id)
    is_disc = bool(user and user[8] == 1)
    rub, stars, has_disc = get_tariff_prices(tid, is_disc)

    disc_note = f"\n🏷️ *Скидка 45% по промокоду WELWES45 учтена!* (Экономия {t['price_rub'] - rub} ₽)" if has_disc else ""

    text = (
        f"💎 **Тариф: {t['name']}**\n\n"
        f"• Стоимость в рублях: **{rub} ₽**\n"
        f"• Стоимость в звёздах: **{stars} ⭐**{disc_note}\n\n"
        f"🌍 Полный доступ ко всем локациям: 🇩🇪 Германия + 🇫🇮 Финляндия\n"
        f"⚡ 100 Mbit/s, YouTube 4K 60FPS, Discord, игры с пингом 20ms\n"
        f"🤖 **Ключ выдаётся БОТОМ АВТОМАТИЧЕСКИ сразу после оплаты!**\n\n"
        f"👇 **Выберите способ оплаты:**"
    )
    await call.message.answer(text, reply_markup=choose_payment_method_kb(call.from_user.id, tid), parse_mode="Markdown")

# --- STARS AUTOMATED PAYMENT ---
@dp.callback_query(F.data.startswith("pay_stars_"))
async def cb_send_stars_invoice(call: CallbackQuery):
    await call.answer()
    tid = call.data.replace("pay_stars_", "")
    t = BASE_TARIFFS.get(tid)
    if not t:
        return

    user = get_user(call.from_user.id)
    is_disc = bool(user and user[8] == 1)
    _, stars, _ = get_tariff_prices(tid, is_disc)

    prices = [LabeledPrice(label=f"Подписка Welwes VPN ({t['name']})", amount=stars)]

    await bot.send_invoice(
        chat_id=call.from_user.id,
        title=f"Welwes VPN — {t['name']}",
        description=f"Автоматическая выдача VPN (Германия + Финляндия, 100M, YouTube 4K, Discord) на {t['name']}.",
        payload=f"stars_sub_{t['days']}_{stars}",
        currency="XTR",
        prices=prices
    )

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    days = 30
    stars_amount = 65

    if payload.startswith("stars_sub_"):
        parts = payload.split("_")
        try:
            days = int(parts[2])
            stars_amount = int(parts[3])
        except Exception:
            pass

    # 1. Update user subscription:
    new_sub, ref_id = set_sub(message.from_user.id, days)
    expire_dt = datetime.fromtimestamp(new_sub).strftime("%d.%m.%Y в %H:%M")

    # 2. Record stars payment into database vault:
    add_stars_payment(message.from_user.id, stars_amount, days)

    # 3. Reward referrer if applicable (+6 hours):
    if ref_id:
        try:
            set_sub(ref_id, 0.25)
            await bot.send_message(
                ref_id,
                f"🎉 **Ваш реферал приобрёл подписку Welwes VPN!**\nВам начислено **+6 часов** бонуса к вашей подписке!",
                parse_mode="Markdown"
            )
        except Exception:
            pass

    text = (
        f"🎉 **ОПЛАТА УСПЕШНО ПОЛУЧЕНА!**\n\n"
        f"✅ Вам АВТОМАТИЧЕСКИ начислено **+{days} дней** подписки {BRAND_NAME}!\n"
        f"⏳ Подписка активна до: `{expire_dt}`\n\n"
        f"🔗 **Ваша персональная ссылка для подключения:**\n"
        f"`{MASTER_SUB_URL}`\n\n"
        f"🚀 Нажмите кнопку ниже для получения ваших ключей и быстрой настройки:"
    )
    await message.answer(text, reply_markup=sub_active_kb(), parse_mode="Markdown")

    # 4. Notify Admins:
    admins = get_all_admins()
    for a_id in admins:
        try:
            await bot.send_message(
                a_id,
                f"💰 **АВТОМАТИЧЕСКАЯ ОПЛАТА ЗВЁЗДАМИ!**\n\n"
                f"👤 Пользователь: {message.from_user.first_name} (@{message.from_user.username})\n"
                f"⭐ Получено: **+{stars_amount} Звёзд**\n"
                f"⏳ Тариф: **{days} дней**\n\n"
                f"Ключи выданы клиенту мгновенно!",
                parse_mode="Markdown"
            )
        except Exception:
            pass

# --- CARD / SBP AUTOMATED CHECKOUT ---
@dp.callback_query(F.data.startswith("pay_card_"))
async def cb_pay_card(call: CallbackQuery):
    await call.answer()
    tid = call.data.replace("pay_card_", "")
    t = BASE_TARIFFS.get(tid)
    if not t:
        return

    user = get_user(call.from_user.id)
    is_disc = bool(user and user[8] == 1)
    rub, stars, _ = get_tariff_prices(tid, is_disc)

    order_id = f"W{int(time.time()) % 1000000}"
    create_card_order(order_id, call.from_user.id, tid, t["days"], rub)

    sbp_url = get_setting("sbp_link", DEFAULT_SBP_LINK)

    text = (
        f"⚙️ **Создали запрос на покупку.**\n\n"
        f"Нажмите на кнопку: «💳 Оплатить»\n\n"
        f"⏳ Обработка платежа занимает до 1 часа, обычно — 1-5 минут."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {rub} ₽", url=sbp_url)],
        [InlineKeyboardButton(text="⚡ Проверить оплату", callback_data=f"check_card_{order_id}")],
        [InlineKeyboardButton(text=f"⭐ Оплатить Звёздами моментально ({stars} ⭐)", callback_data=f"pay_stars_{tid}")],
        [InlineKeyboardButton(text="◀️ Назад к тарифам", callback_data="buy_menu")]
    ])
    cancel_kb = types.ReplyKeyboardMarkup(
        keyboard=[[types.KeyboardButton(text="🔴 Отменить оплату")]],
        resize_keyboard=True
    )
    await call.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    await call.message.answer("Если передумали, нажмите кнопку отмены ниже 👇", reply_markup=cancel_kb)

@dp.callback_query(F.data.startswith("check_card_"))
async def cb_check_card_payment(call: CallbackQuery):
    order_id = call.data.replace("check_card_", "")
    order = get_card_order(order_id)
    if not order:
        await call.answer("Заказ не найден!", show_alert=True)
        return

    if order[6] == "completed":
        await call.answer("Этот заказ уже был успешно оплачен и активирован!", show_alert=True)
        return

    await call.answer("Запрос на проверку отправлен! Ключи будут выданы сразу после подтверждения.", show_alert=True)
    await call.message.answer(
        f"⏳ **Заказ #{order_id} на сумму {order[4]} ₽ проверяется!**\n\n"
        f"Вам не нужно писать в ЛС — как только оплата поступит, бот автоматически отправит вам ключи прямо в этот чат!",
        parse_mode="Markdown"
    )

    # Send 1-click confirmation alert to admins:
    admins = get_all_admins()
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить и выдать VPN", callback_data=f"adm_appr_{order_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"adm_rej_{order_id}")
        ]
    ])
    admin_msg = (
        f"🔔 **НОВЫЙ ЗАКАЗ КАРТОЙ / СБП!**\n\n"
        f"🧾 **Заказ:** `#{order_id}`\n"
        f"👤 **Клиент:** {call.from_user.first_name} (@{call.from_user.username})\n"
        f"🆔 **ID:** `{call.from_user.id}`\n"
        f"💰 **Сумма:** **{order[4]} ₽**\n"
        f"⏳ **Срок:** **{order[3]} дней**\n\n"
        f"Нажмите кнопку ниже для моментальной выдачи VPN клиенту в 1 клик:"
    )
    for a_id in admins:
        try:
            await bot.send_message(a_id, admin_msg, reply_markup=admin_kb, parse_mode="Markdown")
        except Exception:
            pass

@dp.callback_query(F.data.startswith("adm_appr_"))
async def cb_admin_approve_order(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    order_id = call.data.replace("adm_appr_", "")
    order = get_card_order(order_id)
    if not order or order[6] == "completed":
        return

    complete_card_order(order_id)
    target_user_id = order[1]
    days = order[3]
    new_sub, ref_id = set_sub(target_user_id, days)
    expire_dt = datetime.fromtimestamp(new_sub).strftime("%d.%m.%Y в %H:%M")

    # Reward referrer if exists (+6 hours):
    if ref_id:
        try:
            set_sub(ref_id, 0.25)
            await bot.send_message(ref_id, "🎉 Ваш реферал купил VPN! Вам начислено +6 часов подписки!")
        except Exception:
            pass

    # Instant delivery to user:
    try:
        await bot.send_message(
            target_user_id,
            f"🎉 **ВАША ОПЛАТА ПОДТВЕРЖДЕНА!**\n\n"
            f"✅ Вам начислено **+{days} дней** подписки {BRAND_NAME}!\n"
            f"⏳ Подписка активна до: `{expire_dt}`\n\n"
            f"🔗 **Ваша универсальная ссылка подписки:**\n"
            f"`{MASTER_SUB_URL}`\n\n"
            f"Наслаждайтесь свободным и быстрым интернетом!",
            reply_markup=sub_active_kb(),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Error notifying user: {e}")

    await call.message.edit_text(f"✅ **Заказ #{order_id} успешно подтвержден! VPN автоматически выдан клиенту `{target_user_id}`.**")

@dp.callback_query(F.data.startswith("adm_rej_"))
async def cb_admin_reject_order(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    order_id = call.data.replace("adm_rej_", "")
    order = get_card_order(order_id)
    if order:
        try:
            await bot.send_message(order[1], f"❌ Оплата по заказу #{order_id} не была найдена. Если произошла ошибка, свяжитесь с поддержкой: @{SUPPORT_USERNAME}")
        except Exception:
            pass
    await call.message.edit_text(f"❌ **Заказ #{order_id} отклонен.**")

# --- AFFILIATE & INVITE ---
@dp.callback_query(F.data == "affiliate")
async def cb_affiliate(call: CallbackQuery):
    await call.answer()
    invited, active = get_referral_stats(call.from_user.id)
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{call.from_user.id}"
    text = (
        f"👥 **Партнёрская программа {BRAND_NAME}:**\n\n"
        f"Приглашайте друзей и пользуйтесь быстрым VPN **абсолютно бесплатно**!\n\n"
        f"🎁 **Условия:**\n"
        f"• За каждого приглашенного друга вы получаете **+{FRIEND_BONUS_HOURS} часов бесплатного VPN** к вашей подписке!\n"
        f"• Ваш друг получает скидку **-{FRIEND_DISCOUNT_PERCENT}%** на подписку и бесплатный тест!\n\n"
        f"📊 **Ваша статистика:**\n"
        f"• Всего переходов по вашей ссылке: **{invited}**\n"
        f"• Активных пользователей: **{active}**\n"
        f"• Заработано бонусов: **+{active * FRIEND_BONUS_HOURS} ч.**\n\n"
        f"🔗 **Ваша реферальная ссылка:**\n`{ref_link}`"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Пригласить друга (Поделиться)", url=f"https://t.me/share/url?url={ref_link}&text=Держи%20топовый%20VPN%20без%20блокировок%20со%20скидкой%2015%25!")],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_main")]
    ])
    await call.message.answer(text, reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data == "invite_friend")
async def cb_invite_friend(call: CallbackQuery):
    await call.answer()
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{call.from_user.id}"
    text = (
        f"🎁 **Пригласить друга в {BRAND_NAME}:**\n\n"
        f"Отправьте другу эту ссылку. Как только он перейдет в бота, вы получите **+{FRIEND_BONUS_HOURS} часов VPN в подарок**, а друг получит скидку **-{FRIEND_DISCOUNT_PERCENT}%**!\n\n"
        f"🔗 `{ref_link}`"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Переслать ссылку другу", url=f"https://t.me/share/url?url={ref_link}&text=Держи%20топовый%20VPN%20без%20блокировок%20со%20скидкой%2015%25!")],
        [InlineKeyboardButton(text="◀️ В главное меню", callback_data="back_main")]
    ])
    await call.message.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- PROMOCODE ACTIVATION ---
@dp.callback_query(F.data == "enter_promo")
async def cb_enter_promo(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(Form.waiting_for_promocode)
    text = (
        f"🎟️ **Активация промокода / ключа FunPay:**\n\n"
        f"Отправьте секретный код или промокод ответным сообщением сюда:"
    )
    await call.message.answer(text, reply_markup=back_kb(), parse_mode="Markdown")

@dp.message(Form.waiting_for_promocode)
async def process_promocode(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    await state.clear()

    # Universal 45% discount promo code check:
    if code in [ACTIVE_PROMO_CODE, "PROMO45", "45%"]:
        set_discount_active(message.from_user.id, 1)
        text = (
            f"🎉 **Промокод `{ACTIVE_PROMO_CODE}` успешно активирован!**\n\n"
            f"Вам предоставлена скидка **-45%** на ВСЕ тарифы от 7 дней!\n"
            f"Перейдите в раздел покупки, чтобы выбрать тариф по суперцене:"
        )
        await message.answer(text, reply_markup=buy_tariffs_kb(message.from_user.id), parse_mode="Markdown")
        return

    # Days promo code:
    days, status = redeem_promocode(code, message.from_user.id)
    if status == "ok":
        text = (
            f"🎉 **Код успешно активирован!**\n\n"
            f"Вам начислено **+{days} дней** подписки {BRAND_NAME}!\n\n"
            f"🔗 Ваша ссылка для подключения:\n`{MASTER_SUB_URL}`"
        )
        await message.answer(text, reply_markup=sub_active_kb(), parse_mode="Markdown")
    elif status == "already_used":
        await message.answer("❌ Этот промокод уже был активирован ранее!", reply_markup=main_menu_kb(message.from_user.id))
    else:
        await message.answer("❌ Неверный промокод! Проверьте правильность написания.", reply_markup=main_menu_kb(message.from_user.id))

# --- INSTRUCTIONS ---
@dp.callback_query(F.data == "instructions")
async def cb_instructions(call: CallbackQuery):
    await call.answer()
    text = (
        f"📖 **Инструкция по подключению {BRAND_NAME}:**\n\n"
        f"💻 **Для ПК (Windows / Mac):**\n"
        f"1. Скачайте бесплатную программу **[Happ](https://github.com/happ-proxy/happ)** или **[Hiddify](https://github.com/hiddify/hiddify-next/releases)**.\n"
        f"2. Скопируйте ссылку подписки или скачайте файл конфигурации из раздела «Мои ключи».\n"
        f"3. В программе нажмите **«+» → Импорт из буфера обмена**.\n"
        f"4. Выберите сервер и нажмите большую кнопку **Подключиться**!\n\n"
        f"⚠️ **Если в Happ пишет 'u/a' или значок интернета показывает 'Нет доступа':**\n"
        f"• В Happ зайдите в **Настройки (шестерёнка) → DNS**.\n"
        f"• Переключите DNS на **DoH (Cloudflare 1.1.1.1 или Google)**, так как стандартный UDP DNS блокируется в РФ!\n\n"
        f"📱 **Для Телефона (iPhone / Android):**\n"
        f"1. Установите приложение из App Store / Google Play:\n"
        f"   • **iOS (iPhone):** Happ, Streisand, V2Box, Hiddify\n"
        f"   • **Android:** Happ, v2rayNG, Hiddify\n"
        f"2. Нажмите **«+» → Добавить подписку** и вставьте вашу ссылку.\n"
        f"3. Включите VPN и наслаждайтесь YouTube в 4K и Discord!"
    )
    await call.message.answer(text, reply_markup=back_kb(), parse_mode="Markdown", disable_web_page_preview=True)

# ----------------- ADMIN PANEL -----------------
@dp.callback_query(F.data == "admin_panel")
async def cb_admin_panel(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    await call.message.answer("👑 **Панель Создателя Welwes VPN:**", reply_markup=admin_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_self_sub")
async def cb_admin_self_sub(call: CallbackQuery):
    await call.answer("Вам успешно начислено +100 дней подписки!", show_alert=True)
    if not is_admin(call.from_user.id):
        return
    set_sub(call.from_user.id, 100)
    await cb_my_keys(call)

@dp.callback_query(F.data == "admin_stars_balance")
async def cb_admin_stars_balance(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    total_stars, total_payments = get_total_stars_earned()
    rub_approx = int(total_stars * 1.5)
    text = (
        f"⭐ **Хранилище Звёзд (Telegram Stars):**\n\n"
        f"💰 Заработано ботом: **{total_stars} ⭐**\n"
        f"📊 Всего покупок звёздами: **{total_payments}**\n"
        f"💵 Примерная сумма в рублях: **~{rub_approx} ₽**\n\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📤 **Как вывести заработанные Звёзды в реальные деньги:**\n\n"
        f"1. Откройте **[@BotFather](https://t.me/BotFather)**\n"
        f"2. Отправьте команду: `/mybots`\n"
        f"3. Выберите вашего бота (`@{BOT_USERNAME}`)\n"
        f"4. Нажмите **Bot Settings** → **Payments** → **Stars Balance**\n"
        f"5. Нажмите **Withdraw (Вывод)** на платформу **Fragment** (TON/криптовалюта или на карту)!\n\n"
        f"*(Вывод доступен через 21 день после первой оплаты по правилам Telegram)*"
    )
    await call.message.answer(text, reply_markup=admin_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_get_avatar")
async def cb_admin_get_avatar(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    if os.path.exists(AVATAR_PATH):
        photo = FSInputFile(AVATAR_PATH)
        await call.message.answer_photo(photo, caption="🖼️ **Официальная аватарка Welwes VPN!**\n\nУстановите её в @BotFather через команду `/setuserpic`!")
    else:
        await call.message.answer("Файл аватарки не найден на диске!")

@dp.callback_query(F.data == "admin_stats")
async def cb_admin_stats(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    total, active = get_stats()
    total_stars, _ = get_total_stars_earned()
    text = (
        f"📊 **Статистика {BRAND_NAME}:**\n\n"
        f"👥 Всего пользователей в боте: **{total}**\n"
        f"🟢 Активных подписок сейчас: **{active}**\n"
        f"⭐ Баланс хранилища звёзд: **{total_stars} ⭐**\n"
        f"🖥️ Активных серверов в сети: **2** (🇩🇪 Германия, 🇫🇮 Финляндия)"
    )
    await call.message.answer(text, reply_markup=admin_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_gen_promo")
async def cb_admin_gen_promo(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎟️ Промокод на 1 день", callback_data="gen_p_1")],
        [InlineKeyboardButton(text="🎟️ Промокод на 7 дней", callback_data="gen_p_7")],
        [InlineKeyboardButton(text="🎟️ Промокод на 30 дней (FunPay)", callback_data="gen_p_30")],
        [InlineKeyboardButton(text="🎟️ Промокод на 90 дней", callback_data="gen_p_90")],
        [InlineKeyboardButton(text="◀️ Назад в админку", callback_data="admin_panel")]
    ])
    await call.message.answer("🎟️ **Выберите длительность промокода для генерации:**", reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("gen_p_"))
async def cb_gen_promo_days(call: CallbackQuery):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    days = int(call.data.replace("gen_p_", ""))
    code = f"WELWES-{days}D-" + uuid.uuid4().hex[:6].upper()
    create_promocode(code, days, call.from_user.id)
    text = (
        f"✅ **Промокод успешно создан!**\n\n"
        f"🔑 Код: `{code}`\n"
        f"⏳ Длительность: **{days} дней**\n\n"
        f"Отправьте этот код покупателю на FunPay — он введет его в бота и сразу получит подписку!"
    )
    await call.message.answer(text, reply_markup=admin_kb(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_broadcast_prompt")
async def cb_admin_broadcast_prompt(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    await state.set_state(Form.waiting_for_broadcast)
    await call.message.answer(
        "📢 **Рассылка сообщений:**\n\n"
        "Отправьте сообщение (текст), которое получат ВСЕ пользователи бота:",
        reply_markup=back_kb(),
        parse_mode="Markdown"
    )

@dp.message(Form.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    await state.clear()
    users = get_all_user_ids()
    sent_count = 0
    broadcast_text = f"📢 **Объявление от {BRAND_NAME}:**\n\n{message.text}"

    for uid in users:
        try:
            await bot.send_message(uid, broadcast_text, parse_mode="Markdown")
            sent_count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass

    await message.answer(f"✅ **Рассылка успешно завершена!**\nСообщение доставлено **{sent_count}** пользователям.", reply_markup=admin_kb(), parse_mode="Markdown")

# --- SBP LINK ADMIN CONFIGURATION ---
@dp.callback_query(F.data == "admin_set_sbp")
async def cb_admin_set_sbp(call: CallbackQuery, state: FSMContext):
    await call.answer()
    if not is_admin(call.from_user.id):
        return
    current_link = get_setting("sbp_link", DEFAULT_SBP_LINK)
    await state.set_state(Form.waiting_for_sbp_link)
    text = (
        f"🔗 **Настройка платёжной ссылки СБП:**\n\n"
        f"Текущая ссылка:\n`{current_link}`\n\n"
        f"Отправьте вашу персональную ссылку на оплату СБП (из Т-Банка, Сбера или агрегатора) ответным сообщением сюда:"
    )
    await call.message.answer(text, reply_markup=back_kb(), parse_mode="Markdown")

@dp.message(Form.waiting_for_sbp_link)
async def process_set_sbp_link(message: Message, state: FSMContext):
    await state.clear()
    new_url = message.text.strip()
    if not new_url.startswith("http"):
        await message.answer("❌ Ссылка должна начинаться с http:// или https://!", reply_markup=admin_kb())
        return
    set_setting("sbp_link", new_url)
    await message.answer(f"✅ **Ссылка СБП успешно обновлена!**\n\nТеперь при нажатии «Оплатить» клиенты будут переходить по этой ссылке:\n`{new_url}`", reply_markup=admin_kb(), parse_mode="Markdown")

# --- CANCEL PAYMENT HANDLER ---
@dp.message(F.text == "🔴 Отменить оплату")
async def process_cancel_payment(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Запрос на оплату отменён.", reply_markup=types.ReplyKeyboardRemove())
    await cmd_start(message, state)

# ----------------- MAIN RUNNER -----------------
async def main():
    init_db()
    print("=" * 60)
    print("🚀 Welwes VPN Bot starting...")
    print(f"• Brand: {BRAND_NAME}")
    print(f"• Promo: {ACTIVE_PROMO_CODE} (-{PROMO_DISCOUNT_PERCENT}%)")
    print(f"• Friend Discount: -{FRIEND_DISCOUNT_PERCENT}% / Bonus: +{FRIEND_BONUS_HOURS}h")
    print(f"• Master Sub URL: {MASTER_SUB_URL}")
    print("=" * 60)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
