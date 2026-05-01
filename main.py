#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram Bot for selling Telegram Stars and Premium
Works ONLY with Bot Token - no API ID or API Hash required!
Auto-delivery via Fragment API with webhooks
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
import os
import sys
from datetime import datetime
from typing import Dict, Optional, Tuple, List
from contextlib import contextmanager
from functools import wraps

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    CallbackQuery, User, Bot
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, PreCheckoutQueryHandler
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

from flask import Flask, request, jsonify
import threading
import requests

# ================= НАСТРОЙКА ЛОГИРОВАНИЯ =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= КОНФИГУРАЦИЯ =================

# ТОЛЬКО ТОКЕН БОТА (получить у @BotFather)
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # ← ЗАМЕНИТЕ НА ВАШ ТОКЕН!

# Администраторы (Telegram ID)
ADMIN_IDS = [123456789]  # ← ЗАМЕНИТЕ НА ВАШ ID!

# Webhook настройки
WEBHOOK_HOST = "https://your-domain.com"  # ← ЗАМЕНИТЕ НА ВАШ ДОМЕН!
WEBHOOK_PORT = 8443
WEBHOOK_URL = f"{WEBHOOK_HOST}/webhook"

# CryptoBot настройки (https://t.me/CryptoBot)
CRYPTOBOT_TOKEN = "your_cryptobot_token"  # ← ТОКЕН ОТ CRYPTOBOT
CRYPTOBOT_API_URL = "https://pay.crypt.bot/api"

# Platega.io настройки
PLATEGA_MERCHANT_ID = "your_merchant_id"
PLATEGA_SECRET_KEY = "your_secret_key"
PLATEGA_API_URL = "https://platega.io/api/v1"

# Fragment API настройки [citation:2][citation:10]
FRAGMENT_MNEMONIC = "your_24_word_seed_phrase_here"  # 24 слова сид-фразы
FRAGMENT_COOKIES = "your_fragment_cookies"
FRAGMENT_HASH = "your_hash_value"
FRAGMENT_API_URL = "https://fragment.s1qwy.ru"  # API endpoint

# Цены
STAR_PRICE_RUB = 10  # 1 звезда = 10 рублей
STARS_PACKS = {50: 500, 100: 1000, 250: 2500, 500: 5000, 1000: 10000}
PREMIUM_PACKS = {3: 750, 6: 1400, 12: 2500}  # months: price in stars

# Эмодзи
EMOJI = {
    "star": "⭐", "gold_star": "🌟", "fire": "🔥", "crown": "👑",
    "sparkles": "✨", "rocket": "🚀", "heart": "❤️", "diamond": "💎",
    "gift": "🎁", "warning": "⚠️", "check": "✅", "cross": "❌",
    "info": "ℹ️", "settings": "⚙️", "wallet": "💰", "users": "👥",
    "stats": "📊", "mail": "📧", "code": "🎟️", "lock": "🔒",
}

# ================= FRAGMENT API КЛИЕНТ =================

class FragmentAPI:
    """Клиент для работы с Fragment API [citation:10]"""
    
    def __init__(self, mnemonic: str, cookies: str, hash_value: str, api_url: str = FRAGMENT_API_URL):
        self.mnemonic = mnemonic
        self.cookies = cookies
        self.hash_value = hash_value
        self.api_url = api_url
        self.auth_key = None
        self.session = requests.Session()
    
    def authenticate(self) -> bool:
        """Аутентификация в Fragment API"""
        try:
            response = self.session.post(
                f"{self.api_url}/auth",
                json={
                    "wallet_mnemonic": self.mnemonic,
                    "cookies": self.cookies,
                    "hash_value": self.hash_value
                }
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("ok"):
                    self.auth_key = data.get("auth_key")
                    logger.info("✅ Fragment API authentication successful")
                    return True
            logger.error(f"❌ Fragment auth failed: {response.text}")
            return False
        except Exception as e:
            logger.error(f"Fragment auth error: {e}")
            return False
    
    def buy_stars(self, username: str, quantity: int, show_sender: bool = False) -> Dict:
        """Покупка Telegram Stars через Fragment API [citation:10]"""
        if not self.auth_key:
            if not self.authenticate():
                return {"ok": False, "error": "Authentication failed"}
        
        try:
            response = self.session.post(
                f"{self.api_url}/buy_stars",
                json={
                    "auth_key": self.auth_key,
                    "username": username,
                    "quantity": quantity,
                    "show_sender": show_sender
                }
            )
            return response.json()
        except Exception as e:
            logger.error(f"Buy stars error: {e}")
            return {"ok": False, "error": str(e)}
    
    def gift_premium(self, username: str, months: int, show_sender: bool = False) -> Dict:
        """Покупка Telegram Premium через Fragment API [citation:10]"""
        if not self.auth_key:
            if not self.authenticate():
                return {"ok": False, "error": "Authentication failed"}
        
        try:
            response = self.session.post(
                f"{self.api_url}/gift_premium",
                json={
                    "auth_key": self.auth_key,
                    "username": username,
                    "months": months,
                    "show_sender": show_sender
                }
            )
            return response.json()
        except Exception as e:
            logger.error(f"Gift premium error: {e}")
            return {"ok": False, "error": str(e)}
    
    def get_balance(self) -> Dict:
        """Получение баланса кошелька [citation:10]"""
        if not self.auth_key:
            if not self.authenticate():
                return {"ok": False, "error": "Authentication failed"}
        
        try:
            response = self.session.get(
                f"{self.api_url}/balance",
                params={"auth_key": self.auth_key}
            )
            return response.json()
        except Exception as e:
            logger.error(f"Get balance error: {e}")
            return {"ok": False, "error": str(e)}
    
    def health_check(self) -> Dict:
        """Проверка статуса API"""
        try:
            response = self.session.get(f"{self.api_url}/health")
            return response.json()
        except Exception as e:
            return {"ok": False, "error": str(e)}

# ================= БАЗА ДАННЫХ =================

def init_database():
    """Инициализация базы данных"""
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # Пользователи
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0,
            join_date INTEGER DEFAULT 0,
            last_active INTEGER DEFAULT 0
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
            transaction_hash TEXT,
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
            max_uses INTEGER,
            used_count INTEGER DEFAULT 0,
            min_purchase INTEGER DEFAULT 0,
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
            is_active INTEGER DEFAULT 1,
            created_by INTEGER,
            created_at INTEGER
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS completed_tasks (
            user_id INTEGER,
            task_id INTEGER,
            completed_at INTEGER,
            PRIMARY KEY (user_id, task_id)
        )
    """)
    
    # Чёрный список
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            user_id INTEGER PRIMARY KEY,
            reason TEXT,
            banned_by INTEGER,
            banned_at INTEGER
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
    
    conn.commit()
    conn.close()
    logger.info("✅ Database initialized")

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
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        if reason:
            logger.info(f"Added {amount} stars to {user_id}: {reason}")

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def is_banned(user_id: int) -> bool:
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM blacklist WHERE user_id = ?", (user_id,))
        return cursor.fetchone() is not None

def generate_order_id(user_id: int, tx_type: str) -> str:
    return f"{tx_type}_{user_id}_{int(time.time())}_{secrets.token_hex(4)}"

def generate_promo_code(length: int = 8) -> str:
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))

def get_transaction(order_id: str) -> Optional[Dict]:
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM transactions WHERE order_id = ?", (order_id,))
        tx = cursor.fetchone()
        if tx:
            columns = [desc[0] for desc in cursor.description]
            return dict(zip(columns, tx))
        return None

def update_transaction_status(order_id: str, status: str, payment_id: str = None, tx_hash: str = None):
    with db_transaction() as conn:
        cursor = conn.cursor()
        if payment_id:
            cursor.execute(
                "UPDATE transactions SET status = ?, payment_id = ?, transaction_hash = ?, completed_at = ? WHERE order_id = ?",
                (status, payment_id, tx_hash, int(time.time()), order_id)
            )
        else:
            cursor.execute(
                "UPDATE transactions SET status = ?, completed_at = ? WHERE order_id = ?",
                (status, int(time.time()), order_id)
            )

# ================= FRAGMENT ОТПРАВКА =================

fragment_client = FragmentAPI(
    mnemonic=FRAGMENT_MNEMONIC,
    cookies=FRAGMENT_COOKIES,
    hash_value=FRAGMENT_HASH
)

async def send_stars_to_user(username: str, amount: int) -> Tuple[bool, str]:
    """Отправка звезд пользователю через Fragment API [citation:2][citation:10]"""
    if not username.startswith('@'):
        username = f"@{username}"
    
    try:
        # Проверка баланса перед покупкой
        balance = fragment_client.get_balance()
        if not balance.get('ok'):
            return False, f"Fragment API error: {balance.get('error')}"
        
        # Покупка звезд
        result = fragment_client.buy_stars(username, quantity=amount, show_sender=False)
        
        if result.get('ok'):
            tx_hash = result.get('transaction_hash', 'unknown')
            logger.info(f"Stars sent: {amount} to {username}, tx: {tx_hash}")
            return True, tx_hash
        else:
            return False, result.get('error', 'Unknown error')
    except Exception as e:
        logger.error(f"Send stars error: {e}")
        return False, str(e)

async def send_premium_to_user(username: str, months: int) -> Tuple[bool, str]:
    """Отправка Premium пользователю через Fragment API [citation:2][citation:10]"""
    if not username.startswith('@'):
        username = f"@{username}"
    
    try:
        # Проверка баланса
        balance = fragment_client.get_balance()
        if not balance.get('ok'):
            return False, f"Fragment API error: {balance.get('error')}"
        
        # Покупка Premium
        result = fragment_client.gift_premium(username, months=months, show_sender=False)
        
        if result.get('ok'):
            tx_hash = result.get('transaction_hash', 'unknown')
            logger.info(f"Premium sent: {months} months to {username}, tx: {tx_hash}")
            return True, tx_hash
        else:
            # Обработка ошибок Fragment API
            error_msg = result.get('error', 'Unknown error')
            if 'insufficient' in error_msg.lower():
                error_msg = "Недостаточно средств на кошельке Fragment"
            return False, error_msg
    except Exception as e:
        logger.error(f"Send premium error: {e}")
        return False, str(e)

# ================= ПЛАТЕЖНЫЕ СИСТЕМЫ =================

class CryptoBotClient:
    """Клиент для работы с CryptoBot API"""
    
    def __init__(self, token: str):
        self.token = token
        self.headers = {"Crypto-Pay-API-Token": token, "Content-Type":application/json"}
    
    async def create_invoice(self, amount: float, description: str = "") -> Optional[Dict]:
        """Создание счёта в CryptoBot"""
        async with aiohttp.ClientSession() as session:
            data = {"asset": "RUB", "amount": str(amount), "description": description}
            try:
                async with session.post(f"{CRYPTOBOT_API_URL}/createInvoice", headers=self.headers, json=data) as resp:
                    result = await resp.json()
                    if result.get("ok"):
                        return {
                            "invoice_id": result["result"]["invoice_id"],
                            "pay_url": result["result"]["pay_url"]
                        }
                    logger.error(f"CryptoBot error: {result}")
                    return None
            except Exception as e:
                logger.error(f"CryptoBot error: {e}")
                return None
    
    @staticmethod
    def verify_webhook(data: bytes, signature: str, token: str) -> bool:
        """Проверка подписи вебхука CryptoBot"""
        secret = hashlib.sha256(token.encode()).digest()
        computed = hmac.new(secret, data, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, signature)

class PlategaClient:
    """Клиент для работы с Platega.io API"""
    
    def __init__(self, merchant_id: str, secret_key: str):
        self.merchant_id = merchant_id
        self.secret_key = secret_key
    
    async def create_transaction(self, amount: float, order_id: str, description: str = "") -> Optional[Dict]:
        """Создание транзакции в Platega"""
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
                        return {
                            "transaction_id": result["transaction_id"],
                            "payment_url": result["payment_url"]
                        }
                    logger.error(f"Platega error: {result}")
                    return None
            except Exception as e:
                logger.error(f"Platega error: {e}")
                return None

cryptobot = CryptoBotClient(CRYPTOBOT_TOKEN)
platega = PlategaClient(PLATEGA_MERCHANT_ID, PLATEGA_SECRET_KEY)

# ================= КЛАВИАТУРЫ =================

def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Главная клавиатура"""
    buttons = [
        [InlineKeyboardButton(f"{EMOJI['star']} Купить звезды", callback_data="buy_stars_menu")],
        [InlineKeyboardButton(f"{EMOJI['crown']} Купить Premium", callback_data="buy_premium_menu")],
        [InlineKeyboardButton(f"{EMOJI['wallet']} Мой баланс", callback_data="my_balance")],
        [InlineKeyboardButton(f"{EMOJI['rocket']} Задания", callback_data="tasks_menu")],
        [InlineKeyboardButton(f"{EMOJI['gift']} Промокод", callback_data="activate_promo")],
        [InlineKeyboardButton(f"{EMOJI['info']} О боте", callback_data="about")],
    ]
    if is_admin(user_id):
        buttons.append([InlineKeyboardButton(f"{EMOJI['settings']} Админ панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Админ панель"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{EMOJI['stats']} Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(f"{EMOJI['mail']} Рассылка", callback_data="admin_mailing")],
        [InlineKeyboardButton(f"{EMOJI['code']} Промокоды", callback_data="admin_promocodes")],
        [InlineKeyboardButton(f"{EMOJI['rocket']} Задания", callback_data="admin_tasks")],
        [InlineKeyboardButton(f"{EMOJI['star']} Выдать звезды", callback_data="admin_give_stars")],
        [InlineKeyboardButton(f"{EMOJI['crown']} Выдать Premium", callback_data="admin_give_premium")],
        [InlineKeyboardButton(f"{EMOJI['users']} Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(f"{EMOJI['lock']} Чёрный список", callback_data="admin_blacklist")],
        [InlineKeyboardButton(f"{EMOJI['diamond']} Баланс Fragment", callback_data="admin_fragment_balance")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
    ])

def get_stars_keyboard() -> InlineKeyboardMarkup:
    """Выбор количества звезд"""
    buttons = []
    for stars, price in STARS_PACKS.items():
        buttons.append([InlineKeyboardButton(f"{EMOJI['star']} {stars} ⭐ ({price} ₽)", callback_data=f"buy_stars:{stars}:{price}")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(buttons)

def get_premium_keyboard() -> InlineKeyboardMarkup:
    """Выбор Premium подписки"""
    buttons = []
    for months, price in PREMIUM_PACKS.items():
        discount = " -10%" if months == 6 else " -20%" if months == 12 else ""
        buttons.append([InlineKeyboardButton(f"{EMOJI['crown']} {months} мес. ({price} ⭐){discount}", callback_data=f"buy_premium:{months}:{price}")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    return InlineKeyboardMarkup(buttons)

def get_payment_keyboard(order_id: str, amount: int, product_type: str) -> InlineKeyboardMarkup:
    """Выбор способа оплаты"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 CryptoBot", callback_data=f"pay:cryptobot:{order_id}:{amount}:{product_type}")],
        [InlineKeyboardButton("💳 Platega.io", callback_data=f"pay:platega:{order_id}:{amount}:{product_type}")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"back_to_{product_type}")]
    ])

# ================= ОБРАБОТКА ПЛАТЕЖЕЙ =================

async def process_successful_payment(order_id: str, payment_system: str, payment_id: str, app: Application):
    """Обработка успешного платежа - отправка товара через Fragment"""
    tx = get_transaction(order_id)
    if not tx:
        logger.error(f"Transaction {order_id} not found")
        return False
    
    if tx['status'] == 'completed':
        logger.info(f"Transaction {order_id} already processed")
        return True
    
    user_id = tx['user_id']
    
    # Получаем username пользователя
    try:
        user_info = await app.bot.get_chat(user_id)
        username = user_info.username
        if not username:
            await app.bot.send_message(user_id, "❌ Установите username в Telegram для получения товара!")
            return False
    except Exception as e:
        logger.error(f"Error getting username: {e}")
        return False
    
    success = False
    tx_hash = ""
    
    # Отправка звезд через Fragment
    if tx.get('stars_amount') and tx['stars_amount'] > 0:
        success, tx_hash = await send_stars_to_user(username, tx['stars_amount'])
        if success:
            add_stars(user_id, tx['stars_amount'], f"Purchase {tx['stars_amount']} stars")
            update_transaction_status(order_id, 'completed', payment_id, tx_hash)
            
            await app.bot.send_message(
                user_id,
                f"✅ *Оплата подтверждена!*\n\n"
                f"{EMOJI['star']} {tx['stars_amount']} Telegram Stars отправлено!\n"
                f"Transaction: `{tx_hash}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return True
    
    # Отправка Premium через Fragment
    elif tx.get('premium_months') and tx['premium_months'] > 0:
        success, tx_hash = await send_premium_to_user(username, tx['premium_months'])
        if success:
            update_transaction_status(order_id, 'completed', payment_id, tx_hash)
            
            await app.bot.send_message(
                user_id,
                f"✅ *Оплата подтверждена!*\n\n"
                f"{EMOJI['crown']} Telegram Premium на {tx['premium_months']} месяцев активирован!\n"
                f"Transaction: `{tx_hash}`",
                parse_mode=ParseMode.MARKDOWN
            )
            return True
    
    if not success:
        logger.error(f"Failed to deliver product: {tx_hash}")
        await app.bot.send_message(
            user_id,
            f"❌ *Ошибка выдачи товара*\n\n{tx_hash}\nОбратитесь в поддержку.",
            parse_mode=ParseMode.MARKDOWN
        )
    
    return success

# ================= FLASK WEBHOOK СЕРВЕР =================

flask_app = Flask(__name__)
bot_application = None

@flask_app.route('/webhook/cryptobot', methods=['POST'])
def cryptobot_webhook():
    """Обработчик вебхука CryptoBot"""
    try:
        signature = request.headers.get('Crypto-Pay-API-Signature', '')
        body = request.get_data()
        
        if not cryptobot.verify_webhook(body, signature, CRYPTOBOT_TOKEN):
            return jsonify({"error": "Invalid signature"}), 401
        
        data = request.json
        logger.info(f"CryptoBot webhook: {data}")
        
        if data.get('update_type') == 'invoice_paid':
            payload = data.get('payload', {})
            order_id = payload.get('description', '')
            invoice_id = str(payload.get('invoice_id', ''))
            
            if order_id and invoice_id:
                asyncio.run_coroutine_threadsafe(
                    process_successful_payment(order_id, 'cryptobot', invoice_id, bot_application),
                    bot_application.loop
                )
        
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"CryptoBot webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@flask_app.route('/webhook/platega', methods=['POST'])
def platega_webhook():
    """Обработчик вебхука Platega.io"""
    try:
        data = request.json
        logger.info(f"Platega webhook: {data}")
        
        if data.get('event') == 'transaction.completed':
            order_id = data.get('order_id', '')
            transaction_id = data.get('transaction_id', '')
            
            if order_id and transaction_id:
                asyncio.run_coroutine_threadsafe(
                    process_successful_payment(order_id, 'platega', transaction_id, bot_application),
                    bot_application.loop
                )
        
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Platega webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@flask_app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "ok", "timestamp": int(time.time())})

def run_webhook_server():
    """Запуск Flask сервера для вебхуков"""
    flask_app.run(host='0.0.0.0', port=WEBHOOK_PORT, threaded=True)

# ================= ОСНОВНОЙ БОТ (TELEGRAM) =================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = update.effective_user.id
    
    if is_banned(user_id):
        await update.message.reply_text("🚫 Вы заблокированы!")
        return
    
    user = get_user(user_id)
    update_user(user_id,
                username=update.effective_user.username or "",
                first_name=update.effective_user.first_name or "",
                last_active=int(time.time()))
    
    welcome_text = f"""
{EMOJI['star']}{EMOJI['crown']} *Добро пожаловать в магазин Stars & Premium!* {EMOJI['crown']}{EMOJI['star']}

{EMOJI['wallet']} *Ваш баланс:* {user['balance']} ⭐

{EMOJI['rocket']} Покупайте Telegram Stars и Premium с автовыдачей!
{EMOJI['diamond']} Оплата через CryptoBot и Platega.io
{EMOJI['sparkles']} Мгновенная доставка через Fragment API

Используйте кнопки ниже для навигации!
"""
    
    await update.message.reply_text(
        welcome_text,
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.MARKDOWN
    )

async def my_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать баланс пользователя"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = get_user(user_id)
    
    text = f"""
{EMOJI['wallet']} *МОЙ БАЛАНС* {EMOJI['wallet']}

{EMOJI['star']} *Звезд:* {user['balance']} ⭐
{EMOJI['diamond']} *Всего потрачено:* {user['total_spent']} ₽
{EMOJI['gift']} *Дата регистрации:* {datetime.fromtimestamp(user['join_date']).strftime('%d.%m.%Y')}

{EMOJI['info']} Пополнить баланс можно через Магазин → Купить звезды
"""
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def buy_stars_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню покупки звезд"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        f"{EMOJI['star']} *Выберите количество Telegram Stars:* {EMOJI['star']}",
        reply_markup=get_stars_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def buy_premium_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню покупки Premium"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        f"{EMOJI['crown']} *Выберите период Premium подписки:* {EMOJI['crown']}\n\n"
        f"💎 *Преимущества Premium:*\n"
        f"• {EMOJI['sparkles']} Эксклюзивные эмодзи и стикеры\n"
        f"• {EMOJI['rocket']} Ускоренная загрузка медиа\n"
        f"• {EMOJI['heart']} Приоритет в чатах\n"
        f"• {EMOJI['gift']} Ежемесячные бонусы\n\n"
        f"Оплата происходит звездами с вашего баланса!",
        reply_markup=get_premium_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def buy_stars_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка покупки звезд"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    _, stars, price = data.split(":")
    stars, price = int(stars), int(price)
    
    order_id = generate_order_id(query.from_user.id, "stars")
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO transactions (user_id, order_id, amount_rub, stars_amount, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (query.from_user.id, order_id, price, stars, "pending", int(time.time()))
        )
    
    await query.edit_message_text(
        f"{EMOJI['star']} *{stars} звезд*\nСумма: {price} ₽\n\n"
        f"Выберите способ оплаты:",
        reply_markup=get_payment_keyboard(order_id, price, "stars"),
        parse_mode=ParseMode.MARKDOWN
    )

async def buy_premium_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка покупки Premium (за звезды с баланса)"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    _, months, stars_price = data.split(":")
    months, stars_price = int(months), int(stars_price)
    
    user_id = query.from_user.id
    user = get_user(user_id)
    
    if user['balance'] < stars_price:
        await query.answer(f"❌ Недостаточно звезд! Нужно: {stars_price}", show_alert=True)
        return
    
    await query.edit_message_text(
        f"{EMOJI['rocket']} *Оформление Premium...*",
        parse_mode=ParseMode.MARKDOWN
    )
    
    username = query.from_user.username
    if not username:
        await query.edit_message_text(
            "❌ *Установите username в Telegram!*\n\n"
            "Перейдите в Настройки → username и установите имя пользователя.",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    # Отправка Premium через Fragment
    success, tx_hash = await send_premium_to_user(username, months)
    
    if success:
        # Списание звезд
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (stars_price, user_id))
            cursor.execute(
                "INSERT INTO transactions (user_id, order_id, amount_rub, premium_months, status, transaction_hash, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, f"premium_{user_id}_{int(time.time())}", stars_price, months, "completed", tx_hash, int(time.time()))
            )
        
        await query.edit_message_text(
            f"✅ *Premium на {months} месяцев успешно активирован!*\n\n"
            f"{EMOJI['star']} Списано: {stars_price} ⭐\n"
            f"{EMOJI['crown']} Premium активирован!\n"
            f"Transaction: `{tx_hash}`",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await query.edit_message_text(
            f"❌ *Ошибка активации Premium*\n\n{tx_hash}",
            reply_markup=get_main_keyboard(user_id),
            parse_mode=ParseMode.MARKDOWN
        )

async def payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание платежа через выбранную систему"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    _, payment_system, order_id, amount, product_type = data.split(":")
    amount = int(amount)
    
    await query.edit_message_text(
        f"{EMOJI['rocket']} *Создание платежа...*",
        parse_mode=ParseMode.MARKDOWN
    )
    
    if payment_system == "cryptobot":
        invoice = await cryptobot.create_invoice(amount, order_id)
        if invoice:
            await query.edit_message_text(
                f"💳 *Оплата через CryptoBot*\n\n"
                f"Сумма: {amount} ₽\n\n"
                f"🔗 [Нажмите для оплаты]({invoice['pay_url']})\n\n"
                f"{EMOJI['info']} После оплаты товар придет автоматически!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Оплатить", url=invoice['pay_url'])],
                    [InlineKeyboardButton("🔙 Назад", callback_data="buy_stars_menu")]
                ]),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
            update_transaction_status(order_id, "pending", str(invoice['invoice_id']))
        else:
            await query.edit_message_text(
                f"❌ *Ошибка создания платежа*\n\nПопробуйте позже или выберите другой способ.",
                reply_markup=get_stars_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif payment_system == "platega":
        invoice = await platega.create_transaction(amount, order_id, f"Покупка {product_type}")
        if invoice:
            await query.edit_message_text(
                f"💳 *Оплата через Platega.io*\n\n"
                f"Сумма: {amount} ₽\n\n"
                f"🔗 [Нажмите для оплаты]({invoice['payment_url']})\n\n"
                f"{EMOJI['info']} После оплаты товар придет автоматически!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔗 Оплатить", url=invoice['payment_url'])],
                    [InlineKeyboardButton("🔙 Назад", callback_data="buy_stars_menu")]
                ]),
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
        else:
            await query.edit_message_text(
                f"❌ *Ошибка создания платежа*\n\nПопробуйте позже.",
                reply_markup=get_stars_keyboard(),
                parse_mode=ParseMode.MARKDOWN
            )

async def activate_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Активация промокода"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['waiting_for_promo'] = True
    
    await query.edit_message_text(
        f"{EMOJI['gift']} *Активация промокода* {EMOJI['gift']}\n\n"
        f"Введите промокод текстовым сообщением:",
        parse_mode=ParseMode.MARKDOWN
    )

async def handle_promo_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенного промокода"""
    if not context.user_data.get('waiting_for_promo'):
        return
    
    user_id = update.effective_user.id
    code = update.message.text.upper().strip()
    
    del context.user_data['waiting_for_promo']
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT reward_stars, reward_premium_days, max_uses, used_count, is_active, expires_at FROM promocodes WHERE code = ?",
            (code,)
        )
        promo = cursor.fetchone()
    
    if not promo:
        await update.message.reply_text(
            f"{EMOJI['cross']} *Промокод не найден!*",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    reward_stars, reward_days, max_uses, used_count, is_active, expires_at = promo
    
    if not is_active or used_count >= max_uses:
        await update.message.reply_text(
            f"{EMOJI['cross']} *Промокод неактивен или использован максимальное число раз!*",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    if expires_at and expires_at < int(time.time()):
        await update.message.reply_text(
            f"{EMOJI['cross']} *Срок действия промокода истек!*",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM promo_usage WHERE user_id = ? AND code = ?", (user_id, code))
        if cursor.fetchone():
            await update.message.reply_text(
                f"{EMOJI['cross']} *Вы уже активировали этот промокод!*",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        if reward_stars > 0:
            add_stars(user_id, reward_stars, f"Promocode {code}")
            await update.message.reply_text(
                f"{EMOJI['check']} *Промокод активирован!*\n\n{EMOJI['star']} +{reward_stars} звезд",
                parse_mode=ParseMode.MARKDOWN
            )
        
        if reward_days > 0:
            await update.message.reply_text(
                f"{EMOJI['check']} *Промокод активирован!*\n\n{EMOJI['crown']} +{reward_days} дней Premium",
                parse_mode=ParseMode.MARKDOWN
            )
        
        cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?", (code,))
        cursor.execute("INSERT INTO promo_usage (user_id, code, used_at) VALUES (?, ?, ?)", (user_id, code, int(time.time())))

async def tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню заданий"""
    query = update.callback_query
    await query.answer()
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, description, reward_stars, target_id FROM tasks WHERE is_active = 1")
        tasks = cursor.fetchall()
    
    if not tasks:
        await query.edit_message_text(
            f"{EMOJI['info']} *Нет доступных заданий*\n\nЗагляните позже!",
            reply_markup=get_main_keyboard(query.from_user.id),
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    buttons = []
    for task in tasks:
        task_id, title, desc, reward, target = task
        
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ?", (query.from_user.id, task_id))
            completed = cursor.fetchone()
        
        status = "✅" if completed else "📌"
        buttons.append([InlineKeyboardButton(f"{status} {title} (+{reward}⭐)", callback_data=f"view_task:{task_id}")])
    
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")])
    
    await query.edit_message_text(
        f"{EMOJI['rocket']} *Доступные задания* {EMOJI['rocket']}\n\n"
        f"✅ - выполнено | 📌 - доступно\n"
        f"Выполняйте и получайте звезды!",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN
    )

async def view_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просмотр задания"""
    query = update.callback_query
    await query.answer()
    
    task_id = int(query.data.split(":")[1])
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, description, reward_stars, task_type, target_id FROM tasks WHERE id = ? AND is_active = 1", (task_id,))
        task = cursor.fetchone()
    
    if not task:
        await query.answer("Задание не найдено!")
        return
    
    task_id, title, desc, reward, task_type, target = task
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ?", (query.from_user.id, task_id))
        if cursor.fetchone():
            await query.answer("✅ Вы уже выполнили это задание!", show_alert=True)
            return
    
    text = f"""
📋 *{title}*

{desc}

{EMOJI['star']} *Награда:* {reward} ⭐
{EMOJI['info']} *Тип:* Подписка на канал

*Как выполнить:*
• Подпишитесь на канал @{target}
• Нажмите кнопку проверки
"""
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 Подписаться", url=f"https://t.me/{target}")],
            [InlineKeyboardButton("✅ Проверить", callback_data=f"check_task:{task_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="tasks_menu")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def check_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка выполнения задания"""
    query = update.callback_query
    await query.answer()
    
    task_id = int(query.data.split(":")[1])
    user_id = query.from_user.id
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT target_id, reward_stars FROM tasks WHERE id = ?", (task_id,))
        task = cursor.fetchone()
    
    if not task:
        await query.answer("Задание не найдено!")
        return
    
    target_id, reward = task
    
    # Проверка подписки через Telegram Bot API
    try:
        chat_member = await context.bot.get_chat_member(chat_id=f"@{target_id}", user_id=user_id)
        if chat_member.status in ['member', 'administrator', 'creator']:
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM completed_tasks WHERE user_id = ? AND task_id = ?", (user_id, task_id))
                if not cursor.fetchone():
                    add_stars(user_id, reward, f"Task {task_id}")
                    cursor.execute("INSERT INTO completed_tasks (user_id, task_id, completed_at) VALUES (?, ?, ?)",
                                 (user_id, task_id, int(time.time())))
                    
                    await query.edit_message_text(
                        f"✅ *Задание выполнено!*\n\n{EMOJI['star']} +{reward} звезд",
                        reply_markup=get_main_keyboard(user_id),
                        parse_mode=ParseMode.MARKDOWN
                    )
                else:
                    await query.answer("Вы уже получали награду!", show_alert=True)
        else:
            await query.answer("❌ Вы не подписаны на канал!", show_alert=True)
    except Exception as e:
        await query.answer(f"Ошибка проверки. Убедитесь, что вы подписались!", show_alert=True)

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """О боте"""
    query = update.callback_query
    await query.answer()
    
    text = f"""
{EMOJI['info']} *О НАС* {EMOJI['info']}

⭐ *Stars & Premium Shop*

Мы предлагаем:
• Telegram Stars по лучшим ценам
• Premium подписки от 3 месяцев
• Мгновенная выдача через Fragment API
• Поддержка 24/7

{EMOJI['diamond']} *Платежные системы:*
• CryptoBot
• Platega.io

{EMOJI['contact']} *Поддержка:* @support
{EMOJI['news']} *Новости:* @news_channel
"""
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def back_to_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в главное меню"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user = get_user(user_id)
    
    await query.edit_message_text(
        f"{EMOJI['star']} *Главное меню* {EMOJI['star']}\n\n{EMOJI['wallet']} Баланс: {user['balance']} ⭐",
        reply_markup=get_main_keyboard(user_id),
        parse_mode=ParseMode.MARKDOWN
    )

# ================= АДМИН ФУНКЦИИ =================

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ панель"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    await query.edit_message_text(
        f"{EMOJI['settings']} *Панель администратора* {EMOJI['settings']}",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Статистика бота"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT SUM(balance) FROM users")
        total_balance = cursor.fetchone()[0] or 0
        cursor.execute("SELECT SUM(amount_rub) FROM transactions WHERE status = 'completed'")
        total_income = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE status = 'completed' AND stars_amount > 0")
        stars_sales = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM transactions WHERE status = 'completed' AND premium_months > 0")
        premium_sales = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM completed_tasks")
        tasks_completed = cursor.fetchone()[0] or 0
    
    text = f"""
{EMOJI['stats']} *СТАТИСТИКА БОТА* {EMOJI['stats']}

👥 *Пользователей:* {total_users}
⭐ *Баланс пользователей:* {total_balance}
💰 *Доход:* {total_income} ₽

📊 *ПРОДАЖИ:*
{EMOJI['star']} Продано звезд: {stars_sales}
{EMOJI['crown']} Продано Premium: {premium_sales}

📋 *ЗАДАНИЯ:*
✅ Выполнено заданий: {tasks_completed}
"""
    
    await query.edit_message_text(
        text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_fragment_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка баланса Fragment кошелька"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    await query.edit_message_text(
        f"{EMOJI['rocket']} *Проверка баланса Fragment...*",
        parse_mode=ParseMode.MARKDOWN
    )
    
    balance = fragment_client.get_balance()
    
    if balance.get('ok'):
        text = f"""
{EMOJI['diamond']} *БАЛАНС FRAGMENT* {EMOJI['diamond']}

💰 *Баланс TON:* {balance.get('balance', 0)} TON

{EMOJI['info']} Эти средства используются для покупки звезд и Premium.
"""
    else:
        text = f"""
❌ *Ошибка получения баланса*

{balance.get('error', 'Unknown error')}

Проверьте настройки Fragment API.
"""
    
    await query.edit_message_text(
        text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_give_stars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача звезд пользователю (админ команда)"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    context.user_data['admin_action'] = 'give_stars'
    
    await query.edit_message_text(
        f"{EMOJI['star']} *Выдача звезд*\n\n"
        f"Введите команду:\n"
        f"`/give_stars @username количество`\n\n"
        f"Пример: `/give_stars @durov 100`",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_give_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдача Premium пользователю (админ команда)"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    context.user_data['admin_action'] = 'give_premium'
    
    await query.edit_message_text(
        f"{EMOJI['crown']} *Выдача Premium*\n\n"
        f"Введите команду:\n"
        f"`/give_premium @username месяцы`\n\n"
        f"Пример: `/give_premium @durov 3`",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_mailing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Рассылка сообщений"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    context.user_data['admin_action'] = 'mailing'
    
    await query.edit_message_text(
        f"{EMOJI['mail']} *Создание рассылки* {EMOJI['mail']}\n\n"
        f"Отправьте сообщение для рассылки.\n\n"
        f"{EMOJI['info']} Поддерживается текст, фото, видео.\n"
        f"Для отмены отправьте /cancel",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_blacklist_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню черного списка"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    context.user_data['admin_action'] = 'blacklist'
    
    await query.edit_message_text(
        f"{EMOJI['lock']} *Чёрный список* {EMOJI['lock']}\n\n"
        f"Введите команду:\n"
        f"`/ban @username причина` - заблокировать\n"
        f"`/unban @username` - разблокировать\n\n"
        f"Пример: `/ban @spamer Спам`",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_promocodes_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления промокодами"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT code, reward_stars, reward_premium_days, max_uses, used_count, is_active FROM promocodes ORDER BY created_at DESC LIMIT 10")
        promos = cursor.fetchall()
    
    if promos:
        text = f"{EMOJI['code']} *Активные промокоды:*\n\n"
        for promo in promos:
            code, stars, days, max_uses, used, active = promo
            status = "✅" if active else "❌"
            reward = f"{stars}⭐" if stars else f"{days}дн."
            text += f"{status} `{code}` | {reward} | {used}/{max_uses}\n"
    else:
        text = f"{EMOJI['info']} Промокодов нет"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Создать", callback_data="admin_create_promo")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_create_promo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание промокода"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    context.user_data['admin_action'] = 'create_promo'
    
    await query.edit_message_text(
        f"{EMOJI['gift']} *Создание промокода*\n\n"
        f"Введите команду:\n"
        f"`/create_promo stars 100 50` - 100 звезд, 50 активаций\n"
        f"`/create_promo premium 30 10` - 30 дней Premium, 10 активаций\n\n"
        f"Пример: `/create_promo stars 500 100`",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_tasks_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления заданиями"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, title, reward_stars, is_active FROM tasks ORDER BY id")
        tasks = cursor.fetchall()
    
    if tasks:
        text = f"{EMOJI['rocket']} *Список заданий:*\n\n"
        for task in tasks:
            task_id, title, reward, active = task
            status = "✅" if active else "❌"
            text += f"{status} ID `{task_id}` | {title} | +{reward}⭐\n"
        text += f"\n{EMOJI['info']} Для удаления: `/del_task ID`"
    else:
        text = f"{EMOJI['info']} Заданий нет"
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Создать", callback_data="admin_create_task")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_panel")]
        ]),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_create_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создание задания"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    context.user_data['admin_action'] = 'create_task'
    
    await query.edit_message_text(
        f"{EMOJI['plus']} *Создание задания*\n\n"
        f"Введите команду:\n"
        f"`/add_task Название | Описание | награда | канал`\n\n"
        f"Пример: `/add_task Подписка | Подпишись на новости | 50 | my_channel`",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

async def admin_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Информация о пользователях"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_admin(user_id):
        await query.answer("⛔ Доступ запрещен!", show_alert=True)
        return
    
    await query.answer()
    
    with db_transaction() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE join_date > ?", (int(time.time()) - 86400,))
        new_today = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE last_active > ?", (int(time.time()) - 86400,))
        active_today = cursor.fetchone()[0]
        cursor.execute("SELECT user_id, username, balance FROM users ORDER BY balance DESC LIMIT 5")
        top_users = cursor.fetchall()
    
    text = f"""
{EMOJI['users']} *ПОЛЬЗОВАТЕЛИ* {EMOJI['users']}

👥 *Всего:* {total}
📈 *Новых за 24ч:* {new_today}
✅ *Активных за 24ч:* {active_today}

{EMOJI['star']} *ТОП-5 ПО БАЛАНСУ:*
"""
    
    for i, (uid, username, balance) in enumerate(top_users, 1):
        name = username or str(uid)
        text += f"{i}. @{name} - {balance}⭐\n"
    
    await query.edit_message_text(
        text,
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

# ================= ОБРАБОТКА ТЕКСТОВЫХ КОМАНД (АДМИН) =================

async def handle_admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых команд от админов"""
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return
    
    text = update.message.text.strip()
    
    # Рассылка
    if context.user_data.get('admin_action') == 'mailing':
        await update.message.reply_text(f"{EMOJI['rocket']} *Начинаю рассылку...*", parse_mode=ParseMode.MARKDOWN)
        
        with db_transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users")
            users = cursor.fetchall()
        
        success = 0
        fail = 0
        
        for (uid,) in users:
            try:
                await update.message.copy(uid)
                success += 1
            except Exception:
                fail += 1
            await asyncio.sleep(0.05)
        
        await update.message.reply_text(
            f"{EMOJI['check']} *Рассылка завершена!*\n\n✅ Успешно: {success}\n❌ Ошибок: {fail}",
            parse_mode=ParseMode.MARKDOWN
        )
        context.user_data['admin_action'] = None
        return
    
    # Выдача звезд
    if text.startswith("/give_stars"):
        parts = text.split()
        if len(parts) == 3:
            username = parts[1].lstrip('@')
            amount = int(parts[2])
            
            success, tx_hash = await send_stars_to_user(username, amount)
            
            if success:
                await update.message.reply_text(
                    f"{EMOJI['check']} *{amount} звезд отправлено* @{username}\nTX: `{tx_hash}`",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"{EMOJI['cross']} *Ошибка:* {tx_hash}",
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            await update.message.reply_text(
                f"{EMOJI['warning']} Использование: `/give_stars @username количество`",
                parse_mode=ParseMode.MARKDOWN
            )
        context.user_data['admin_action'] = None
        return
    
    # Выдача Premium
    if text.startswith("/give_premium"):
        parts = text.split()
        if len(parts) == 3:
            username = parts[1].lstrip('@')
            months = int(parts[2])
            
            success, tx_hash = await send_premium_to_user(username, months)
            
            if success:
                await update.message.reply_text(
                    f"{EMOJI['check']} *Premium на {months} месяцев отправлен* @{username}\nTX: `{tx_hash}`",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"{EMOJI['cross']} *Ошибка:* {tx_hash}",
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            await update.message.reply_text(
                f"{EMOJI['warning']} Использование: `/give_premium @username месяцы`",
                parse_mode=ParseMode.MARKDOWN
            )
        context.user_data['admin_action'] = None
        return
    
    # Создание промокода
    if text.startswith("/create_promo"):
        parts = text.split()
        if len(parts) == 4:
            ptype = parts[1]
            value = int(parts[2])
            max_uses = int(parts[3])
            code = generate_promo_code()
            
            with db_transaction() as conn:
                cursor = conn.cursor()
                if ptype == "stars":
                    cursor.execute(
                        "INSERT INTO promocodes (code, reward_stars, max_uses, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                        (code, value, max_uses, user_id, int(time.time()))
                    )
                    await update.message.reply_text(
                        f"{EMOJI['check']} *Промокод создан!*\n\n"
                        f"`{code}`\n"
                        f"{EMOJI['star']} Награда: {value} ⭐\n"
                        f"{EMOJI['users']} Активаций: {max_uses}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                elif ptype == "premium":
                    cursor.execute(
                        "INSERT INTO promocodes (code, reward_premium_days, max_uses, created_by, created_at) VALUES (?, ?, ?, ?, ?)",
                        (code, value, max_uses, user_id, int(time.time()))
                    )
                    await update.message.reply_text(
                        f"{EMOJI['check']} *Промокод создан!*\n\n"
                        f"`{code}`\n"
                        f"{EMOJI['crown']} Награда: {value} дней Premium\n"
                        f"{EMOJI['users']} Активаций: {max_uses}",
                        parse_mode=ParseMode.MARKDOWN
                    )
        else:
            await update.message.reply_text(
                f"{EMOJI['warning']} Использование: `/create_promo stars|premium значение лимит`",
                parse_mode=ParseMode.MARKDOWN
            )
        context.user_data['admin_action'] = None
        return
    
    # Создание задания
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
                await update.message.reply_text(
                    f"{EMOJI['check']} *Задание создано!*\n\n"
                    f"📋 {title}\n"
                    f"{EMOJI['star']} +{reward}⭐\n"
                    f"📢 Канал: @{channel}",
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await update.message.reply_text(
                    f"{EMOJI['warning']} Формат: `/add_task Название | Описание | награда | канал`",
                    parse_mode=ParseMode.MARKDOWN
                )
        except Exception as e:
            await update.message.reply_text(f"Ошибка: {e}")
        context.user_data['admin_action'] = None
        return
    
    # Удаление задания
    if text.startswith("/del_task"):
        parts = text.split()
        if len(parts) == 2:
            task_id = int(parts[1])
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            await update.message.reply_text(
                f"{EMOJI['check']} *Задание {task_id} удалено*",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"{EMOJI['warning']} Использование: `/del_task ID`",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Бан пользователя
    if text.startswith("/ban"):
        parts = text.split(maxsplit=2)
        if len(parts) >= 2:
            username = parts[1].lstrip('@')
            reason = parts[2] if len(parts) > 2 else "Нарушение правил"
            
            # Поиск user_id по username
            try:
                chat = await context.bot.get_chat(f"@{username}")
                target_id = chat.id
            except:
                await update.message.reply_text(f"❌ Пользователь @{username} не найден")
                return
            
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT OR REPLACE INTO blacklist (user_id, reason, banned_by, banned_at) VALUES (?, ?, ?, ?)",
                    (target_id, reason, user_id, int(time.time()))
                )
            
            await update.message.reply_text(
                f"{EMOJI['lock']} *Пользователь @{username} заблокирован*\nПричина: {reason}",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"{EMOJI['warning']} Использование: `/ban @username причина`",
                parse_mode=ParseMode.MARKDOWN
            )
        return
    
    # Разбан пользователя
    if text.startswith("/unban"):
        parts = text.split()
        if len(parts) == 2:
            username = parts[1].lstrip('@')
            
            try:
                chat = await context.bot.get_chat(f"@{username}")
                target_id = chat.id
            except:
                await update.message.reply_text(f"❌ Пользователь @{username} не найден")
                return
            
            with db_transaction() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM blacklist WHERE user_id = ?", (target_id,))
            
            await update.message.reply_text(
                f"{EMOJI['unlock']} *Пользователь @{username} разблокирован*",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(
                f"{EMOJI['warning']} Использование: `/unban @username`",
                parse_mode=ParseMode.MARKDOWN
            )
        return

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущего действия"""
    if context.user_data.get('admin_action'):
        context.user_data['admin_action'] = None
        await update.message.reply_text(
            f"{EMOJI['check']} *Действие отменено*",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text("Нет активных действий для отмены")

# ================= ЗАПУСК БОТА =================

def main():
    """Основная функция запуска бота"""
    global bot_application
    
    # Инициализация БД
    init_database()
    
    # Проверка Fragment API
    logger.info("Checking Fragment API...")
    health = fragment_client.health_check()
    if health.get('ok'):
        logger.info("✅ Fragment API available")
    else:
        logger.warning(f"⚠️ Fragment API unavailable: {health.get('error')}")
    
    # Создание приложения
    application = Application.builder().token(BOT_TOKEN).build()
    bot_application = application
    
    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("cancel", cancel))
    
    # Регистрация callback обработчиков
    application.add_handler(CallbackQueryHandler(my_balance, pattern="^my_balance$"))
    application.add_handler(CallbackQueryHandler(buy_stars_menu, pattern="^buy_stars_menu$"))
    application.add_handler(CallbackQueryHandler(buy_premium_menu, pattern="^buy_premium_menu$"))
    application.add_handler(CallbackQueryHandler(buy_stars_callback, pattern="^buy_stars:"))
    application.add_handler(CallbackQueryHandler(buy_premium_callback, pattern="^buy_premium:"))
    application.add_handler(CallbackQueryHandler(payment_callback, pattern="^pay:"))
    application.add_handler(CallbackQueryHandler(activate_promo, pattern="^activate_promo$"))
    application.add_handler(CallbackQueryHandler(tasks_menu, pattern="^tasks_menu$"))
    application.add_handler(CallbackQueryHandler(view_task, pattern="^view_task:"))
    application.add_handler(CallbackQueryHandler(check_task, pattern="^check_task:"))
    application.add_handler(CallbackQueryHandler(about, pattern="^about$"))
    application.add_handler(CallbackQueryHandler(back_to_main, pattern="^back_to_main$"))
    
    # Админ обработчики
    application.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    application.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    application.add_handler(CallbackQueryHandler(admin_fragment_balance, pattern="^admin_fragment_balance$"))
    application.add_handler(CallbackQueryHandler(admin_give_stars, pattern="^admin_give_stars$"))
    application.add_handler(CallbackQueryHandler(admin_give_premium, pattern="^admin_give_premium$"))
    application.add_handler(CallbackQueryHandler(admin_mailing, pattern="^admin_mailing$"))
    application.add_handler(CallbackQueryHandler(admin_blacklist_menu, pattern="^admin_blacklist$"))
    application.add_handler(CallbackQueryHandler(admin_promocodes_menu, pattern="^admin_promocodes$"))
    application.add_handler(CallbackQueryHandler(admin_create_promo, pattern="^admin_create_promo$"))
    application.add_handler(CallbackQueryHandler(admin_tasks_menu, pattern="^admin_tasks$"))
    application.add_handler(CallbackQueryHandler(admin_create_task, pattern="^admin_create_task$"))
    application.add_handler(CallbackQueryHandler(admin_users, pattern="^admin_users$"))
    
    # Текстовые сообщения
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_promo_text))
    application.add_handler(MessageHandler(filters.TEXT & filters.COMMAND, handle_admin_text))
    
    # Запуск вебхук сервера в отдельном потоке
    webhook_thread = threading.Thread(target=run_webhook_server, daemon=True)
    webhook_thread.start()
    logger.info(f"🌐 Webhook server started on port {WEBHOOK_PORT}")
    
    # Запуск бота
    logger.info("🚀 Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # Проверка наличия токена
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ ОШИБКА: Укажите BOT_TOKEN в коде!")
        print("Получите токен у @BotFather")
        sys.exit(1)
    
    # Проверка Fragment настроек
    if FRAGMENT_MNEMONIC == "your_24_word_seed_phrase_here":
        print("⚠️ ВНИМАНИЕ: Не указана сид-фраза Fragment!")
        print("Бот будет работать, но отправка звезд/Premium через Fragment будет недоступна")
    
    main()
