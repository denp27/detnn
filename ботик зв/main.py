#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram Bot for selling Telegram Stars and Premium
Expanded admin functions, profile-based balance management
"""

import asyncio
import json
import sqlite3
import secrets
import string
import time
import hashlib
import hmac
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List, Any
from contextlib import contextmanager
from enum import Enum

import aiohttp
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    Message, User, InputMediaPhoto, InputMediaVideo,
    InputMediaAudio, InputMediaDocument, WebAppInfo
)
from pyrogram.enums import ParseMode, MessageEntityType, ChatMemberStatus
from pyrogram.errors import UserNotParticipant, FloodWait, PeerIdInvalid

# ================= НАСТРОЙКА ЛОГИРОВАНИЯ =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================= КОНФИГУРАЦИЯ =================

# Telegram Bot
API_ID = 12345
API_HASH = "your_api_hash"
BOT_TOKEN = "7867924002:AAFIsZ0EPEHnId4HC8il4b8IrTW9Ilh3F_E"

# Администраторы
ADMIN_IDS = [8429942952]

# Webhook настройки
WEBHOOK_HOST = "https://your-domain.com"
WEBHOOK_PORT = 3000
WEBHOOK_PATH = "/webhook"

# CryptoBot
CRYPTOBOT_TOKEN = "your_cryptobot_token"
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api"

# Platega.io
PLATEGA_MERCHANT_ID = "your_merchant_id"
PLATEGA_SECRET_KEY = "your_secret_key"
PLATEGA_API_URL = "https://platega.io/api/v1"

# Fragment API
FRAGMENT_SEED = "word1 word2 ... word24"
FRAGMENT_API_KEY = "your_tonapi_key"
FRAGMENT_COOKIES = {
    "stel_ssid": "your_ssid",
    "stel_dt": "your_dt",
    "stel_token": "your_token",
    "stel_ton_token": "your_ton_token",
}

# Премиум эмодзи
PREMIUM_EMOJI_IDS = {
    "star": 5343528654456496221,
    "fire": 5343615236702215768,
    "crown": 5343543193031085986,
    "sparkles": 5343579263228451028,
    "rocket": 5343585422010155027,
    "heart": 5343524811580579204,
}

# Обычные эмодзи
EMOJI = {
    "star": "⭐",
    "gold_star": "🌟",
    "fire": "🔥",
    "crown": "👑",
    "sparkles": "✨",
    "rocket": "🚀",
    "heart": "❤️",
    "diamond": "💎",
    "gift": "🎁",
    "warning": "⚠️",
    "check": "✅",
    "cross": "❌",
    "info": "ℹ️",
    "settings": "⚙️",
    "wallet": "💰",
    "users": "👥",
    "stats": "📊",
    "mail": "📧",
    "code": "🎟️",
    "lock": "🔒",
    "unlock": "🔓",
    "plus": "➕",
    "minus": "➖",
    "edit": "✏️",
    "delete": "🗑️",
    "list": "📋",
    "back": "🔙",
    "forward": "➡️",
    "refresh": "🔄",
}

# Цены
STAR_PRICE_RUB = 10
STARS_PACKS = {50: 500, 100: 1000, 250: 2500, 500: 5000, 1000: 10000}
PREMIUM_PACKS = {3: 750, 6: 1400, 12: 2500}
REFERRAL_BONUS = 10  # Бонус за приглашённого друга


# ================= БАЗА ДАННЫХ =================

def init_database():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()

    # Пользователи (расширенная таблица)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            last_name TEXT,
            balance INTEGER DEFAULT 0,
            premium_until INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0,
            total_earned INTEGER DEFAULT 0,
            join_date INTEGER DEFAULT 0,
            last_active INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT 0,
            referral_count INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            warnings INTEGER DEFAULT 0,
            language TEXT DEFAULT 'ru',
            notification_settings TEXT DEFAULT '{"payments": true, "promos": true}'
        )
    """)

    # Транзакции
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            order_id TEXT UNIQUE,
            amount_rub INTEGER,
            stars_amount INTEGER,
            premium_months INTEGER,
            payment_system TEXT,
            status TEXT DEFAULT 'pending',
            payment_id TEXT,
            created_at INTEGER,
            completed_at INTEGER
        )
    """)

    # Промокоды
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            reward_stars INTEGER,
            reward_premium_days INTEGER,
            reward_balance INTEGER,
            max_uses INTEGER,
            used_count INTEGER DEFAULT 0,
            min_level INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_by INTEGER,
            created_at INTEGER,
            expires_at INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promo_usage (
            user_id INTEGER,
            code TEXT,
            used_at INTEGER,
            PRIMARY KEY (user_id, code)
        )
    """)

    # Задания
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            description TEXT,
            reward_stars INTEGER,
            task_type TEXT,
            target_id TEXT,
            target_url TEXT,
            required_count INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            created_by INTEGER,
            created_at INTEGER,
            order_index INTEGER DEFAULT 0,
            daily_limit INTEGER DEFAULT 0,
            daily_completed INTEGER DEFAULT 0,
            last_reset INTEGER DEFAULT 0
        )
    """)

    # Выполненные задания
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS completed_tasks (
            user_id INTEGER,
            task_id INTEGER,
            completed_at INTEGER,
            completed_count INTEGER DEFAULT 1,
            PRIMARY KEY (user_id, task_id)
        )
    """)

    # Рассылки
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mailings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_text TEXT,
            message_type TEXT,
            media_file_id TEXT,
            buttons_json TEXT,
            target_filter TEXT,
            status TEXT,
            total_users INTEGER,
            sent_count INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at INTEGER
        )
    """)

    # Чёрный список
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            banned_by INTEGER,
            banned_at INTEGER,
            banned_until INTEGER
        )
    """)

    # Статистика ошибок
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            error_type TEXT,
            error_message TEXT,
            user_id INTEGER,
            created_at INTEGER
        )
    """)

    # Ежедневные бонусы
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_bonus (
            user_id INTEGER PRIMARY KEY,
            last_claim INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0
        )
    """)

    # Настройки бота
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at INTEGER
        )
    """)

    # Вставка настроек по умолчанию
    default_settings = [
        ('welcome_message', 'Добро пожаловать в магазин!', 0),
        ('referral_bonus', '10', 0),
        ('daily_bonus_base', '5', 0),
        ('daily_bonus_multiplier', '2', 0),
        ('maintenance_mode', '0', 0),
        ('min_withdraw', '100', 0),
    ]
    cursor.executemany("INSERT OR IGNORE INTO bot_settings (key, value, updated_at) VALUES (?, ?, ?)", default_settings)

    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")


def get_db():
    return sqlite3.connect("bot_database.db")


@contextmanager
def db_transaction():
    conn = get_db()
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_user(user_id: int) -> Dict:
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            cursor.execute(
                "INSERT INTO users (user_id, join_date, last_active) VALUES (?, ?, ?)",
                (user_id, int(time.time()), int(time.time()))
            )
            conn.commit()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            user = cursor.fetchone()
        columns = [desc[0] for desc in cursor.description]
        return dict(zip(columns, user))


def update_user(user_id: int, **kwargs):
    with db_transaction() as conn:
        cursor = conn.cursor()
        for key, value in kwargs.items():
            cursor.execute(f"UPDATE users SET {key} = ? WHERE user_id = ?", (value, user_id))


def add_stars(user_id: int, amount: int, reason: str = ""):
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance + ?, total_earned = total_earned + ? WHERE user_id = ?",
                       (amount, amount, user_id))
        if reason:
            logger.info(f"Added {amount} stars to {user_id}: {reason}")


def remove_stars(user_id: int, amount: int) -> bool:
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
                       (amount, user_id, amount))
        return cursor.rowcount > 0


def set_premium(user_id: int, days: int):
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        current = result[0] if result else 0
        new_until = max(current, int(time.time())) + (days * 86400)
        cursor.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (new_until, user_id))


def is_premium_active(user_id: int) -> bool:
    user = get_user(user_id)
    return user.get('premium_until', 0) > int(time.time())


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_banned(user_id: int) -> bool:
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT banned_until FROM blacklist WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result and result[0] and result[0] > int(time.time()):
            return True
        cursor.execute("SELECT is_banned FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return result and result[0] == 1


def generate_order_id(user_id: int, tx_type: str) -> str:
    return f"{tx_type}_{user_id}_{int(time.time())}_{secrets.token_hex(4)}"


def get_emoji(emoji_name: str) -> str:
    return EMOJI.get(emoji_name, "⭐")


def get_premium_emoji_message(text: str) -> str:
    replacements = {
        "⭐": f'<emoji id={PREMIUM_EMOJI_IDS["star"]}>⭐</emoji>',
        "🔥": f'<emoji id={PREMIUM_EMOJI_IDS["fire"]}>🔥</emoji>',
        "👑": f'<emoji id={PREMIUM_EMOJI_IDS["crown"]}>👑</emoji>',
        "✨": f'<emoji id={PREMIUM_EMOJI_IDS["sparkles"]}>✨</emoji>',
        "🚀": f'<emoji id={PREMIUM_EMOJI_IDS["rocket"]}>🚀</emoji>',
        "❤️": f'<emoji id={PREMIUM_EMOJI_IDS["heart"]}>❤️</emoji>',
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


# ================= FRAGMENT API =================

try:
    from pyfragment import FragmentClient, UserNotFoundError, WalletError

    PYFRAGMENT_AVAILABLE = True
except ImportError:
    PYFRAGMENT_AVAILABLE = False


async def send_stars_via_fragment(username: str, amount: int) -> Tuple[bool, str]:
    if not PYFRAGMENT_AVAILABLE:
        return False, "pyfragment не установлен"
    try:
        async with FragmentClient(
                seed=FRAGMENT_SEED,
                api_key=FRAGMENT_API_KEY,
                cookies=FRAGMENT_COOKIES,
        ) as client:
            result = await client.purchase_stars(username, amount=amount)
            return True, result.transaction_id
    except Exception as e:
        return False, str(e)


async def send_premium_via_fragment(username: str, months: int) -> Tuple[bool, str]:
    if not PYFRAGMENT_AVAILABLE:
        return False, "pyfragment не установлен"
    try:
        async with FragmentClient(
                seed=FRAGMENT_SEED,
                api_key=FRAGMENT_API_KEY,
                cookies=FRAGMENT_COOKIES,
        ) as client:
            result = await client.purchase_premium(username, months=months)
            return True, result.transaction_id
    except Exception as e:
        return False, str(e)


# ================= ПЛАТЕЖНЫЕ СИСТЕМЫ =================

class CryptoBotClient:
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Crypto-Pay-API-Token": token, "Content-Type": "application/json"}

    async def create_invoice(self, amount: float, description: str = "") -> Optional[Dict]:
        async with aiohttp.ClientSession() as session:
            data = {"asset": "RUB", "amount": str(amount), "description": description}
            try:
                async with session.post(f"{CRYPTOBOT_API_URL}/createInvoice", headers=self.headers, json=data) as resp:
                    result = await resp.json()
                    if result.get("ok"):
                        return {"invoice_id": result["result"]["invoice_id"], "pay_url": result["result"]["pay_url"]}
            except Exception as e:
                logger.error(f"CryptoBot error: {e}")
            return None


class PlategaClient:
    def __init__(self, merchant_id: str, secret_key: str):
        self.merchant_id = merchant_id
        self.secret_key = secret_key

    async def create_transaction(self, amount: float, order_id: str, description: str = "") -> Optional[Dict]:
        async with aiohttp.ClientSession() as session:
            timestamp = int(time.time())
            sign_str = f"{self.merchant_id}{order_id}{amount}{timestamp}{self.secret_key}"
            signature = hashlib.md5(sign_str.encode()).hexdigest()

            data = {
                "merchant_id": self.merchant_id,
                "amount": amount,
                "order_id": order_id,
                "description": description,
                "timestamp": timestamp,
                "signature": signature,
                "currency": "RUB",
            }

            try:
                async with session.post(f"{PLATEGA_API_URL}/create", json=data) as resp:
                    result = await resp.json()
                    if result.get("status") == "success":
                        return {"transaction_id": result["transaction_id"], "payment_url": result["payment_url"]}
            except Exception as e:
                logger.error(f"Platega error: {e}")
            return None


cryptobot = CryptoBotClient(CRYPTOBOT_TOKEN)
platega = PlategaClient(PLATEGA_MERCHANT_ID, PLATEGA_SECRET_KEY)


# ================= ПРОВЕРКИ ЗАДАНИЙ =================

async def check_channel_subscription(client: Client, user_id: int, channel_username: str) -> bool:
    try:
        member = await client.get_chat_member(f"@{channel_username}", user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except:
        return False


async def check_group_join(client: Client, user_id: int, group_username: str) -> bool:
    try:
        member = await client.get_chat_member(f"@{group_username}", user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except:
        return False


async def check_bot_start(bot_username: str, user_id: int) -> bool:
    # Требуется deep linking реализация
    return True


# ================= КЛАВИАТУРЫ =================

def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Главное меню - только кабинет"""
    buttons = [
        [InlineKeyboardButton(f"{get_emoji('wallet')} Мой кошелек", callback_data="my_wallet")],
        [InlineKeyboardButton(f"{get_emoji('sparkles')} Магазин", callback_data="shop_menu")],
        [InlineKeyboardButton(f"{get_emoji('rocket')} Задания", callback_data="tasks_menu")],
        [InlineKeyboardButton(f"{get_emoji('gift')} Ежедневный бонус", callback_data="daily_bonus")],
        [InlineKeyboardButton(f"{get_emoji('users')} Реферальная система", callback_data="referral_menu")],
        [InlineKeyboardButton(f"{get_emoji('info')} О боте", callback_data="about_menu")],
    ]
    if is_admin(user_id):
        buttons.append([InlineKeyboardButton(f"{get_emoji('settings')} Админ панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)


def get_wallet_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Клавиатура кошелька"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{get_emoji('plus')} Пополнить баланс", callback_data="deposit_menu")],
        [InlineKeyboardButton(f"{get_emoji('gift')} Активировать промокод", callback_data="activate_promo")],
        [InlineKeyboardButton(f"{get_emoji('crown')} Купить Premium", callback_data="buy_premium_menu")],
        [InlineKeyboardButton(f"{get_emoji('refresh')} История операций", callback_data="transaction_history")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="back_to_main")]
    ])


def get_deposit_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{get_emoji('star')} 50 ⭐ (500 ₽)", callback_data="deposit:50:500")],
        [InlineKeyboardButton(f"{get_emoji('star')} 100 ⭐ (1000 ₽)", callback_data="deposit:100:1000")],
        [InlineKeyboardButton(f"{get_emoji('star')} 250 ⭐ (2500 ₽)", callback_data="deposit:250:2500")],
        [InlineKeyboardButton(f"{get_emoji('star')} 500 ⭐ (5000 ₽)", callback_data="deposit:500:5000")],
        [InlineKeyboardButton(f"{get_emoji('star')} 1000 ⭐ (10000 ₽)", callback_data="deposit:1000:10000")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="my_wallet")]
    ])


def get_payment_method_keyboard(order_id: str, amount: int, product_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 CryptoBot", callback_data=f"pay:cryptobot:{order_id}:{amount}:{product_type}")],
        [InlineKeyboardButton("💳 Platega.io", callback_data=f"pay:platega:{order_id}:{amount}:{product_type}")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="deposit_menu")]
    ])


def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    """Главная админ-панель"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{get_emoji('users')} Управление пользователями", callback_data="admin_users_menu")],
        [InlineKeyboardButton(f"{get_emoji('stats')} Статистика и аналитика", callback_data="admin_stats_menu")],
        [InlineKeyboardButton(f"{get_emoji('mail')} Рассылки", callback_data="admin_mailing_menu")],
        [InlineKeyboardButton(f"{get_emoji('code')} Промокоды", callback_data="admin_promocodes_menu")],
        [InlineKeyboardButton(f"{get_emoji('rocket')} Задания", callback_data="admin_tasks_menu")],
        [InlineKeyboardButton(f"{get_emoji('settings')} Настройки бота", callback_data="admin_settings_menu")],
        [InlineKeyboardButton(f"{get_emoji('diamond')} Финансы", callback_data="admin_finance_menu")],
        [InlineKeyboardButton(f"{get_emoji('lock')} Безопасность", callback_data="admin_security_menu")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="back_to_main")]
    ])


def get_admin_users_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Общая статистика", callback_data="admin_user_stats")],
        [InlineKeyboardButton("🔍 Поиск пользователя", callback_data="admin_search_user")],
        [InlineKeyboardButton("⭐ Выдать звезды", callback_data="admin_give_stars")],
        [InlineKeyboardButton("👑 Выдать Premium", callback_data="admin_give_premium")],
        [InlineKeyboardButton("⚠️ Заблокировать", callback_data="admin_ban_user")],
        [InlineKeyboardButton("✅ Разблокировать", callback_data="admin_unban_user")],
        [InlineKeyboardButton("📈 Топ пользователей", callback_data="admin_top_users")],
        [InlineKeyboardButton("📋 Активные премиум", callback_data="admin_premium_users")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="admin_panel")]
    ])


def get_admin_stats_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 Общая статистика", callback_data="admin_general_stats")],
        [InlineKeyboardButton("💰 Финансовая статистика", callback_data="admin_finance_stats")],
        [InlineKeyboardButton("📈 Графики", callback_data="admin_charts")],
        [InlineKeyboardButton("🎯 Активность заданий", callback_data="admin_tasks_stats")],
        [InlineKeyboardButton("💎 Продажи Premium", callback_data="admin_premium_sales")],
        [InlineKeyboardButton("⚡ Ежедневная активность", callback_data="admin_daily_activity")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="admin_panel")]
    ])


def get_admin_mailing_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Новая рассылка", callback_data="admin_new_mailing")],
        [InlineKeyboardButton("📋 История рассылок", callback_data="admin_mailing_history")],
        [InlineKeyboardButton("⏹️ Остановить рассылку", callback_data="admin_stop_mailing")],
        [InlineKeyboardButton("🎯 Рассылка по фильтрам", callback_data="admin_filtered_mailing")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="admin_panel")]
    ])


def get_admin_promocodes_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Создать промокод", callback_data="admin_create_promo")],
        [InlineKeyboardButton("📋 Список промокодов", callback_data="admin_list_promocodes")],
        [InlineKeyboardButton("🗑️ Удалить промокод", callback_data="admin_delete_promo")],
        [InlineKeyboardButton("📊 Статистика промокодов", callback_data="admin_promo_stats")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="admin_panel")]
    ])


def get_admin_tasks_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Создать задание", callback_data="admin_create_task")],
        [InlineKeyboardButton("📋 Список заданий", callback_data="admin_tasks_list")],
        [InlineKeyboardButton("✏️ Редактировать задание", callback_data="admin_edit_task")],
        [InlineKeyboardButton("🗑️ Удалить задание", callback_data="admin_delete_task")],
        [InlineKeyboardButton("🔄 Сбросить статистику", callback_data="admin_reset_tasks")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="admin_panel")]
    ])


def get_admin_settings_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Приветственное сообщение", callback_data="admin_set_welcome")],
        [InlineKeyboardButton("⭐ Реферальный бонус", callback_data="admin_set_referral")],
        [InlineKeyboardButton("🎁 Ежедневный бонус", callback_data="admin_set_daily")],
        [InlineKeyboardButton("💱 Курс звезд", callback_data="admin_set_star_price")],
        [InlineKeyboardButton("🔧 Режим обслуживания", callback_data="admin_maintenance")],
        [InlineKeyboardButton("📢 Системное сообщение", callback_data="admin_system_msg")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="admin_panel")]
    ])


def get_admin_finance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Баланс бота", callback_data="admin_bot_balance")],
        [InlineKeyboardButton("📊 Вывод средств", callback_data="admin_withdraw_stats")],
        [InlineKeyboardButton("⚙️ Настройки платежей", callback_data="admin_payment_settings")],
        [InlineKeyboardButton("📈 Отчет по транзакциям", callback_data="admin_transaction_report")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="admin_panel")]
    ])


def get_admin_security_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚫 Чёрный список", callback_data="admin_blacklist")],
        [InlineKeyboardButton("⚠️ Жалобы пользователей", callback_data="admin_reports")],
        [InlineKeyboardButton("📜 Логи ошибок", callback_data="admin_error_logs")],
        [InlineKeyboardButton("🔐 Сменить токен бота", callback_data="admin_change_token")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="admin_panel")]
    ])


def get_referral_keyboard(user_id: int, referral_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Пригласить друга", callback_data="invite_friend")],
        [InlineKeyboardButton("👥 Мои рефералы", callback_data="my_referrals")],
        [InlineKeyboardButton("🎁 Бонусы", callback_data="referral_bonuses")],
        [InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="back_to_main")]
    ])


# ================= WEBHOOK СЕРВЕР =================

bot_instance = None


async def process_payment(order_id: str, payment_system: str, payment_id: str):
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE order_id = ?", (order_id,))
        tx = cursor.fetchone()

        if not tx or tx[7] == 'completed':
            return

        user_id = tx[1]
        stars_amount = tx[4]
        premium_months = tx[5]

        try:
            user_info = await bot_instance.get_users(user_id)
            username = user_info.username
            if not username:
                return
        except:
            return

        if stars_amount and stars_amount > 0:
            success, result = await send_stars_via_fragment(f"@{username}", stars_amount)
            if success:
                cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (stars_amount, user_id))
                cursor.execute(
                    "UPDATE transactions SET status = 'completed', payment_id = ?, completed_at = ? WHERE order_id = ?",
                    (payment_id, int(time.time()), order_id))
                await bot_instance.send_message(
                    user_id,
                    get_premium_emoji_message(
                        f"✅ *Оплата подтверждена!*\n\n"
                        f"{get_emoji('star')} {stars_amount} Telegram Stars отправлено!\n"
                        f"Transaction ID: `{result}`"
                    ),
                    parse_mode=ParseMode.HTML
                )
        elif premium_months and premium_months > 0:
            success, result = await send_premium_via_fragment(f"@{username}", premium_months)
            if success:
                cursor.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
                current = cursor.fetchone()[0] or 0
                new_until = max(current, int(time.time())) + (premium_months * 30 * 86400)
                cursor.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (new_until, user_id))
                cursor.execute(
                    "UPDATE transactions SET status = 'completed', payment_id = ?, completed_at = ? WHERE order_id = ?",
                    (payment_id, int(time.time()), order_id))
                await bot_instance.send_message(
                    user_id,
                    get_premium_emoji_message(
                        f"✅ *Оплата подтверждена!*\n\n"
                        f"{get_emoji('crown')} Premium на {premium_months} месяцев активирован!"
                    ),
                    parse_mode=ParseMode.HTML
                )


async def cryptobot_webhook(request):
    try:
        data = await request.json()
        if data.get("update_type") == "invoice_paid":
            payload = data.get("payload", {})
            order_id = payload.get("description", "")
            invoice_id = str(payload.get("invoice_id", ""))
            if order_id and invoice_id:
                await process_payment(order_id, "cryptobot", invoice_id)
        return web.json_response({"ok": True})
    except Exception as e:
        logger.error(f"CryptoBot webhook error: {e}")
        return web.json_response({"error": str(e)}, status=500)


async def platega_webhook(request):
    try:
        data = await request.json()
        if data.get("event") == "transaction.completed":
            order_id = data.get("order_id", "")
            transaction_id = data.get("transaction_id", "")
            if order_id and transaction_id:
                await process_payment(order_id, "platega", transaction_id)
        return web.json_response({"ok": True})
    except Exception as e:
        logger.error(f"Platega webhook error: {e}")
        return web.json_response({"error": str(e)}, status=500)


web_app = web.Application()
web_app.router.add_post("/webhook/cryptobot", cryptobot_webhook)
web_app.router.add_post("/webhook/platega", platega_webhook)


async def run_webhook():
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()
    logger.info(f"Webhook server started on port {WEBHOOK_PORT}")


# ================= ОСНОВНОЙ БОТ =================

app = Client("stars_premium_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
waiting_for = {}


# ===== КОМАНДЫ =====

@app.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id

    if is_banned(user_id):
        await message.reply("🚫 Вы заблокированы!")
        return

    user = get_user(user_id)
    update_user(user_id,
                username=message.from_user.username or "",
                first_name=message.from_user.first_name or "",
                last_active=int(time.time()))

    # Обработка реферальной ссылки
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        referrer_id = int(args[1].replace("ref_", ""))
        if referrer_id != user_id and not user.get('referrer_id'):
            update_user(user_id, referrer_id=referrer_id)
            add_stars(referrer_id, REFERRAL_BONUS, f"Реферал {user_id}")
            update_user(referrer_id, referral_count=user.get('referral_count', 0) + 1)

    welcome_text = f"""
{get_emoji('star')}{get_emoji('crown')} *Добро пожаловать в магазин Stars & Premium!* {get_emoji('crown')}{get_emoji('star')}

{get_emoji('wallet')} *Ваш баланс:* {user['balance']} ⭐

{get_emoji('info')} Для пополнения баланса и активации промокодов используйте кнопки ниже.

💎 *Преимущества:*
• Мгновенная выдача товара
• Поддержка 24/7
• Реферальная программа
• Ежедневные бонусы
"""

    await message.reply_text(
        get_premium_emoji_message(welcome_text),
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.HTML
    )


@app.on_message(filters.command("admin") & filters.private)
async def admin_command(client: Client, message: Message):
    if is_admin(message.from_user.id):
        await message.reply_text(
            get_premium_emoji_message(f"{get_emoji('settings')} *Админ панель* {get_emoji('settings')}"),
            reply_markup=get_admin_main_keyboard(),
            parse_mode=ParseMode.HTML
        )
    else:
        await message.reply_text("⛔ Доступ запрещён!")


# ===== CALLBACK ОБРАБОТЧИКИ =====

@app.on_callback_query()
async def handle_callback(client: Client, callback: CallbackQuery):
    user_id = callback.from_user.id
    data = callback.data

    if is_banned(user_id):
        await callback.answer("🚫 Вы заблокированы!", show_alert=True)
        return

    # === НАВИГАЦИЯ ===

    if data == "back_to_main":
        user = get_user(user_id)
        await callback.message.edit_text(
            get_premium_emoji_message(
                f"{get_emoji('star')} *Главное меню* {get_emoji('star')}\n\n"
                f"{get_emoji('wallet')} Баланс: {user['balance']} ⭐"
            ),
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data == "admin_panel" and is_admin(user_id):
        await callback.message.edit_text(
            get_premium_emoji_message(f"{get_emoji('settings')} *Панель администратора* {get_emoji('settings')}"),
            reply_markup=get_admin_main_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === МОЙ КОШЕЛЕК ===

    if data == "my_wallet":
        user = get_user(user_id)
        premium_status = "✅" if is_premium_active(user_id) else "❌"
        text = f"""
{get_emoji('wallet')} *МОЙ КОШЕЛЕК* {get_emoji('wallet')}

{get_emoji('star')} *Баланс:* {user['balance']} ⭐
{get_emoji('crown')} *Premium:* {premium_status}
{get_emoji('diamond')} *Всего потрачено:* {user['total_spent']} ₽
{get_emoji('gift')} *Заработано:* {user['total_earned']} ⭐
{get_emoji('users')} *Приглашено:* {user['referral_count']}

💡 *Как пополнить:*
Выберите сумму и способ оплаты. Товар придёт автоматически.
"""
        await callback.message.edit_text(
            get_premium_emoji_message(text),
            reply_markup=get_wallet_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === ПОПОЛНЕНИЕ БАЛАНСА ===

    if data == "deposit_menu":
        await callback.message.edit_text(
            get_premium_emoji_message(
                f"{get_emoji('plus')} *Пополнение баланса* {get_emoji('plus')}\n\n"
                f"Выберите количество звезд:"
            ),
            reply_markup=get_deposit_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data.startswith("deposit:"):
        _, stars, price = data.split(":")
        stars, price = int(stars), int(price)
        order_id = generate_order_id(user_id, "stars")

        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO transactions (user_id, order_id, amount_rub, stars_amount, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, order_id, price, stars, "pending", int(time.time()))
            )

        await callback.message.edit_text(
            get_premium_emoji_message(
                f"{get_emoji('star')} *{stars} звезд*\n"
                f"Сумма: {price} ₽\n\n"
                f"Выберите способ оплаты:"
            ),
            reply_markup=get_payment_method_keyboard(order_id, price, "stars"),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === ОПЛАТА ===

    if data.startswith("pay:"):
        _, payment_system, order_id, amount, product_type = data.split(":")
        amount = int(amount)

        await callback.message.edit_text(
            get_premium_emoji_message(f"{get_emoji('rocket')} *Создание платежа...*"),
            parse_mode=ParseMode.HTML
        )

        if payment_system == "cryptobot":
            invoice = await cryptobot.create_invoice(amount, order_id)
            if invoice:
                await callback.message.edit_text(
                    get_premium_emoji_message(
                        f"💳 *Оплата через CryptoBot*\n\n"
                        f"Сумма: {amount} ₽\n\n"
                        f"🔗 [Нажмите для оплаты]({invoice['pay_url']})\n\n"
                        f"{get_emoji('info')} После оплаты товар придет автоматически."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 Оплатить", url=invoice['pay_url'])],
                        [InlineKeyboardButton("🔙 Назад", callback_data="deposit_menu")]
                    ]),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            else:
                await callback.message.edit_text("❌ Ошибка создания платежа", reply_markup=get_deposit_keyboard())

        elif payment_system == "platega":
            invoice = await platega.create_transaction(amount, order_id, f"Покупка {product_type}")
            if invoice:
                await callback.message.edit_text(
                    get_premium_emoji_message(
                        f"💳 *Оплата через Platega.io*\n\n"
                        f"Сумма: {amount} ₽\n\n"
                        f"🔗 [Нажмите для оплаты]({invoice['payment_url']})\n\n"
                        f"{get_emoji('info')} После оплаты товар придет автоматически."
                    ),
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔗 Оплатить", url=invoice['payment_url'])],
                        [InlineKeyboardButton("🔙 Назад", callback_data="deposit_menu")]
                    ]),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True
                )
            else:
                await callback.message.edit_text("❌ Ошибка создания платежа", reply_markup=get_deposit_keyboard())

        await callback.answer()
        return

    # === ПОКУПКА PREMIUM ===

    if data == "buy_premium_menu":
        await callback.message.edit_text(
            get_premium_emoji_message(
                f"{get_emoji('crown')} *Premium подписка* {get_emoji('crown')}\n\n"
                f"Преимущества Premium:\n"
                f"• {get_emoji('sparkles')} Эксклюзивные эмодзи\n"
                f"• {get_emoji('rocket')} Приоритетная поддержка\n"
                f"• {get_emoji('gift')} Ежемесячные бонусы\n\n"
                f"Оплата звездами с баланса:"
            ),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("3 мес. (750 ⭐)", callback_data="buy_premium:3:750")],
                [InlineKeyboardButton("6 мес. (1400 ⭐)", callback_data="buy_premium:6:1400")],
                [InlineKeyboardButton("12 мес. (2500 ⭐)", callback_data="buy_premium:12:2500")],
                [InlineKeyboardButton("🔙 Назад", callback_data="my_wallet")]
            ]),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data.startswith("buy_premium:"):
        _, months, stars_price = data.split(":")
        months, stars_price = int(months), int(stars_price)

        user = get_user(user_id)
        if user['balance'] < stars_price:
            await callback.answer(f"❌ Недостаточно звезд! Нужно: {stars_price}", show_alert=True)
            return

        username = callback.from_user.username
        if not username:
            await callback.answer("❌ Установите username в Telegram!", show_alert=True)
            return

        await callback.message.edit_text(
            get_premium_emoji_message(f"{get_emoji('rocket')} *Оформление Premium...*"),
            parse_mode=ParseMode.HTML
        )

        success, result = await send_premium_via_fragment(f"@{username}", months)

        if success:
            remove_stars(user_id, stars_price)
            set_premium(user_id, months * 30)

            await callback.message.edit_text(
                get_premium_emoji_message(
                    f"✅ *Premium на {months} месяцев успешно оформлен!*\n\n"
                    f"{get_emoji('star')} Списано: {stars_price} ⭐\n"
                    f"{get_emoji('fire')} Premium активирован!"
                ),
                reply_markup=get_main_keyboard(user_id),
                parse_mode=ParseMode.HTML
            )
        else:
            await callback.message.edit_text(
                get_premium_emoji_message(f"❌ *Ошибка:* {result}"),
                reply_markup=get_main_keyboard(user_id),
                parse_mode=ParseMode.HTML
            )
        await callback.answer()
        return

    # === АКТИВАЦИЯ ПРОМОКОДА ===

    if data == "activate_promo":
        waiting_for[user_id] = "promo"
        await callback.message.edit_text(
            get_premium_emoji_message(
                f"{get_emoji('gift')} *Активация промокода* {get_emoji('gift')}\n\n"
                f"Введите промокод текстовым сообщением:"
            ),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === ЕЖЕДНЕВНЫЙ БОНУС ===

    if data == "daily_bonus":
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT last_claim, streak FROM daily_bonus WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()

            last_claim = result[0] if result else 0
            streak = result[1] if result else 0

            # Проверка возможности получения бонуса
            today_start = int(time.time()) // 86400
            last_claim_start = last_claim // 86400

            if last_claim_start == today_start:
                remaining = 86400 - (int(time.time()) - last_claim)
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                await callback.answer(f"Бонус будет доступен через {hours}ч {minutes}мин", show_alert=True)
                return

            # Расчёт бонуса
            if last_claim_start == today_start - 1:
                streak = min(streak + 1, 30)
            else:
                streak = 1

            base_bonus = 5
            multiplier = min(2 + (streak // 7), 5)
            bonus = base_bonus * multiplier

            add_stars(user_id, bonus, f"Ежедневный бонус: день {streak}")

            cursor.execute("""
                INSERT OR REPLACE INTO daily_bonus (user_id, last_claim, streak)
                VALUES (?, ?, ?)
            """, (user_id, int(time.time()), streak))

        await callback.message.edit_text(
            get_premium_emoji_message(
                f"{get_emoji('gift')} *ЕЖЕДНЕВНЫЙ БОНУС* {get_emoji('gift')}\n\n"
                f"{get_emoji('star')} Вы получили +{bonus} звезд!\n"
                f"{get_emoji('fire')} День: {streak} 🔥\n"
                f"{get_emoji('rocket')} Множитель: x{multiplier}\n\n"
                f"Возвращайтесь завтра за следующим бонусом!"
            ),
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === РЕФЕРАЛЬНАЯ СИСТЕМА ===

    if data == "referral_menu":
        user = get_user(user_id)
        bot_username = (await client.get_me()).username
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

        await callback.message.edit_text(
            get_premium_emoji_message(
                f"{get_emoji('users')} *РЕФЕРАЛЬНАЯ ПРОГРАММА* {get_emoji('users')}\n\n"
                f"{get_emoji('star')} За каждого приглашенного: +{REFERRAL_BONUS} ⭐\n"
                f"{get_emoji('diamond')} Ваших рефералов: {user['referral_count']}\n"
                f"{get_emoji('gift')} Заработано: {user['referral_count'] * REFERRAL_BONUS} ⭐\n\n"
                f"🔗 *Ваша реферальная ссылка:*\n"
                f"`{ref_link}`\n\n"
                f"{get_emoji('info')} Поделитесь ссылкой с друзьями!"
            ),
            reply_markup=get_referral_keyboard(user_id, str(user_id)),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === ИСТОРИЯ ТРАНЗАКЦИЙ ===

    if data == "transaction_history":
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT created_at, stars_amount, premium_months, amount_rub, status 
                FROM transactions 
                WHERE user_id = ? AND status = 'completed'
                ORDER BY created_at DESC LIMIT 10
            """, (user_id,))
            txs = cursor.fetchall()

        if not txs:
            text = f"{get_emoji('info')} У вас пока нет операций"
        else:
            text = f"{get_emoji('list')} *Последние операции:*\n\n"
            for tx in txs:
                date = datetime.fromtimestamp(tx[0]).strftime("%d.%m.%Y %H:%M")
                if tx[1]:
                    text += f"⭐ +{tx[1]} звезд | {date}\n"
                elif tx[2]:
                    text += f"👑 Premium {tx[2]} мес. | {date}\n"
                elif tx[3]:
                    text += f"💰 Пополнение {tx[3]} ₽ | {date}\n"

        await callback.message.edit_text(
            get_premium_emoji_message(text),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="my_wallet")]]),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === О БОТЕ ===

    if data == "about_menu":
        await callback.message.edit_text(
            get_premium_emoji_message(
                f"{get_emoji('info')} *О НАС* {get_emoji('info')}\n\n"
                f"⭐ *Stars & Premium Shop*\n\n"
                f"Мы предлагаем:\n"
                f"• Telegram Stars по лучшим ценам\n"
                f"• Premium подписки\n"
                f"• Мгновенная выдача через Fragment\n"
                f"• Поддержка 24/7\n\n"
                f"💎 *Контакты:* @support\n"
                f"📢 *Канал:* @news_channel"
            ),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]]),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === АДМИН: УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ===

    if data == "admin_users_menu" and is_admin(user_id):
        await callback.message.edit_text(
            f"{get_emoji('users')} *Управление пользователями* {get_emoji('users')}",
            reply_markup=get_admin_users_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data == "admin_user_stats" and is_admin(user_id):
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE premium_until > ?", (int(time.time()),))
            premium = cursor.fetchone()[0]
            cursor.execute("SELECT SUM(balance) FROM users")
            total_balance = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM users WHERE join_date > ?", (int(time.time()) - 86400,))
            new_today = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM users WHERE last_active > ?", (int(time.time()) - 86400,))
            active_today = cursor.fetchone()[0]

        text = f"""
📊 *СТАТИСТИКА ПОЛЬЗОВАТЕЛЕЙ*

👥 Всего: {total}
💎 Premium: {premium}
⭐ Баланс: {total_balance}
📈 Новых за 24ч: {new_today}
✅ Активных за 24ч: {active_today}
"""
        await callback.message.edit_text(text, reply_markup=get_admin_users_keyboard(), parse_mode=ParseMode.MARKDOWN)
        await callback.answer()
        return

    if data == "admin_give_stars" and is_admin(user_id):
        waiting_for[user_id] = "give_stars"
        await callback.message.edit_text(
            "⭐ *Выдача звезд*\n\nВведите команду:\n`/give_stars @username количество`\n\nПример: `/give_stars @durov 100`",
            parse_mode=ParseMode.MARKDOWN
        )
        await callback.answer()
        return

    if data == "admin_give_premium" and is_admin(user_id):
        waiting_for[user_id] = "give_premium"
        await callback.message.edit_text(
            "👑 *Выдача Premium*\n\nВведите команду:\n`/give_premium @username месяцы`\n\nПример: `/give_premium @durov 3`",
            parse_mode=ParseMode.MARKDOWN
        )
        await callback.answer()
        return

    # === АДМИН: СТАТИСТИКА ===

    if data == "admin_stats_menu" and is_admin(user_id):
        await callback.message.edit_text(
            f"{get_emoji('stats')} *Статистика и аналитика* {get_emoji('stats')}",
            reply_markup=get_admin_stats_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data == "admin_general_stats" and is_admin(user_id):
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            total_users = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM tasks WHERE is_active = 1")
            active_tasks = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM completed_tasks")
            total_completions = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM promocodes WHERE is_active = 1")
            active_promos = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM blacklist")
            banned = cursor.fetchone()[0]

        text = f"""
📈 *ОБЩАЯ СТАТИСТИКА*

👥 Пользователей: {total_users}
📝 Активных заданий: {active_tasks}
✅ Выполнено заданий: {total_completions}
🎟 Активных промокодов: {active_promos}
🚫 Заблокировано: {banned}
"""
        await callback.message.edit_text(text, reply_markup=get_admin_stats_keyboard(), parse_mode=ParseMode.MARKDOWN)
        await callback.answer()
        return

    if data == "admin_finance_stats" and is_admin(user_id):
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(amount_rub) FROM transactions WHERE status = 'completed'")
            total_income = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(amount_rub) FROM transactions WHERE status = 'completed' AND completed_at > ?",
                           (int(time.time()) - 30 * 86400,))
            month_income = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(stars_amount) FROM transactions WHERE status = 'completed'")
            total_stars_sold = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM transactions WHERE premium_months > 0 AND status = 'completed'")
            premium_sales = cursor.fetchone()[0] or 0

        text = f"""
💰 *ФИНАНСОВАЯ СТАТИСТИКА*

💵 Общий доход: {total_income} ₽
📆 Доход за месяц: {month_income} ₽
⭐ Продано звезд: {total_stars_sold}
👑 Продано Premium: {premium_sales}
"""
        await callback.message.edit_text(text, reply_markup=get_admin_stats_keyboard(), parse_mode=ParseMode.MARKDOWN)
        await callback.answer()
        return

    # === АДМИН: РАССЫЛКИ ===

    if data == "admin_mailing_menu" and is_admin(user_id):
        await callback.message.edit_text(
            f"{get_emoji('mail')} *Панель рассылок* {get_emoji('mail')}",
            reply_markup=get_admin_mailing_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data == "admin_new_mailing" and is_admin(user_id):
        waiting_for[user_id] = "mailing"
        await callback.message.edit_text(
            get_premium_emoji_message(
                f"{get_emoji('rocket')} *СОЗДАНИЕ РАССЫЛКИ* {get_emoji('rocket')}\n\n"
                f"Отправьте сообщение для рассылки.\n\n"
                f"{get_emoji('info')} Поддерживается:\n"
                f"• Текст с {get_emoji('fire')} премиум-эмодзи\n"
                f"• Фото, видео, документы\n"
                f"• Инлайн-кнопки (если прикрепить)\n\n"
                f"Отправьте сообщение сейчас:"
            ),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === АДМИН: ПРОМОКОДЫ ===

    if data == "admin_promocodes_menu" and is_admin(user_id):
        await callback.message.edit_text(
            f"{get_emoji('code')} *Управление промокодами* {get_emoji('code')}",
            reply_markup=get_admin_promocodes_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data == "admin_list_promocodes" and is_admin(user_id):
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT code, reward_stars, reward_premium_days, max_uses, used_count, is_active FROM promocodes ORDER BY created_at DESC LIMIT 20")
            promos = cursor.fetchall()

        if not promos:
            text = "📋 Промокодов нет"
        else:
            text = "📋 *СПИСОК ПРОМОКОДОВ*\n\n"
            for promo in promos:
                code, stars, days, max_uses, used, active = promo
                status = "✅" if active else "❌"
                reward = f"{stars}⭐" if stars else f"{days}дн."
                text += f"{status} `{code}` | {reward} | {used}/{max_uses}\n"

        await callback.message.edit_text(text, reply_markup=get_admin_promocodes_keyboard(),
                                         parse_mode=ParseMode.MARKDOWN)
        await callback.answer()
        return

    if data == "admin_create_promo" and is_admin(user_id):
        waiting_for[user_id] = "create_promo"
        await callback.message.edit_text(
            "🎟 *Создание промокода*\n\nФормат:\n`/create_promo stars 100 50` - 100 звезд\n`/create_promo premium 30 10` - 30 дней\n`/create_promo balance 500 20` - 500 звезд на баланс",
            parse_mode=ParseMode.MARKDOWN
        )
        await callback.answer()
        return

    # === АДМИН: ЗАДАНИЯ ===

    if data == "admin_tasks_menu" and is_admin(user_id):
        await callback.message.edit_text(
            f"{get_emoji('rocket')} *Управление заданиями* {get_emoji('rocket')}",
            reply_markup=get_admin_tasks_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data == "admin_tasks_list" and is_admin(user_id):
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, reward_stars, task_type, is_active FROM tasks ORDER BY order_index")
            tasks = cursor.fetchall()

        if tasks:
            text = "📋 *СПИСОК ЗАДАНИЙ*\n\n"
            for t in tasks:
                status = "✅" if t[4] else "❌"
                text += f"{status} ID `{t[0]}` | {t[1]} | +{t[2]}⭐\n"
            text += "\nДля удаления: `/del_task ID`"
        else:
            text = "📋 Заданий нет"

        await callback.message.edit_text(text, reply_markup=get_admin_tasks_keyboard(), parse_mode=ParseMode.MARKDOWN)
        await callback.answer()
        return

    if data == "admin_create_task" and is_admin(user_id):
        waiting_for[user_id] = "create_task"
        await callback.message.edit_text(
            "📝 *Создание задания*\n\nФормат:\n`/add_task Название | Описание | награда | канал`\n\nПример: `/add_task Подписка | Подпишись на новости | 50 | my_channel`",
            parse_mode=ParseMode.MARKDOWN
        )
        await callback.answer()
        return

    # === АДМИН: НАСТРОЙКИ ===

    if data == "admin_settings_menu" and is_admin(user_id):
        await callback.message.edit_text(
            f"{get_emoji('settings')} *Настройки бота* {get_emoji('settings')}",
            reply_markup=get_admin_settings_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === АДМИН: ФИНАНСЫ ===

    if data == "admin_finance_menu" and is_admin(user_id):
        await callback.message.edit_text(
            f"{get_emoji('diamond')} *Финансовое управление* {get_emoji('diamond')}",
            reply_markup=get_admin_finance_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    # === АДМИН: БЕЗОПАСНОСТЬ ===

    if data == "admin_security_menu" and is_admin(user_id):
        await callback.message.edit_text(
            f"{get_emoji('lock')} *Безопасность* {get_emoji('lock')}",
            reply_markup=get_admin_security_keyboard(),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data == "admin_blacklist" and is_admin(user_id):
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id, reason, banned_at FROM blacklist ORDER BY banned_at DESC LIMIT 20")
            banned = cursor.fetchall()

        if banned:
            text = "🚫 *ЧЁРНЫЙ СПИСОК*\n\n"
            for b in banned:
                uid, reason, date = b
                text += f"• `{uid}` | {reason[:30]}\n"
        else:
            text = "🚫 Чёрный список пуст"

        await callback.message.edit_text(text, reply_markup=get_admin_security_keyboard(),
                                         parse_mode=ParseMode.MARKDOWN)
        await callback.answer()
        return

    # === ЗАДАНИЯ (ПОЛЬЗОВАТЕЛЬСКИЕ) ===

    if data == "tasks_menu":
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, description, reward_stars, task_type, target_id FROM tasks WHERE is_active = 1 ORDER BY order_index")
            tasks = cursor.fetchall()

        if not tasks:
            await callback.message.edit_text(
                get_premium_emoji_message(f"{get_emoji('info')} *Нет доступных заданий*"),
                reply_markup=get_main_keyboard(user_id),
                parse_mode=ParseMode.HTML
            )
            await callback.answer()
            return

        buttons = []
        for task in tasks:
            task_id, title, desc, reward, task_type, target = task
            with db_transaction() as conn:
                cursor2 = conn.cursor()
                cursor2.execute("SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ?", (user_id, task_id))
                completed = cursor2.fetchone()

            status = "✅" if completed else "📌"
            buttons.append(
                [InlineKeyboardButton(f"{status} {title} (+{reward}⭐)", callback_data=f"view_task:{task_id}")])

        buttons.append([InlineKeyboardButton(f"{get_emoji('back')} Назад", callback_data="back_to_main")])

        await callback.message.edit_text(
            get_premium_emoji_message(
                f"{get_emoji('rocket')} *ДОСТУПНЫЕ ЗАДАНИЯ* {get_emoji('rocket')}\n\n"
                f"✅ - выполнено | 📌 - доступно\n"
                f"Выполняйте и получайте звезды!"
            ),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data.startswith("view_task:"):
        task_id = int(data.split(":")[1])

        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, title, description, reward_stars, task_type, target_id, target_url FROM tasks WHERE id = ? AND is_active = 1",
                (task_id,))
            task = cursor.fetchone()

        if not task:
            await callback.answer("Задание не найдено")
            return

        task_id, title, desc, reward, task_type, target_id, target_url = task

        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ?", (user_id, task_id))
            if cursor.fetchone():
                await callback.answer("✅ Вы уже выполнили это задание!", show_alert=True)
                return

        text = f"""
📋 *{title}*

{desc}

{get_emoji('star')} *Награда:* {reward} ⭐
{get_emoji('info')} *Тип:* {TASK_TYPES.get(task_type, {}).get('name', 'Задание')}

*Как выполнить:*
• Подпишитесь на @{target_id}
• Нажмите кнопку проверки
"""

        await callback.message.edit_text(
            get_premium_emoji_message(text),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Подписаться", url=f"https://t.me/{target_id}")],
                [InlineKeyboardButton("✅ Проверить", callback_data=f"check_task:{task_id}")],
                [InlineKeyboardButton("🔙 Назад", callback_data="tasks_menu")]
            ]),
            parse_mode=ParseMode.HTML
        )
        await callback.answer()
        return

    if data.startswith("check_task:"):
        task_id = int(data.split(":")[1])

        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT target_id, reward_stars FROM tasks WHERE id = ?", (task_id,))
            task = cursor.fetchone()

        if not task:
            await callback.answer("Задание не найдено")
            return

        target_id, reward = task

        # Проверка подписки
        try:
            member = await client.get_chat_member(f"@{target_id}", user_id)
            if member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
                with db_transaction() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ?",
                                   (user_id, task_id))
                    if not cursor.fetchone():
                        add_stars(user_id, reward, f"Задание {task_id}")
                        cursor.execute("INSERT INTO completed_tasks (user_id, task_id, completed_at) VALUES (?, ?, ?)",
                                       (user_id, task_id, int(time.time())))

                        await callback.message.edit_text(
                            get_premium_emoji_message(
                                f"✅ *Задание выполнено!*\n\n{get_emoji('star')} Вы получили {reward} звезд!"
                            ),
                            reply_markup=get_main_keyboard(user_id),
                            parse_mode=ParseMode.HTML
                        )
                    else:
                        await callback.message.edit_text(
                            get_premium_emoji_message("✅ Вы уже получали награду!"),
                            reply_markup=get_main_keyboard(user_id),
                            parse_mode=ParseMode.HTML
                        )
            else:
                await callback.answer("❌ Вы не подписаны на канал!", show_alert=True)
        except UserNotParticipant:
            await callback.answer("❌ Вы не подписаны на канал!", show_alert=True)
        except Exception as e:
            await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

        await callback.answer()
        return


# ===== ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ =====

@app.on_message(filters.text & filters.private)
async def handle_text(client: Client, message: Message):
    user_id = message.from_user.id
    text = message.text.strip()

    if is_banned(user_id):
        await message.reply("🚫 Вы заблокированы!")
        return

    # Промокод
    if waiting_for.get(user_id) == "promo":
        code = text.upper()

        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT reward_stars, reward_premium_days, reward_balance, max_uses, used_count, is_active, expires_at FROM promocodes WHERE code = ?",
                (code,))
            promo = cursor.fetchone()

        if not promo:
            await message.reply(get_premium_emoji_message(f"{get_emoji('cross')} *Промокод не найден!*"),
                                parse_mode=ParseMode.HTML)
        else:
            reward_stars, reward_days, reward_balance, max_uses, used_count, is_active, expires_at = promo

            if not is_active or used_count >= max_uses:
                await message.reply(
                    get_premium_emoji_message(f"{get_emoji('cross')} *Промокод неактивен или использован!*"),
                    parse_mode=ParseMode.HTML)
            elif expires_at and expires_at < int(time.time()):
                await message.reply(get_premium_emoji_message(f"{get_emoji('cross')} *Срок действия истек!*"),
                                    parse_mode=ParseMode.HTML)
            else:
                with db_transaction() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT 1 FROM promo_usage WHERE user_id = ? AND code = ?", (user_id, code))
                    if cursor.fetchone():
                        await message.reply(
                            get_premium_emoji_message(f"{get_emoji('cross')} *Вы уже активировали этот промокод!*"),
                            parse_mode=ParseMode.HTML)
                    else:
                        if reward_stars > 0:
                            add_stars(user_id, reward_stars, f"Промокод {code}")
                            await message.reply(get_premium_emoji_message(
                                f"{get_emoji('check')} *Промокод активирован!* +{reward_stars} ⭐"),
                                                parse_mode=ParseMode.HTML)
                        if reward_days > 0:
                            set_premium(user_id, reward_days)
                            await message.reply(get_premium_emoji_message(
                                f"{get_emoji('check')} *Промокод активирован!* +{reward_days} дней Premium"),
                                                parse_mode=ParseMode.HTML)
                        if reward_balance > 0:
                            add_stars(user_id, reward_balance, f"Промокод {code}")
                            await message.reply(get_premium_emoji_message(
                                f"{get_emoji('check')} *Промокод активирован!* +{reward_balance} ⭐"),
                                                parse_mode=ParseMode.HTML)

                        cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
                        cursor.execute("INSERT INTO promo_usage (user_id, code, used_at) VALUES (?, ?, ?)",
                                       (user_id, code, int(time.time())))

        waiting_for[user_id] = None
        return

    # Рассылка (админ)
    if waiting_for.get(user_id) == "mailing" and is_admin(user_id):
        await message.reply(get_premium_emoji_message(f"{get_emoji('rocket')} *Начинаю рассылку...*"),
                            parse_mode=ParseMode.HTML)

        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()

        success = 0
        fail = 0

        for (uid,) in users:
            try:
                await message.copy(uid)
                success += 1
            except FloodWait as e:
                await asyncio.sleep(e.value)
                try:
                    await message.copy(uid)
                    success += 1
                except:
                    fail += 1
            except:
                fail += 1
            await asyncio.sleep(0.05)

        await message.reply(
            get_premium_emoji_message(
                f"{get_emoji('check')} *РАССЫЛКА ЗАВЕРШЕНА* {get_emoji('check')}\n\n"
                f"✅ Успешно: {success}\n"
                f"❌ Ошибок: {fail}"
            ),
            parse_mode=ParseMode.HTML
        )
        waiting_for[user_id] = None
        return

    # Админ команды
    if is_admin(user_id):
        if text.startswith("/give_stars"):
            parts = text.split()
            if len(parts) == 3:
                username = parts[1].lstrip('@')
                amount = int(parts[2])
                success, result = await send_stars_via_fragment(f"@{username}", amount)
                if success:
                    await message.reply(
                        get_premium_emoji_message(f"✅ *{amount} звезд отправлено* @{username}\nTX: `{result}`"),
                        parse_mode=ParseMode.HTML)
                else:
                    await message.reply(get_premium_emoji_message(f"❌ *Ошибка:* {result}"), parse_mode=ParseMode.HTML)
            else:
                await message.reply("Использование: `/give_stars @username количество`", parse_mode=ParseMode.MARKDOWN)
            waiting_for[user_id] = None
            return

        if text.startswith("/give_premium"):
            parts = text.split()
            if len(parts) == 3:
                username = parts[1].lstrip('@')
                months = int(parts[2])
                success, result = await send_premium_via_fragment(f"@{username}", months)
                if success:
                    await message.reply(get_premium_emoji_message(
                        f"✅ *Premium на {months} месяцев отправлен* @{username}\nTX: `{result}`"),
                                        parse_mode=ParseMode.HTML)
                else:
                    await message.reply(get_premium_emoji_message(f"❌ *Ошибка:* {result}"), parse_mode=ParseMode.HTML)
            else:
                await message.reply("Использование: `/give_premium @username месяцы`", parse_mode=ParseMode.MARKDOWN)
            waiting_for[user_id] = None
            return

        if text.startswith("/create_promo"):
            parts = text.split()
            if len(parts) == 4:
                ptype = parts[1]
                value = int(parts[2])
                max_uses = int(parts[3])
                code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))

                with db_transaction() as conn:
                    cursor = conn.cursor()
                    if ptype == "stars":
                        cursor.execute(
                            "INSERT INTO promocodes (code, reward_stars, max_uses, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                            (code, value, max_uses, user_id, int(time.time()))
                        )
                        await message.reply(f"✅ Промокод создан!\n`{code}`\nНаграда: {value} ⭐\nАктиваций: {max_uses}")
                    elif ptype == "premium":
                        cursor.execute(
                            "INSERT INTO promocodes (code, reward_premium_days, max_uses, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                            (code, value, max_uses, user_id, int(time.time()))
                        )
                        await message.reply(
                            f"✅ Промокод создан!\n`{code}`\nНаграда: {value} дней Premium\nАктиваций: {max_uses}")
                    elif ptype == "balance":
                        cursor.execute(
                            "INSERT INTO promocodes (code, reward_balance, max_uses, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                            (code, value, max_uses, user_id, int(time.time()))
                        )
                        await message.reply(f"✅ Промокод создан!\n`{code}`\nНаграда: {value} ⭐\nАктиваций: {max_uses}")
            else:
                await message.reply("Использование: `/create_promo stars|premium|balance значение лимит`",
                                    parse_mode=ParseMode.MARKDOWN)
            waiting_for[user_id] = None
            return

        if text.startswith("/add_task"):
            try:
                parts = text[9:].split("|")
                if len(parts) >= 4:
                    title = parts[0].strip()
                    desc = parts[1].strip()
                    reward = int(parts[2].strip())
                    channel = parts[3].strip().lstrip('@')

                    with db_transaction() as conn:
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT INTO tasks (title, description, reward_stars, task_type, target_id, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (title, desc, reward, "channel_sub", channel, user_id, int(time.time()))
                        )
                    await message.reply(f"✅ Задание создано!\n{title} | +{reward}⭐ | @{channel}")
                else:
                    await message.reply("Формат: `/add_task Название | Описание | награда | канал`",
                                        parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                await message.reply(f"Ошибка: {e}")
            waiting_for[user_id] = None
            return

        if text.startswith("/del_task"):
            parts = text.split()
            if len(parts) == 2:
                task_id = int(parts[1])
                with db_transaction() as conn:
                    cursor = conn.cursor()
                    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
                await message.reply(f"✅ Задание {task_id} удалено")
            else:
                await message.reply("Использование: `/del_task ID`", parse_mode=ParseMode.MARKDOWN)
            return


# ===== ЗАПУСК =====

async def main():
    global bot_instance
    bot_instance = app

    # Запуск вебхук сервера
    asyncio.create_task(run_webhook())

    # Запуск бота
    await app.start()
    logger.info("🚀 Бот успешно запущен!")

    # Уведомление админам
    for admin_id in ADMIN_IDS:
        try:
            await app.send_message(
                admin_id,
                get_premium_emoji_message(
                    f"{get_emoji('check')} *БОТ ЗАПУЩЕН* {get_emoji('check')}\n\n"
                    f"{get_emoji('fire')} Все системы активны!"
                ),
                parse_mode=ParseMode.HTML
            )
        except:
            pass

    await asyncio.Event().wait()


if __name__ == "__main__":
    init_database()

    # Словарь типов заданий для отображения
    TASK_TYPES = {
        "channel_sub": {"name": "Подписка на канал", "icon": "📢"},
        "group_join": {"name": "Вступление в группу", "icon": "👥"},
        "bot_start": {"name": "Запуск бота", "icon": "🤖"},
    }

    if not PYFRAGMENT_AVAILABLE:
        logger.warning("⚠️ pyfragment не установлен! Установите: pip install pyfragment")

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")