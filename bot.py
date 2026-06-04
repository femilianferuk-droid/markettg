import os
import re
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
)
from telethon.sessions import StringSession

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode

load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [7973988177]

API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"

logging.basicConfig(level=logging.INFO)

# ==================== PREMIUM EMOJI IDS ====================
EMOJI = {
    "profile": "5870994129244131212",
    "wallet": "5769126056262898415",
    "money": "5904462880941545555",
    "sell": "5890848474563352982",
    "buy": "5879814368572478751",
    "star": "5373141891321699086",
    "check": "5870633910337015697",
    "cross": "5870657884844462243",
    "lock": "6037249452824072506",
    "globe": "6042011682497106307",
    "box": "5884479287171485878",
    "gift": "6032644646587338669",
    "clock": "5983150113483134607",
    "send": "5963103826075456248",
    "download": "6039802767931481871",
    "info": "6028435952299413210",
    "bot": "6030400221232501136",
    "tag": "5886285355279193209",
    "trash": "5870875489362513438",
    "edit": "5870676941614354370",
    "phone": "5870528606328852614",
    "people": "5870772616305839506",
    "filter": "5870930636742595124",
    "stats": "5870921681735781843",
    "frozen": "6037249452824072506",
}

# Коды стран
COUNTRY_CODES = {
    '7': 'Россия', '380': 'Украина', '375': 'Беларусь', '1': 'USA',
    '44': 'UK', '49': 'Германия', '33': 'Франция', '39': 'Италия',
    '34': 'Испания', '31': 'Нидерланды', '48': 'Польша', '90': 'Турция',
    '52': 'Мексика', '55': 'Бразилия', '91': 'Индия', '86': 'Китай',
    '81': 'Япония', '82': 'Корея', '234': 'Нигерия', '20': 'Египет',
}

def get_country_from_phone(phone: str) -> str:
    phone = phone.strip().lstrip('+')
    for code in sorted(COUNTRY_CODES.keys(), key=len, reverse=True):
        if phone.startswith(code):
            return COUNTRY_CODES[code]
    return "Неизвестно"

# ==================== БАЗА ДАННЫХ ====================
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

def init_db():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        username TEXT,
        balance INTEGER DEFAULT 0,
        frozen_balance INTEGER DEFAULT 0,
        rating FLOAT DEFAULT 0.0,
        total_reviews INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE TABLE IF NOT EXISTS accounts (
        id SERIAL PRIMARY KEY,
        seller_id BIGINT NOT NULL,
        title TEXT NOT NULL DEFAULT 'Аккаунт',
        phone TEXT NOT NULL,
        password_2fa TEXT,
        session_string TEXT,
        country TEXT NOT NULL,
        description TEXT,
        price INTEGER NOT NULL,
        status TEXT DEFAULT 'active',
        is_valid BOOLEAN DEFAULT TRUE,
        auto_username TEXT,
        auto_firstname TEXT,
        auto_lastname TEXT,
        auto_2fa BOOLEAN DEFAULT FALSE,
        buyer_id BIGINT,
        sold_at TIMESTAMP,
        hold_until TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE TABLE IF NOT EXISTS purchases (
        id SERIAL PRIMARY KEY,
        buyer_id BIGINT NOT NULL,
        account_id INTEGER NOT NULL,
        purchased_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE TABLE IF NOT EXISTS reviews (
        id SERIAL PRIMARY KEY,
        purchase_id INTEGER NOT NULL,
        rating INTEGER CHECK (rating >= 1 AND rating <= 5),
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE TABLE IF NOT EXISTS transactions (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        type TEXT NOT NULL,
        amount INTEGER NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    
    # Миграции
    try:
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS title TEXT NOT NULL DEFAULT 'Аккаунт'")
    except:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS frozen_balance INTEGER DEFAULT 0")
    except:
        pass
    try:
        cur.execute("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS hold_until TIMESTAMP")
    except:
        pass

"""
users: 0=id, 1=telegram_id, 2=username, 3=balance, 4=frozen_balance, 5=rating, 6=total_reviews, 7=created_at
accounts: 0=id, 1=seller_id, 2=title, 3=phone, 4=password_2fa, 5=session_string, 6=country, 7=description, 8=price, 9=status, 10=is_valid, 11=auto_username, 12=auto_firstname, 13=auto_lastname, 14=auto_2fa, 15=buyer_id, 16=sold_at, 17=hold_until, 18=created_at
purchases: 0=id, 1=buyer_id, 2=account_id, 3=purchased_at
reviews: 0=id, 1=purchase_id, 2=rating, 3=created_at
transactions: 0=id, 1=user_id, 2=type, 3=amount, 4=description, 5=created_at
"""

def get_user(telegram_id: int):
    cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    return cur.fetchone()

def create_user(telegram_id: int, username: str = None):
    cur.execute(
        "INSERT INTO users (telegram_id, username) VALUES (%s, %s) ON CONFLICT (telegram_id) DO NOTHING",
        (telegram_id, username)
    )

def update_balance(telegram_id: int, amount: int):
    cur.execute(
        "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
        (amount, telegram_id)
    )

def freeze_balance(telegram_id: int, amount: int):
    cur.execute(
        "UPDATE users SET balance = balance - %s, frozen_balance = frozen_balance + %s WHERE telegram_id = %s",
        (amount, amount, telegram_id)
    )

def unfreeze_balance(telegram_id: int, amount: int):
    cur.execute(
        "UPDATE users SET frozen_balance = frozen_balance - %s, balance = balance + %s WHERE telegram_id = %s",
        (amount, amount, telegram_id)
    )

def release_hold_for_seller(telegram_id: int, amount: int):
    cur.execute(
        "UPDATE users SET frozen_balance = frozen_balance - %s, balance = balance + %s WHERE telegram_id = %s",
        (amount, amount, telegram_id)
    )

def process_expired_holds():
    cur.execute("""
        SELECT a.id, a.seller_id, a.price, a.hold_until
        FROM accounts a
        WHERE a.status = 'sold' 
        AND a.hold_until IS NOT NULL 
        AND a.hold_until <= NOW()
    """)
    expired = cur.fetchall()
    
    for acc in expired:
        try:
            release_hold_for_seller(acc[1], acc[2])
            add_transaction(acc[1], "sale_released", acc[2], f"Средства разморожены за аккаунт #{acc[0]}")
            cur.execute("UPDATE accounts SET hold_until = NULL WHERE id = %s", (acc[0],))
            try:
                asyncio.ensure_future(
                    bot.send_message(
                        acc[1],
                        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Средства за аккаунт #{acc[0]} разморожены!\n"
                        f"На баланс зачислено: {acc[2]} ⭐"
                    )
                )
            except:
                pass
        except Exception as e:
            logging.error(f"Error releasing hold for account {acc[0]}: {e}")

def add_transaction(user_id: int, t_type: str, amount: int, description: str = None):
    cur.execute(
        "INSERT INTO transactions (user_id, type, amount, description) VALUES (%s, %s, %s, %s)",
        (user_id, t_type, amount, description)
    )

def add_account(seller_id: int, title: str, phone: str, password_2fa: str, session_string: str,
                country: str, description: str, price: int, auto_username: str = None,
                auto_firstname: str = None, auto_lastname: str = None, auto_2fa: bool = False):
    cur.execute("""
        INSERT INTO accounts (seller_id, title, phone, password_2fa, session_string, country,
        description, price, status, is_valid, auto_username, auto_firstname, auto_lastname, auto_2fa)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', TRUE, %s, %s, %s, %s)
        RETURNING id
    """, (seller_id, title, phone, password_2fa, session_string, country, description, price,
          auto_username, auto_firstname, auto_lastname, auto_2fa))
    return cur.fetchone()[0]

def get_available_accounts(country_filter: str = None, price_from: int = None, 
                           price_to: int = None, has_2fa: bool = None):
    query = """
        SELECT a.id, a.seller_id, a.title, a.phone, a.password_2fa, a.session_string, 
               a.country, a.description, a.price, a.status, a.is_valid, 
               a.auto_username, a.auto_firstname, a.auto_lastname, a.auto_2fa,
               a.buyer_id, a.sold_at, a.hold_until, a.created_at,
               u.rating as seller_rating
        FROM accounts a
        JOIN users u ON a.seller_id = u.telegram_id
        WHERE a.status = 'active' AND a.is_valid = TRUE
    """
    params = []
    
    if country_filter:
        query += " AND a.country = %s"
        params.append(country_filter)
    if price_from is not None:
        query += " AND a.price >= %s"
        params.append(price_from)
    if price_to is not None:
        query += " AND a.price <= %s"
        params.append(price_to)
    if has_2fa is not None:
        query += " AND a.auto_2fa = %s"
        params.append(has_2fa)
    
    query += " ORDER BY a.created_at DESC"
    cur.execute(query, params)
    return cur.fetchall()

def get_account(account_id: int):
    cur.execute("SELECT * FROM accounts WHERE id = %s", (account_id,))
    return cur.fetchone()

def buy_account(account_id: int, buyer_id: int):
    hold_until = datetime.now() + timedelta(days=1)
    cur.execute(
        "UPDATE accounts SET status = 'sold', buyer_id = %s, sold_at = NOW(), hold_until = %s WHERE id = %s AND status = 'active'",
        (buyer_id, hold_until, account_id)
    )
    if cur.rowcount > 0:
        cur.execute(
            "INSERT INTO purchases (buyer_id, account_id) VALUES (%s, %s) RETURNING id",
            (buyer_id, account_id)
        )
        return cur.fetchone()[0]
    return None

def get_purchases(buyer_id: int):
    cur.execute("""
        SELECT p.id, p.buyer_id, p.account_id, p.purchased_at,
               a.phone, a.password_2fa, a.session_string, a.country, a.description,
               a.title, a.auto_username, a.auto_firstname, a.auto_lastname, a.auto_2fa
        FROM purchases p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.buyer_id = %s
        ORDER BY p.purchased_at DESC
    """, (buyer_id,))
    return cur.fetchall()

def get_purchase(purchase_id: int):
    cur.execute("""
        SELECT p.id, p.buyer_id, p.account_id, p.purchased_at,
               a.phone, a.password_2fa, a.session_string, a.country, a.description,
               a.title, a.auto_username, a.auto_firstname, a.auto_lastname, a.auto_2fa
        FROM purchases p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.id = %s
    """, (purchase_id,))
    return cur.fetchone()

def add_review(purchase_id: int, rating: int):
    cur.execute(
        "INSERT INTO reviews (purchase_id, rating) VALUES (%s, %s)",
        (purchase_id, rating)
    )
    cur.execute("""
        UPDATE users 
        SET total_reviews = COALESCE(total_reviews, 0) + 1,
            rating = CASE 
                WHEN COALESCE(total_reviews, 0) = 0 THEN %s
                ELSE (rating * COALESCE(total_reviews, 0) + %s) / (COALESCE(total_reviews, 0) + 1)
            END
        WHERE telegram_id = (
            SELECT a.seller_id FROM accounts a
            JOIN purchases p ON a.id = p.account_id
            WHERE p.id = %s
        )
    """, (rating, rating, purchase_id))

def has_review(purchase_id: int):
    cur.execute("SELECT id FROM reviews WHERE purchase_id = %s", (purchase_id,))
    return cur.fetchone() is not None

def get_seller_accounts(seller_id: int):
    cur.execute("""
        SELECT * FROM accounts
        WHERE seller_id = %s AND status = 'active'
        ORDER BY created_at DESC
    """, (seller_id,))
    return cur.fetchall()

def get_seller_stats(seller_id: int):
    cur.execute("SELECT COUNT(*) FROM accounts WHERE seller_id = %s AND status = 'sold'", (seller_id,))
    total_sold = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM accounts WHERE seller_id = %s AND status = 'active'", (seller_id,))
    active = cur.fetchone()[0]
    return {"total_sold": total_sold, "active": active}

def get_seller_reviews(seller_id: int):
    cur.execute("""
        SELECT r.rating, r.created_at, p.buyer_id
        FROM reviews r
        JOIN purchases p ON r.purchase_id = p.id
        JOIN accounts a ON p.account_id = a.id
        WHERE a.seller_id = %s
        ORDER BY r.created_at DESC
        LIMIT 10
    """, (seller_id,))
    return cur.fetchall()

def remove_account(account_id: int, seller_id: int):
    cur.execute(
        "UPDATE accounts SET status = 'removed' WHERE id = %s AND seller_id = %s",
        (account_id, seller_id)
    )

# ==================== BOT & DISPATCHER ====================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ==================== TELEPHON CLIENT FACTORY ====================
async def create_telethon_client(session_string: str = None):
    if session_string:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    else:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
    return client

async def verify_account(session_string: str = None, phone: str = None) -> dict:
    client = await create_telethon_client(session_string)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            if not session_string:
                sent = await client.send_code_request(phone)
                session_string = client.session.save()
                await client.disconnect()
                return {
                    "valid": True,
                    "need_code": True,
                    "session_string": session_string,
                    "phone_code_hash": sent.phone_code_hash,
                    "error": None,
                    "user_info": None
                }
            else:
                await client.disconnect()
                return {"valid": False, "need_code": False, "session_string": None, "error": "Сессия не авторизована", "user_info": None}
        
        me = await client.get_me()
        user_info = {
            "username": me.username,
            "first_name": me.first_name,
            "last_name": me.last_name,
            "has_2fa": False
        }
        session_string = client.session.save()
        await client.disconnect()
        return {"valid": True, "need_code": False, "session_string": session_string, "error": None, "user_info": user_info}
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        return {"valid": False, "need_code": False, "session_string": None, "error": str(e), "user_info": None}

async def sign_in_with_code(session_string: str, phone: str, code: str, phone_code_hash: str) -> dict:
    client = await create_telethon_client(session_string)
    try:
        await client.connect()
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        session_string = client.session.save()
        await client.disconnect()
        return {
            "success": True,
            "session_string": session_string,
            "need_2fa": False,
            "user_info": {
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "has_2fa": False
            }
        }
    except SessionPasswordNeededError:
        await client.disconnect()
        return {"success": True, "session_string": session_string, "need_2fa": True, "user_info": None}
    except PhoneCodeInvalidError:
        await client.disconnect()
        return {"success": False, "error": "Неверный код"}
    except PhoneCodeExpiredError:
        await client.disconnect()
        return {"success": False, "error": "Код истёк"}
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        return {"success": False, "error": str(e)}

async def sign_in_with_2fa(session_string: str, password: str) -> dict:
    client = await create_telethon_client(session_string)
    try:
        await client.connect()
        await client.sign_in(password=password)
        me = await client.get_me()
        session_string = client.session.save()
        await client.disconnect()
        return {
            "success": True,
            "session_string": session_string,
            "user_info": {
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "has_2fa": True
            }
        }
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        return {"success": False, "error": str(e)}

async def get_code_from_chat(session_string: str) -> str:
    client = await create_telethon_client(session_string)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return None

        dialogs = await client.get_dialogs(limit=10)
        
        for dialog in dialogs:
            if dialog.is_channel or dialog.is_group:
                continue
            
            messages = await client.get_messages(dialog.entity, limit=5)
            for msg in messages:
                if msg.message:
                    codes = re.findall(r'\b\d{5}\b', msg.message)
                    if codes:
                        await client.disconnect()
                        return codes[0]
        
        await client.disconnect()
        return None
    except:
        try:
            await client.disconnect()
        except:
            pass
        return None

# ==================== СОСТОЯНИЯ FSM ====================
class SellAccount(StatesGroup):
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_price = State()

class BuyAccount(StatesGroup):
    waiting_for_code = State()

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

class FilterStates(StatesGroup):
    waiting_for_country = State()
    waiting_for_price_from = State()
    waiting_for_price_to = State()

# ==================== КЛАВИАТУРЫ ====================
def main_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Продать аккаунт",
            callback_data="sell_account",
            icon_custom_emoji_id=EMOJI["sell"]
        )],
        [InlineKeyboardButton(
            text="Купить аккаунт",
            callback_data="buy_account",
            icon_custom_emoji_id=EMOJI["buy"]
        )],
        [InlineKeyboardButton(
            text="Профиль",
            callback_data="profile",
            icon_custom_emoji_id=EMOJI["profile"]
        )],
    ])

def profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Пополнить баланс",
            callback_data="add_balance",
            icon_custom_emoji_id=EMOJI["star"]
        )],
        [InlineKeyboardButton(
            text="Мои покупки",
            callback_data="my_purchases",
            icon_custom_emoji_id=EMOJI["box"]
        )],
        [InlineKeyboardButton(
            text="Мои объявления",
            callback_data="my_listings",
            icon_custom_emoji_id=EMOJI["tag"]
        )],
        [InlineKeyboardButton(
            text="Вывод средств",
            url="https://t.me/VestMarketSupport",
            icon_custom_emoji_id=EMOJI["money"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main"
        )],
    ])

def back_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main"
        )]
    ])

def account_list_keyboard(accounts):
    buttons = []
    for acc in accounts:
        # acc[0]=id, acc[2]=title, acc[8]=price
        buttons.append([InlineKeyboardButton(
            text=f"{acc[2]} | {acc[8]}⭐",
            callback_data=f"view_acc_{acc[0]}",
            icon_custom_emoji_id=EMOJI["globe"]
        )])
    buttons.append([InlineKeyboardButton(
        text="Фильтры",
        callback_data="filters",
        icon_custom_emoji_id=EMOJI["filter"]
    )])
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data="back_to_main"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def account_view_keyboard(account_id: int, seller_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Купить",
            callback_data=f"buy_{account_id}",
            icon_custom_emoji_id=EMOJI["buy"]
        )],
        [InlineKeyboardButton(
            text="Профиль продавца",
            callback_data=f"seller_{seller_id}",
            icon_custom_emoji_id=EMOJI["people"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_list"
        )],
    ])

def seller_profile_keyboard(seller_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Аккаунты продавца",
            callback_data=f"seller_accs_{seller_id}",
            icon_custom_emoji_id=EMOJI["box"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_list"
        )],
    ])

def filter_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="По стране",
            callback_data="filter_country",
            icon_custom_emoji_id=EMOJI["globe"]
        )],
        [InlineKeyboardButton(
            text="По цене (от)",
            callback_data="filter_price_from",
            icon_custom_emoji_id=EMOJI["money"]
        )],
        [InlineKeyboardButton(
            text="По цене (до)",
            callback_data="filter_price_to",
            icon_custom_emoji_id=EMOJI["money"]
        )],
        [InlineKeyboardButton(
            text="С 2FA",
            callback_data="filter_2fa_yes",
            icon_custom_emoji_id=EMOJI["lock"]
        )],
        [InlineKeyboardButton(
            text="Без 2FA",
            callback_data="filter_2fa_no",
            icon_custom_emoji_id=EMOJI["check"]
        )],
        [InlineKeyboardButton(
            text="Сбросить фильтры",
            callback_data="filter_reset"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_list"
        )],
    ])

def purchase_keyboard(purchase_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Получить код",
            callback_data=f"get_code_{purchase_id}",
            icon_custom_emoji_id=EMOJI["download"]
        )],
        [InlineKeyboardButton(
            text="Оставить отзыв",
            callback_data=f"review_{purchase_id}",
            icon_custom_emoji_id=EMOJI["edit"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_profile"
        )],
    ])

def review_keyboard(purchase_id: int):
    buttons = []
    row = []
    for i in range(1, 6):
        row.append(InlineKeyboardButton(
            text=str(i),
            callback_data=f"rate_{purchase_id}_{i}",
            icon_custom_emoji_id=EMOJI["star"]
        ))
    buttons.append(row)
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data=f"purchase_{purchase_id}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def my_listings_keyboard(accounts):
    buttons = []
    for acc in accounts:
        # acc[0]=id, acc[2]=title, acc[8]=price
        buttons.append([InlineKeyboardButton(
            text=f"{acc[2]} | {acc[8]}⭐",
            callback_data=f"listing_{acc[0]}",
            icon_custom_emoji_id=EMOJI["tag"]
        )])
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data="back_to_profile"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def listing_actions_keyboard(account_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Снять с продажи",
            callback_data=f"remove_{account_id}",
            icon_custom_emoji_id=EMOJI["trash"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="my_listings"
        )],
    ])

def admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Изменить баланс",
            callback_data="admin_change_balance",
            icon_custom_emoji_id=EMOJI["wallet"]
        )],
        [InlineKeyboardButton(
            text="Статистика",
            callback_data="admin_stats",
            icon_custom_emoji_id=EMOJI["stats"]
        )],
    ])

# Глобальный словарь для хранения фильтров
user_filters = {}

# ==================== ФОНОВАЯ ПРОВЕРКА ХОЛДОВ ====================
async def hold_checker():
    while True:
        try:
            process_expired_holds()
        except Exception as e:
            logging.error(f"Hold checker error: {e}")
        await asyncio.sleep(60)

# ==================== ХЕНДЛЕРЫ ====================
@router.message(Command("start"))
async def cmd_start(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username)
    
    user_filters[message.from_user.id] = {}
    
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['bot']}\">🤖</tg-emoji> Добро пожаловать в маркетплейс Telegram аккаунтов!\n"
        f"Здесь вы можете купить или продать аккаунт.",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['bot']}\">🤖</tg-emoji> Добро пожаловать в маркетплейс Telegram аккаунтов!\n"
        f"Здесь вы можете купить или продать аккаунт.",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "profile")
async def profile(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        create_user(callback.from_user.id, callback.from_user.username)
        user = get_user(callback.from_user.id)
    
    # user: 0=id, 1=telegram_id, 2=username, 3=balance, 4=frozen_balance, 5=rating, 6=total_reviews, 7=created_at
    rating_text = f"⭐ {user[5]:.1f}" if user[6] > 0 else "Нет оценок"
    frozen_text = f"\n<tg-emoji emoji-id=\"{EMOJI['frozen']}\">🔒</tg-emoji> Заморожено: {user[4]} ⭐" if user[4] > 0 else ""
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['profile']}\">👤</tg-emoji> <b>Профиль</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['wallet']}\">👛</tg-emoji> Баланс: {user[3]} ⭐"
        f"{frozen_text}\n"
        f"{rating_text} ({user[6]} отзывов)",
        reply_markup=profile_keyboard()
    )

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    # user: 0=id, 1=telegram_id, 2=username, 3=balance, 4=frozen_balance, 5=rating, 6=total_reviews, 7=created_at
    rating_text = f"⭐ {user[5]:.1f}" if user[6] > 0 else "Нет оценок"
    frozen_text = f"\n<tg-emoji emoji-id=\"{EMOJI['frozen']}\">🔒</tg-emoji> Заморожено: {user[4]} ⭐" if user[4] > 0 else ""
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['profile']}\">👤</tg-emoji> <b>Профиль</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['wallet']}\">👛</tg-emoji> Баланс: {user[3]} ⭐"
        f"{frozen_text}\n"
        f"{rating_text} ({user[6]} отзывов)",
        reply_markup=profile_keyboard()
    )

# ==================== ПРОДАЖА АККАУНТА ====================
@router.callback_query(F.data == "sell_account")
async def sell_account_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['sell']}\">📤</tg-emoji> Введите номер телефона аккаунта "
        f"в международном формате (например, +79991234567):",
        reply_markup=back_keyboard()
    )
    await state.set_state(SellAccount.waiting_for_phone)

@router.message(StateFilter(SellAccount.waiting_for_phone))
async def sell_account_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    
    if not re.match(r'^\+\d{7,15}$', phone):
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Неверный формат. "
            f"Используйте международный формат, например +79991234567"
        )
        return
    
    await state.update_data(phone=phone)
    
    status_msg = await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['clock']}\">⏰</tg-emoji> Проверяю аккаунт..."
    )
    
    result = await verify_account(phone=phone)
    
    if result["need_code"]:
        await state.update_data(
            session_string=result["session_string"],
            phone_code_hash=result["phone_code_hash"]
        )
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['send']}\">⬆</tg-emoji> Введите код подтверждения, "
            f"отправленный в Telegram (действителен 2 минуты):"
        )
        await state.set_state(SellAccount.waiting_for_code)
    elif result["valid"]:
        await state.update_data(session_string=result["session_string"])
        country = get_country_from_phone(phone)
        await state.update_data(country=country)
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Аккаунт валиден!\n"
            f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна определена: <b>{country}</b>\n\n"
            f"Введите название объявления:"
        )
        await state.set_state(SellAccount.waiting_for_title)
    else:
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Ошибка: {result['error']}",
            reply_markup=back_keyboard()
        )
        await state.clear()

@router.message(StateFilter(SellAccount.waiting_for_code))
async def sell_account_code(message: Message, state: FSMContext):
    code = message.text.strip()
    data = await state.get_data()
    
    status_msg = await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['clock']}\">⏰</tg-emoji> Проверяю код..."
    )
    
    result = await sign_in_with_code(
        data["session_string"],
        data["phone"],
        code,
        data["phone_code_hash"]
    )
    
    if result["success"] and result["need_2fa"]:
        await state.update_data(session_string=result["session_string"])
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['lock']}\">🔒</tg-emoji> Введите пароль 2FA (если нет — напишите 'нет'):"
        )
        await state.set_state(SellAccount.waiting_for_2fa)
    elif result["success"]:
        country = get_country_from_phone(data["phone"])
        await state.update_data(
            session_string=result["session_string"],
            country=country,
            auto_username=result["user_info"]["username"],
            auto_firstname=result["user_info"]["first_name"],
            auto_lastname=result["user_info"]["last_name"],
            auto_2fa=False
        )
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Аккаунт подтверждён!\n"
            f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна: <b>{country}</b>\n\n"
            f"Введите название объявления:"
        )
        await state.set_state(SellAccount.waiting_for_title)
    else:
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Ошибка: {result['error']}",
            reply_markup=back_keyboard()
        )
        await state.clear()

@router.message(StateFilter(SellAccount.waiting_for_2fa))
async def sell_account_2fa(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    
    if password.lower() == 'нет':
        password = None
    
    if password:
        status_msg = await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['clock']}\">⏰</tg-emoji> Проверяю 2FA..."
        )
        result = await sign_in_with_2fa(data["session_string"], password)
    else:
        result = {"success": True, "session_string": data["session_string"], 
                  "user_info": {"username": None, "first_name": None, "last_name": None, "has_2fa": False}}
        status_msg = await message.answer("...")
    
    if result["success"]:
        country = get_country_from_phone(data["phone"])
        await state.update_data(
            session_string=result["session_string"],
            country=country,
            auto_username=result["user_info"]["username"],
            auto_firstname=result["user_info"]["first_name"],
            auto_lastname=result["user_info"]["last_name"],
            auto_2fa=result["user_info"]["has_2fa"],
            password_2fa=password
        )
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Аккаунт подтверждён!\n"
            f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна: <b>{country}</b>\n\n"
            f"Введите название объявления:"
        )
        await state.set_state(SellAccount.waiting_for_title)
    else:
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Ошибка: {result['error']}",
            reply_markup=back_keyboard()
        )
        await state.clear()

@router.message(StateFilter(SellAccount.waiting_for_title))
async def sell_account_title(message: Message, state: FSMContext):
    title = message.text.strip()
    if len(title) > 50:
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Название не должно превышать 50 символов."
        )
        return
    
    await state.update_data(title=title)
    
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['edit']}\">🖋</tg-emoji> Введите описание аккаунта (до 100 слов):"
    )
    await state.set_state(SellAccount.waiting_for_description)

@router.message(StateFilter(SellAccount.waiting_for_description))
async def sell_account_description(message: Message, state: FSMContext):
    description = message.text.strip()
    words = description.split()
    
    if len(words) > 100:
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Описание не должно превышать 100 слов. "
            f"У вас {len(words)} слов."
        )
        return
    
    await state.update_data(description=description)
    
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['money']}\">🪙</tg-emoji> Введите цену аккаунта в звёздах:"
    )
    await state.set_state(SellAccount.waiting_for_price)

@router.message(StateFilter(SellAccount.waiting_for_price))
async def sell_account_price(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
        if price < 1:
            raise ValueError
    except:
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Введите целое число больше 0"
        )
        return
    
    data = await state.get_data()
    
    auto_desc = f"\n\n<b>Характеристики:</b>"
    if data.get("auto_username"):
        auto_desc += f"\n• @{data['auto_username']}"
    if data.get("auto_firstname"):
        auto_desc += f"\n• Имя: {data['auto_firstname']}"
    if data.get("auto_lastname"):
        auto_desc += f"\n• Фамилия: {data['auto_lastname']}"
    auto_desc += f"\n• 2FA: {'Есть' if data.get('auto_2fa') else 'Нет'}"
    
    full_description = data["description"] + auto_desc
    
    account_id = add_account(
        seller_id=message.from_user.id,
        title=data["title"],
        phone=data["phone"],
        password_2fa=data.get("password_2fa"),
        session_string=data["session_string"],
        country=data["country"],
        description=full_description,
        price=price,
        auto_username=data.get("auto_username"),
        auto_firstname=data.get("auto_firstname"),
        auto_lastname=data.get("auto_lastname"),
        auto_2fa=data.get("auto_2fa", False)
    )
    
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Аккаунт успешно выставлен на продажу!\n"
        f"<tg-emoji emoji-id=\"{EMOJI['tag']}\">🏷</tg-emoji> Название: {data['title']}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['money']}\">🪙</tg-emoji> Цена: {price} ⭐\n"
        f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна: {data['country']}",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()

# ==================== ПОКУПКА АККАУНТА ====================
@router.callback_query(F.data == "buy_account")
async def buy_account_list(callback: CallbackQuery):
    await show_accounts(callback)

async def show_accounts(callback: CallbackQuery, filters: dict = None):
    if filters is None:
        filters = user_filters.get(callback.from_user.id, {})
    
    accounts = get_available_accounts(
        country_filter=filters.get("country"),
        price_from=filters.get("price_from"),
        price_to=filters.get("price_to"),
        has_2fa=filters.get("has_2fa")
    )
    
    if not accounts:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> Нет доступных аккаунтов.\n"
            f"Попробуйте сбросить фильтры.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Фильтры",
                    callback_data="filters",
                    icon_custom_emoji_id=EMOJI["filter"]
                )],
                [InlineKeyboardButton(
                    text="Назад",
                    callback_data="back_to_main"
                )],
            ])
        )
        return
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['buy']}\">🏧</tg-emoji> <b>Доступные аккаунты:</b>",
        reply_markup=account_list_keyboard(accounts)
    )

@router.callback_query(F.data == "back_to_list")
async def back_to_list(callback: CallbackQuery):
    await show_accounts(callback)

@router.callback_query(F.data.startswith("view_acc_"))
async def view_account(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    account = get_account(account_id)
    
    # account: 0=id, 1=seller_id, 2=title, 3=phone, 4=password_2fa, 5=session_string, 6=country, 7=description, 8=price, 9=status, 10=is_valid
    if not account or account[9] != "active":
        await callback.answer("Аккаунт уже не доступен", show_alert=True)
        await show_accounts(callback)
        return
    
    seller = get_user(account[1])
    
    text = (
        f"<tg-emoji emoji-id=\"{EMOJI['tag']}\">🏷</tg-emoji> <b>{account[2]}</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна: {account[6]}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['money']}\">🪙</tg-emoji> Цена: {account[8]} ⭐\n"
        f"<tg-emoji emoji-id=\"{EMOJI['people']}\">👥</tg-emoji> Продавец: {seller[2] or 'Без username'}"
    )
    
    if seller[6] > 0:
        text += f"\n⭐ Рейтинг: {seller[5]:.1f} ({seller[6]} отзывов)"
    
    text += f"\n\n<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> {account[7] or 'Нет описания'}"
    
    await callback.message.edit_text(
        text,
        reply_markup=account_view_keyboard(account_id, account[1])
    )

@router.callback_query(F.data.startswith("buy_"))
async def buy_account_confirm(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    account = get_account(account_id)
    
    # account: 9=status
    if not account or account[9] != "active":
        await callback.answer("Аккаунт уже не доступен", show_alert=True)
        await show_accounts(callback)
        return
    
    buyer = get_user(callback.from_user.id)
    seller = get_user(account[1])
    
    if buyer[0] == account[1]:
        await callback.answer("Нельзя купить свой аккаунт", show_alert=True)
        return
    
    # buyer[3]=balance, account[8]=price
    if buyer[3] < account[8]:
        await callback.answer(
            f"Недостаточно средств! Ваш баланс: {buyer[3]} ⭐, нужно: {account[8]} ⭐",
            show_alert=True
        )
        return
    
    await callback.answer("Проверяю актуальность аккаунта...")
    
    # account[5]=session_string
    result = await verify_account(session_string=account[5])
    
    if not result["valid"]:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Аккаунт больше не валиден.",
            reply_markup=back_keyboard()
        )
        return
    
    update_balance(callback.from_user.id, -account[8])
    freeze_balance(account[1], account[8])
    
    add_transaction(callback.from_user.id, "purchase", -account[8], f"Покупка аккаунта #{account_id}")
    add_transaction(account[1], "sale_frozen", account[8], f"Продажа аккаунта #{account_id} (заморожено на 24ч)")
    
    purchase_id = buy_account(account_id, callback.from_user.id)
    
    if not purchase_id:
        await callback.answer("Ошибка при покупке", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Вы успешно купили аккаунт!\n"
        f"Списано: {account[8]} ⭐",
        reply_markup=back_keyboard()
    )
    
    try:
        await bot.send_message(
            account[1],
            f"<tg-emoji emoji-id=\"{EMOJI['gift']}\">🎁</tg-emoji> Ваш аккаунт «{account[2]}» был продан!\n"
            f"Сумма: {account[8]} ⭐\n"
            f"<tg-emoji emoji-id=\"{EMOJI['clock']}\">⏰</tg-emoji> Средства будут зачислены через 24 часа."
        )
    except:
        pass

# ==================== ПРОФИЛЬ ПРОДАВЦА ====================
@router.callback_query(F.data.startswith("seller_"))
async def view_seller_profile(callback: CallbackQuery):
    seller_id = int(callback.data.split("_")[1])
    seller = get_user(seller_id)
    
    # seller: 2=username, 5=rating, 6=total_reviews
    if not seller:
        await callback.answer("Продавец не найден", show_alert=True)
        return
    
    stats = get_seller_stats(seller_id)
    reviews = get_seller_reviews(seller_id)
    
    text = (
        f"<tg-emoji emoji-id=\"{EMOJI['people']}\">👥</tg-emoji> <b>Профиль продавца</b>\n\n"
        f"Username: {seller[2] or 'Скрыт'}\n"
    )
    
    if seller[6] > 0:
        text += f"⭐ Рейтинг: {seller[5]:.1f} ({seller[6]} отзывов)"
    else:
        text += "⭐ Рейтинг: Нет оценок"
    
    text += (
        f"\n\n<tg-emoji emoji-id=\"{EMOJI['stats']}\">📊</tg-emoji> <b>Статистика:</b>\n"
        f"• Продано: {stats['total_sold']}\n"
        f"• Активных: {stats['active']}"
    )
    
    if reviews:
        text += f"\n\n<tg-emoji emoji-id=\"{EMOJI['edit']}\">🖋</tg-emoji> <b>Последние отзывы:</b>"
        for rev in reviews[:5]:
            text += f"\n• {rev[0]}⭐ от пользователя {rev[2]}"
    
    await callback.message.edit_text(
        text,
        reply_markup=seller_profile_keyboard(seller_id)
    )

@router.callback_query(F.data.startswith("seller_accs_"))
async def view_seller_accounts(callback: CallbackQuery):
    seller_id = int(callback.data.split("_")[2])
    accounts = get_seller_accounts(seller_id)
    
    if not accounts:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> У продавца нет активных аккаунтов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Назад",
                    callback_data=f"seller_{seller_id}"
                )]
            ])
        )
        return
    
    buttons = []
    for acc in accounts:
        # acc[0]=id, acc[2]=title, acc[8]=price
        buttons.append([InlineKeyboardButton(
            text=f"{acc[2]} | {acc[8]}⭐",
            callback_data=f"view_acc_{acc[0]}",
            icon_custom_emoji_id=EMOJI["globe"]
        )])
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data=f"seller_{seller_id}"
    )])
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['box']}\">📦</tg-emoji> <b>Аккаунты продавца:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

# ==================== ФИЛЬТРЫ ====================
@router.callback_query(F.data == "filters")
async def filters_menu(callback: CallbackQuery):
    f = user_filters.get(callback.from_user.id, {})
    text = (
        f"<tg-emoji emoji-id=\"{EMOJI['filter']}\">📊</tg-emoji> <b>Фильтры:</b>\n\n"
        f"Страна: {f.get('country', 'Все')}\n"
        f"Цена от: {f.get('price_from', 'Нет')}\n"
        f"Цена до: {f.get('price_to', 'Нет')}\n"
        f"2FA: {f.get('has_2fa', 'Не важно')}"
    )
    await callback.message.edit_text(text, reply_markup=filter_keyboard())

@router.callback_query(F.data == "filter_country")
async def filter_country_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Введите страну (или 'все' для сброса):",
        reply_markup=back_keyboard()
    )
    await state.set_state(FilterStates.waiting_for_country)

@router.message(StateFilter(FilterStates.waiting_for_country))
async def filter_country_set(message: Message, state: FSMContext):
    country = message.text.strip()
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {}
    
    if country.lower() == "все":
        user_filters[message.from_user.id].pop("country", None)
    else:
        user_filters[message.from_user.id]["country"] = country
    
    await state.clear()
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Фильтр обновлён!",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "filter_price_from")
async def filter_price_from_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['money']}\">🪙</tg-emoji> Введите минимальную цену (или 0 для сброса):",
        reply_markup=back_keyboard()
    )
    await state.set_state(FilterStates.waiting_for_price_from)

@router.message(StateFilter(FilterStates.waiting_for_price_from))
async def filter_price_from_set(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
    except:
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Введите число"
        )
        return
    
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {}
    
    if price == 0:
        user_filters[message.from_user.id].pop("price_from", None)
    else:
        user_filters[message.from_user.id]["price_from"] = price
    
    await state.clear()
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Фильтр обновлён!",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "filter_price_to")
async def filter_price_to_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['money']}\">🪙</tg-emoji> Введите максимальную цену (или 0 для сброса):",
        reply_markup=back_keyboard()
    )
    await state.set_state(FilterStates.waiting_for_price_to)

@router.message(StateFilter(FilterStates.waiting_for_price_to))
async def filter_price_to_set(message: Message, state: FSMContext):
    try:
        price = int(message.text.strip())
    except:
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Введите число"
        )
        return
    
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {}
    
    if price == 0:
        user_filters[message.from_user.id].pop("price_to", None)
    else:
        user_filters[message.from_user.id]["price_to"] = price
    
    await state.clear()
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Фильтр обновлён!",
        reply_markup=main_menu_keyboard()
    )

@router.callback_query(F.data == "filter_2fa_yes")
async def filter_2fa_yes(callback: CallbackQuery):
    if callback.from_user.id not in user_filters:
        user_filters[callback.from_user.id] = {}
    user_filters[callback.from_user.id]["has_2fa"] = True
    await callback.answer("Фильтр: только с 2FA")
    await filters_menu(callback)

@router.callback_query(F.data == "filter_2fa_no")
async def filter_2fa_no(callback: CallbackQuery):
    if callback.from_user.id not in user_filters:
        user_filters[callback.from_user.id] = {}
    user_filters[callback.from_user.id]["has_2fa"] = False
    await callback.answer("Фильтр: только без 2FA")
    await filters_menu(callback)

@router.callback_query(F.data == "filter_reset")
async def filter_reset(callback: CallbackQuery):
    user_filters[callback.from_user.id] = {}
    await callback.answer("Фильтры сброшены")
    await show_accounts(callback)

# ==================== МОИ ПОКУПКИ ====================
@router.callback_query(F.data == "my_purchases")
async def my_purchases(callback: CallbackQuery):
    purchases = get_purchases(callback.from_user.id)
    
    # purchases columns: 0=id, 1=buyer_id, 2=account_id, 3=purchased_at, 4=phone, 5=password_2fa, 6=session_string, 7=country, 8=description, 9=title, 10=auto_username, 11=auto_firstname, 12=auto_lastname, 13=auto_2fa
    if not purchases:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> У вас пока нет покупок.",
            reply_markup=back_keyboard()
        )
        return
    
    buttons = []
    for p in purchases:
        title = p[9] if len(p) > 9 and p[9] else f"Покупка #{p[0]}"
        buttons.append([InlineKeyboardButton(
            text=title,
            callback_data=f"purchase_{p[0]}",
            icon_custom_emoji_id=EMOJI["box"]
        )])
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data="back_to_profile"
    )])
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['box']}\">📦</tg-emoji> <b>Ваши покупки:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@router.callback_query(F.data.startswith("purchase_"))
async def view_purchase(callback: CallbackQuery):
    purchase_id = int(callback.data.split("_")[1])
    purchase = get_purchase(purchase_id)
    
    # purchase: 0=id, 1=buyer_id, 2=account_id, 3=purchased_at, 4=phone, 5=password_2fa, 6=session_string, 7=country, 8=description, 9=title
    if not purchase or purchase[1] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    text = (
        f"<tg-emoji emoji-id=\"{EMOJI['box']}\">📦</tg-emoji> <b>{purchase[9]}</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна: {purchase[7]}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> Описание: {purchase[8] or 'Нет'}\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['phone']}\">📁</tg-emoji> Номер: <code>{purchase[4]}</code>\n"
    )
    
    if purchase[5]:
        text += f"<tg-emoji emoji-id=\"{EMOJI['lock']}\">🔒</tg-emoji> 2FA: <code>{purchase[5]}</code>\n"
    
    if has_review(purchase_id):
        text += f"\n<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Отзыв оставлен"
    
    await callback.message.edit_text(
        text,
        reply_markup=purchase_keyboard(purchase_id)
    )

@router.callback_query(F.data.startswith("get_code_"))
async def get_purchase_code(callback: CallbackQuery):
    purchase_id = int(callback.data.split("_")[2])
    purchase = get_purchase(purchase_id)
    
    # purchase: 6=session_string
    if not purchase or purchase[1] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    await callback.answer("Получаю код...")
    
    status_msg = await callback.message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['clock']}\">⏰</tg-emoji> Ищу код в чатах..."
    )
    
    code = await get_code_from_chat(purchase[6])
    
    if code:
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Найден код: <code>{code}</code>"
        )
    else:
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Код не найден. "
            f"Попробуйте позже."
        )

@router.callback_query(F.data.startswith("review_"))
async def review_purchase(callback: CallbackQuery):
    purchase_id = int(callback.data.split("_")[1])
    purchase = get_purchase(purchase_id)
    
    if not purchase or purchase[1] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    if has_review(purchase_id):
        await callback.answer("Вы уже оставили отзыв", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['edit']}\">🖋</tg-emoji> Поставьте оценку продавцу:",
        reply_markup=review_keyboard(purchase_id)
    )

@router.callback_query(F.data.startswith("rate_"))
async def submit_review(callback: CallbackQuery):
    parts = callback.data.split("_")
    purchase_id = int(parts[1])
    rating = int(parts[2])
    
    add_review(purchase_id, rating)
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Спасибо за отзыв! Вы поставили {rating} ⭐",
        reply_markup=back_keyboard()
    )

# ==================== МОИ ОБЪЯВЛЕНИЯ ====================
@router.callback_query(F.data == "my_listings")
async def my_listings(callback: CallbackQuery):
    accounts = get_seller_accounts(callback.from_user.id)
    
    if not accounts:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> У вас нет активных объявлений.",
            reply_markup=back_keyboard()
        )
        return
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['tag']}\">🏷</tg-emoji> <b>Ваши объявления:</b>",
        reply_markup=my_listings_keyboard(accounts)
    )

@router.callback_query(F.data.startswith("listing_"))
async def view_listing(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    account = get_account(account_id)
    
    # account: 2=title, 6=country, 8=price, 7=description, 1=seller_id
    if not account or account[1] != callback.from_user.id:
        await callback.answer("Объявление не найдено", show_alert=True)
        return
    
    text = (
        f"<tg-emoji emoji-id=\"{EMOJI['tag']}\">🏷</tg-emoji> <b>{account[2]}</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна: {account[6]}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['money']}\">🪙</tg-emoji> Цена: {account[8]} ⭐\n"
        f"Описание: {account[7] or 'Нет'}"
    )
    
    await callback.message.edit_text(
        text,
        reply_markup=listing_actions_keyboard(account_id)
    )

@router.callback_query(F.data.startswith("remove_"))
async def remove_listing(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    remove_account(account_id, callback.from_user.id)
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Объявление снято с продажи.",
        reply_markup=back_keyboard()
    )

# ==================== ПОПОЛНЕНИЕ БАЛАНСА ====================
@router.callback_query(F.data == "add_balance")
async def add_balance_start(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['star']}\">⭐</tg-emoji> Введите сумму пополнения в звёздах (минимум 1):",
        reply_markup=back_keyboard()
    )
    await state.set_state(BuyAccount.waiting_for_code)

@router.message(StateFilter(BuyAccount.waiting_for_code))
async def process_balance_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount < 1:
            raise ValueError
    except:
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Введите целое число больше 0"
        )
        return
    
    await message.answer_invoice(
        title="Пополнение баланса",
        description=f"Пополнение баланса на {amount} ⭐",
        payload=f"balance_{amount}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{amount} звёзд", amount=amount)],
        provider_token="",
    )
    await state.clear()

@router.pre_checkout_query()
async def pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    
    if payload.startswith("balance_"):
        amount = int(payload.split("_")[1])
        update_balance(message.from_user.id, amount)
        add_transaction(message.from_user.id, "deposit", amount, "Пополнение баланса")
        
        user = get_user(message.from_user.id)
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Баланс пополнен на {amount} ⭐\n"
            f"Текущий баланс: {user[3]} ⭐",
            reply_markup=main_menu_keyboard()
        )

# ==================== АДМИН-ПАНЕЛЬ ====================
@router.message(Command("admin"))
async def admin_panel(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['bot']}\">🤖</tg-emoji> <b>Админ-панель</b>",
        reply_markup=admin_keyboard()
    )

@router.callback_query(F.data == "admin_change_balance")
async def admin_change_balance_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['wallet']}\">👛</tg-emoji> Введите ID пользователя:",
        reply_markup=back_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_user_id)

@router.message(StateFilter(AdminStates.waiting_for_user_id))
async def admin_get_user_id(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        user_id = int(message.text.strip())
    except:
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Введите корректный ID"
        )
        return
    
    user = get_user(user_id)
    if not user:
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Пользователь не найден"
        )
        await state.clear()
        return
    
    # user: 2=username, 3=balance, 4=frozen_balance
    await state.update_data(admin_user_id=user_id)
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['profile']}\">👤</tg-emoji> Пользователь: {user[2] or 'Без username'}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['wallet']}\">👛</tg-emoji> Баланс: {user[3]} ⭐\n"
        f"<tg-emoji emoji-id=\"{EMOJI['frozen']}\">🔒</tg-emoji> Заморожено: {user[4]} ⭐\n\n"
        f"Введите сумму для изменения (положительное — добавить, отрицательное — списать):"
    )
    await state.set_state(AdminStates.waiting_for_amount)

@router.message(StateFilter(AdminStates.waiting_for_amount))
async def admin_change_balance_execute(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        amount = int(message.text.strip())
    except:
        await message.answer(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Введите целое число"
        )
        return
    
    data = await state.get_data()
    user_id = data["admin_user_id"]
    
    update_balance(user_id, amount)
    add_transaction(user_id, "admin", amount, f"Изменение баланса админом {message.from_user.id}")
    
    user = get_user(user_id)
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Баланс изменён!\n"
        f"Новый баланс пользователя {user[2] or user_id}: {user[3]} ⭐",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()

@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Нет доступа", show_alert=True)
        return
    
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM accounts WHERE status = 'active'")
    active_accounts = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM purchases")
    total_purchases = cur.fetchone()[0]
    
    cur.execute("SELECT SUM(amount) FROM transactions WHERE type = 'deposit'")
    total_deposits = cur.fetchone()[0] or 0
    
    cur.execute("SELECT SUM(frozen_balance) FROM users")
    total_frozen = cur.fetchone()[0] or 0
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> <b>Статистика:</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['profile']}\">👤</tg-emoji> Пользователей: {total_users}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['tag']}\">🏷</tg-emoji> Активных объявлений: {active_accounts}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['box']}\">📦</tg-emoji> Всего покупок: {total_purchases}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['money']}\">🪙</tg-emoji> Всего пополнено: {total_deposits} ⭐\n"
        f"<tg-emoji emoji-id=\"{EMOJI['frozen']}\">🔒</tg-emoji> Заморожено: {total_frozen} ⭐",
        reply_markup=back_keyboard()
    )

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    print("База данных инициализирована")
    
    asyncio.create_task(hold_checker())
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
