import os
import re
import asyncio
import logging
import uuid
import io
from datetime import datetime, timedelta
from typing import Optional

from dotenv import load_dotenv
import psycopg2
import aiohttp
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
from aiogram.utils.keyboard import InlineKeyboardBuilder  # ✅ Правильный импорт
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode

# Загрузка переменных окружения
load_dotenv()

# ==================== КОНФИГУРАЦИЯ БОТА ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [7973988177]
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN", "")
SUPPORT_LINK = "https://t.me/VestMarketSupport"
API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"

# Настройки платформы
STARS_RATE = 1  # 1 звезда = 1 рубль
PER_PAGE = 10   # Количество объявлений на странице
PIN_PRICE = 15  # Цена закрепления в рублях
PIN_DURATION = 30  # Длительность закрепления в минутах

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    "settings": "5870982283724328568",
    "pin": "5890937706803894250",
    "resell": "5778672437122045013",
    "crypto": "5260752406890711732",
    "ton": "6030400221232501136",
    "usdt": "5904462880941545555",
    "ban": "5893192487324880883",
    "unban": "5891207662678317861",
    "valid": "6037397706505195857",
    "invalid": "6037243349675544634",
}

def em(name: str) -> str:
    """Генерирует HTML-код для premium-emoji"""
    icons = {
        "profile": "👤", "wallet": "👛", "money": "🪙", "sell": "📤",
        "buy": "🏧", "star": "⭐", "check": "✅", "cross": "❌",
        "lock": "🔒", "globe": "📍", "box": "📦", "gift": "🎁",
        "clock": "⏰", "send": "⬆", "download": "⬇", "info": "ℹ",
        "bot": "🤖", "tag": "🏷", "trash": "🗑", "edit": "🖋",
        "phone": "📁", "people": "👥", "filter": "📊", "stats": "📊",
        "frozen": "🔒", "settings": "⚙", "pin": "📌", "resell": "🔄",
        "crypto": "👾", "ton": "💎", "usdt": "💵",
        "ban": "🚫", "unban": "✅", "valid": "🟢", "invalid": "🔴",
    }
    emoji_id = EMOJI.get(name, "")
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{icons.get(name, "")}</tg-emoji>'
    return ""

# ==================== СТРАНЫ (ВСЕ НА РУССКОМ) ====================
ALLOWED_COUNTRIES = [
    "Россия", "Украина", "Беларусь", "Казахстан", "Узбекистан", "Киргизия",
    "Таджикистан", "Туркменистан", "Армения", "Азербайджан", "Грузия", "Молдова",
    "США", "Великобритания", "Германия", "Франция", "Италия", "Испания",
    "Нидерланды", "Польша", "Турция", "Бразилия", "Индия", "Китай",
    "Япония", "Южная Корея", "Нигерия", "Египет", "ОАЭ", "Израиль",
    "Канада", "Австралия", "Швеция", "Норвегия", "Финляндия", "Румыния",
]

COUNTRY_CODES = {
    '7': 'Россия',
    '380': 'Украина',
    '375': 'Беларусь',
    '77': 'Казахстан',
    '998': 'Узбекистан',
    '996': 'Киргизия',
    '992': 'Таджикистан',
    '993': 'Туркменистан',
    '374': 'Армения',
    '994': 'Азербайджан',
    '995': 'Грузия',
    '373': 'Молдова',
    '1': 'США',
    '44': 'Великобритания',
    '49': 'Германия',
    '33': 'Франция',
    '39': 'Италия',
    '34': 'Испания',
    '31': 'Нидерланды',
    '48': 'Польша',
    '90': 'Турция',
    '55': 'Бразилия',
    '91': 'Индия',
    '86': 'Китай',
    '81': 'Япония',
    '82': 'Южная Корея',
    '234': 'Нигерия',
    '20': 'Египет',
    '971': 'ОАЭ',
    '972': 'Израиль',
    '1': 'Канада',
    '61': 'Австралия',
    '46': 'Швеция',
    '47': 'Норвегия',
    '358': 'Финляндия',
    '40': 'Румыния',
}

SOURCE_TYPES = {
    "autoreg": "Авторег",
    "selfreg": "Саморег",
    "phishing": "Фишинг",
    "stealer": "Стилер",
}

def get_country_from_phone(phone: str) -> Optional[str]:
    """Определяет страну по номеру телефона"""
    phone = phone.strip().lstrip('+')
    for code in sorted(COUNTRY_CODES.keys(), key=len, reverse=True):
        if phone.startswith(code):
            country = COUNTRY_CODES[code]
            if country in ALLOWED_COUNTRIES:
                return country
    return None

# ==================== БАЗА ДАННЫХ POSTGRESQL ====================
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

def init_db():
    """Инициализация базы данных с пересозданием всех таблиц"""
    logger.info("Начинаю инициализацию базы данных...")
    
    # Удаляем таблицы в правильном порядке
    cur.execute("DROP TABLE IF EXISTS crypto_invoices CASCADE")
    cur.execute("DROP TABLE IF EXISTS reviews CASCADE")
    cur.execute("DROP TABLE IF EXISTS transactions CASCADE")
    cur.execute("DROP TABLE IF EXISTS purchases CASCADE")
    cur.execute("DROP TABLE IF EXISTS accounts CASCADE")
    cur.execute("DROP TABLE IF EXISTS users CASCADE")
    
    # Создаём таблицы заново
    cur.execute("""
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        username TEXT,
        balance INTEGER DEFAULT 0,
        frozen_balance INTEGER DEFAULT 0,
        rating FLOAT DEFAULT 0.0,
        total_reviews INTEGER DEFAULT 0,
        is_banned BOOLEAN DEFAULT FALSE,
        ban_reason TEXT,
        banned_until TIMESTAMP,
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE TABLE accounts (
        id SERIAL PRIMARY KEY,
        seller_id BIGINT NOT NULL,
        title TEXT NOT NULL DEFAULT 'Аккаунт',
        phone TEXT NOT NULL,
        password_2fa TEXT,
        session_string TEXT,
        session_file_id TEXT,
        country TEXT NOT NULL,
        description TEXT,
        price INTEGER NOT NULL,
        source_type TEXT DEFAULT 'selfreg',
        status TEXT DEFAULT 'active',
        is_valid BOOLEAN DEFAULT TRUE,
        is_pinned BOOLEAN DEFAULT FALSE,
        pinned_until TIMESTAMP,
        auto_username TEXT,
        auto_firstname TEXT,
        auto_lastname TEXT,
        auto_2fa BOOLEAN DEFAULT FALSE,
        buyer_id BIGINT,
        sold_at TIMESTAMP,
        hold_until TIMESTAMP,
        can_resell BOOLEAN DEFAULT TRUE,
        original_account_id INTEGER,
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE TABLE purchases (
        id SERIAL PRIMARY KEY,
        purchase_uid TEXT UNIQUE NOT NULL,
        buyer_id BIGINT NOT NULL,
        account_id INTEGER NOT NULL,
        purchased_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE TABLE reviews (
        id SERIAL PRIMARY KEY,
        purchase_id INTEGER NOT NULL,
        rating INTEGER CHECK (rating >= 1 AND rating <= 5),
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE TABLE transactions (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        type TEXT NOT NULL,
        amount INTEGER NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE TABLE crypto_invoices (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        invoice_id TEXT UNIQUE NOT NULL,
        amount_rub INTEGER NOT NULL,
        crypto_amount TEXT,
        currency TEXT,
        status TEXT DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE INDEX idx_accounts_status ON accounts(status);
    CREATE INDEX idx_accounts_seller ON accounts(seller_id);
    CREATE INDEX idx_accounts_phone ON accounts(phone);
    CREATE INDEX idx_users_banned ON users(is_banned);
    """)
    
    logger.info("База данных успешно инициализирована")

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С БД ====================

def get_user(telegram_id: int):
    """Получает пользователя по telegram_id"""
    cur.execute("SELECT * FROM users WHERE telegram_id=%s", (telegram_id,))
    return cur.fetchone()

def create_user(telegram_id: int, username: str = None):
    """Создаёт нового пользователя"""
    cur.execute(
        "INSERT INTO users (telegram_id, username) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        (telegram_id, username)
    )

def update_balance(telegram_id: int, amount: int):
    """Обновляет баланс пользователя"""
    cur.execute(
        "UPDATE users SET balance=balance+%s WHERE telegram_id=%s",
        (amount, telegram_id)
    )

def freeze_balance(telegram_id: int, amount: int):
    """Замораживает средства на балансе"""
    cur.execute(
        "UPDATE users SET frozen_balance=frozen_balance+%s WHERE telegram_id=%s",
        (amount, telegram_id)
    )

def release_hold(telegram_id: int, amount: int):
    """Размораживает средства и начисляет на баланс"""
    cur.execute(
        "UPDATE users SET frozen_balance=frozen_balance-%s, balance=balance+%s WHERE telegram_id=%s",
        (amount, amount, telegram_id)
    )

def add_transaction(user_id: int, t_type: str, amount: int, description: str = None):
    """Добавляет запись о транзакции"""
    cur.execute(
        "INSERT INTO transactions (user_id, type, amount, description) VALUES (%s,%s,%s,%s)",
        (user_id, t_type, amount, description)
    )

def is_user_banned(telegram_id: int) -> bool:
    """Проверяет, заблокирован ли пользователь"""
    user = get_user(telegram_id)
    if not user:
        return False
    # Постоянный бан
    if user[7] and user[9] is None:
        return True
    # Временный бан
    if user[7] and user[9] and user[9] > datetime.now():
        return True
    return False

def ban_user(telegram_id: int, reason: str, until: datetime = None):
    """Блокирует пользователя"""
    cur.execute(
        "UPDATE users SET is_banned=TRUE, ban_reason=%s, banned_until=%s WHERE telegram_id=%s",
        (reason, until, telegram_id)
    )

def unban_user(telegram_id: int):
    """Разблокирует пользователя"""
    cur.execute(
        "UPDATE users SET is_banned=FALSE, ban_reason=NULL, banned_until=NULL WHERE telegram_id=%s",
        (telegram_id,)
    )

def get_all_users():
    """Получает список всех пользователей"""
    cur.execute("SELECT * FROM users ORDER BY created_at DESC")
    return cur.fetchall()

def check_duplicate_phone(phone: str) -> bool:
    """Проверяет, нет ли уже активного объявления с таким номером"""
    cur.execute(
        "SELECT id FROM accounts WHERE phone=%s AND status='active' AND is_valid=TRUE",
        (phone,)
    )
    return cur.fetchone() is not None

def add_account(seller_id, title, phone, password_2fa, session_string, session_file_id,
                country, description, price, source_type, **kwargs):
    """Добавляет новый аккаунт в базу"""
    cur.execute("""
        INSERT INTO accounts (
            seller_id, title, phone, password_2fa, session_string, session_file_id,
            country, description, price, source_type, status, is_valid,
            auto_username, auto_firstname, auto_lastname, auto_2fa
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',TRUE,%s,%s,%s,%s)
        RETURNING id
    """, (
        seller_id, title, phone, password_2fa, session_string, session_file_id,
        country, description, price, source_type,
        kwargs.get('au'), kwargs.get('af'), kwargs.get('al'), kwargs.get('a2fa', False)
    ))
    return cur.fetchone()[0]

def get_available_accounts(country=None, price_from=None, price_to=None,
                           has_2fa=None, source=None, page=1):
    """Получает список доступных аккаунтов с фильтрацией и пагинацией"""
    query = """
        SELECT a.*, u.rating 
        FROM accounts a 
        JOIN users u ON a.seller_id = u.telegram_id 
        WHERE a.status = 'active' 
        AND a.is_valid = TRUE 
        AND u.is_banned = FALSE
    """
    params = []
    
    if country:
        query += " AND a.country = %s"
        params.append(country)
    if price_from is not None:
        query += " AND a.price >= %s"
        params.append(price_from)
    if price_to is not None:
        query += " AND a.price <= %s"
        params.append(price_to)
    if has_2fa is not None:
        query += " AND a.auto_2fa = %s"
        params.append(has_2fa)
    if source:
        query += " AND a.source_type = %s"
        params.append(source)
    
    # Сортировка: сначала закреплённые, потом по дате создания
    query += " ORDER BY a.is_pinned DESC, a.created_at DESC"
    query += f" LIMIT {PER_PAGE} OFFSET {(page - 1) * PER_PAGE}"
    
    cur.execute(query, params)
    return cur.fetchall()

def get_total_accounts(country=None, price_from=None, price_to=None,
                       has_2fa=None, source=None):
    """Получает общее количество доступных аккаунтов"""
    query = """
        SELECT COUNT(*) 
        FROM accounts a 
        JOIN users u ON a.seller_id = u.telegram_id 
        WHERE a.status = 'active' 
        AND a.is_valid = TRUE 
        AND u.is_banned = FALSE
    """
    params = []
    
    if country:
        query += " AND a.country = %s"
        params.append(country)
    if price_from is not None:
        query += " AND a.price >= %s"
        params.append(price_from)
    if price_to is not None:
        query += " AND a.price <= %s"
        params.append(price_to)
    if has_2fa is not None:
        query += " AND a.auto_2fa = %s"
        params.append(has_2fa)
    if source:
        query += " AND a.source_type = %s"
        params.append(source)
    
    cur.execute(query, params)
    return cur.fetchone()[0]

def get_account(account_id: int):
    """Получает информацию об аккаунте по ID"""
    cur.execute("SELECT * FROM accounts WHERE id=%s", (account_id,))
    return cur.fetchone()

def buy_account(account_id: int, buyer_id: int):
    """Оформляет покупку аккаунта"""
    hold_until = datetime.now() + timedelta(days=1)
    cur.execute(
        "UPDATE accounts SET status='sold', buyer_id=%s, sold_at=NOW(), hold_until=%s "
        "WHERE id=%s AND status='active'",
        (buyer_id, hold_until, account_id)
    )
    if cur.rowcount > 0:
        purchase_uid = str(uuid.uuid4())[:12].upper()
        cur.execute(
            "INSERT INTO purchases (purchase_uid, buyer_id, account_id) VALUES (%s,%s,%s) RETURNING id",
            (purchase_uid, buyer_id, account_id)
        )
        return cur.fetchone()[0], purchase_uid
    return None, None

def get_purchases(buyer_id: int):
    """Получает список покупок пользователя"""
    cur.execute("""
        SELECT 
            p.id, p.purchase_uid, p.buyer_id, p.account_id, p.purchased_at,
            a.phone, a.password_2fa, a.session_string, a.session_file_id,
            a.country, a.description, a.title, a.auto_username, a.auto_firstname,
            a.auto_lastname, a.auto_2fa, a.source_type, a.can_resell
        FROM purchases p 
        JOIN accounts a ON p.account_id = a.id 
        WHERE p.buyer_id = %s 
        ORDER BY p.purchased_at DESC
    """, (buyer_id,))
    return cur.fetchall()

def get_purchase(purchase_id: int):
    """Получает информацию о конкретной покупке"""
    cur.execute("""
        SELECT 
            p.id, p.purchase_uid, p.buyer_id, p.account_id, p.purchased_at,
            a.phone, a.password_2fa, a.session_string, a.session_file_id,
            a.country, a.description, a.title, a.auto_username, a.auto_firstname,
            a.auto_lastname, a.auto_2fa, a.source_type, a.can_resell
        FROM purchases p 
        JOIN accounts a ON p.account_id = a.id 
        WHERE p.id = %s
    """, (purchase_id,))
    return cur.fetchone()

def add_review(purchase_id: int, rating: int):
    """Добавляет отзыв и обновляет рейтинг продавца"""
    cur.execute(
        "INSERT INTO reviews (purchase_id, rating) VALUES (%s,%s)",
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
            SELECT a.seller_id 
            FROM accounts a 
            JOIN purchases p ON a.id = p.account_id 
            WHERE p.id = %s
        )
    """, (rating, rating, purchase_id))

def has_review(purchase_id: int):
    """Проверяет, оставлен ли уже отзыв"""
    cur.execute("SELECT id FROM reviews WHERE purchase_id=%s", (purchase_id,))
    return cur.fetchone() is not None

def get_seller_accounts(seller_id: int):
    """Получает активные аккаунты продавца"""
    cur.execute(
        "SELECT * FROM accounts WHERE seller_id=%s AND status='active' ORDER BY created_at DESC",
        (seller_id,)
    )
    return cur.fetchall()

def get_seller_stats(seller_id: int):
    """Получает статистику продавца"""
    cur.execute(
        "SELECT COUNT(*) FROM accounts WHERE seller_id=%s AND status='sold'",
        (seller_id,)
    )
    total_sold = cur.fetchone()[0]
    
    cur.execute(
        "SELECT COUNT(*) FROM accounts WHERE seller_id=%s AND status='active'",
        (seller_id,)
    )
    active = cur.fetchone()[0]
    
    return {"total_sold": total_sold, "active": active}

def get_seller_reviews(seller_id: int):
    """Получает последние отзывы о продавце"""
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
    """Снимает аккаунт с продажи"""
    cur.execute(
        "UPDATE accounts SET status='removed' WHERE id=%s AND seller_id=%s",
        (account_id, seller_id)
    )

def pin_account(account_id: int, seller_id: int) -> bool:
    """Закрепляет объявление на 30 минут"""
    pinned_until = datetime.now() + timedelta(minutes=PIN_DURATION)
    cur.execute(
        "UPDATE accounts SET is_pinned=TRUE, pinned_until=%s "
        "WHERE id=%s AND seller_id=%s AND status='active'",
        (pinned_until, account_id, seller_id)
    )
    return cur.rowcount > 0

def unpin_expired():
    """Снимает закрепление с истекших объявлений"""
    cur.execute(
        "UPDATE accounts SET is_pinned=FALSE, pinned_until=NULL "
        "WHERE is_pinned=TRUE AND pinned_until <= NOW()"
    )

def process_expired_holds():
    """Обрабатывает истекшие холды (замороженные средства)"""
    cur.execute(
        "SELECT id, seller_id, price FROM accounts "
        "WHERE status='sold' AND hold_until IS NOT NULL AND hold_until <= NOW()"
    )
    for acc in cur.fetchall():
        try:
            release_hold(acc[1], acc[2])
            add_transaction(acc[1], "sale_released", acc[2], f"Разморозка средств за аккаунт #{acc[0]}")
            cur.execute("UPDATE accounts SET hold_until=NULL WHERE id=%s", (acc[0],))
            logger.info(f"Холд разморожен: аккаунт #{acc[0]}, сумма {acc[2]} ₽")
        except Exception as e:
            logger.error(f"Ошибка при разморозке холда #{acc[0]}: {e}")

def resell_account(account_id: int, seller_id: int, title: str, description: str, price: int) -> bool:
    """Перепродаёт купленный аккаунт (только один раз)"""
    acc = get_account(account_id)
    if not acc or acc[1] != seller_id or not acc[15] or acc[9] != 'sold':
        return False
    
    cur.execute("""
        UPDATE accounts 
        SET seller_id=%s, title=%s, description=%s, price=%s,
            status='active', buyer_id=NULL, sold_at=NULL, hold_until=NULL, can_resell=FALSE
        WHERE id=%s
    """, (seller_id, title, description, price, account_id))
    
    return cur.rowcount > 0

# ==================== BOT INITIALIZATION ====================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ==================== TELEPHON CLIENT ====================
async def create_telethon_client(session_string: str = None):
    """Создаёт клиент Telethon"""
    if session_string:
        return TelegramClient(StringSession(session_string), API_ID, API_HASH)
    return TelegramClient(StringSession(), API_ID, API_HASH)

async def verify_account(session_string: str = None, phone: str = None) -> dict:
    """
    Проверяет валидность аккаунта Telegram.
    Возвращает словарь с результатом проверки.
    """
    client = await create_telethon_client(session_string)
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            if not session_string:
                # Отправляем код подтверждения
                sent = await client.send_code_request(phone)
                new_session = client.session.save()
                await client.disconnect()
                return {
                    "valid": True,
                    "need_code": True,
                    "session_string": new_session,
                    "phone_code_hash": sent.phone_code_hash
                }
            else:
                await client.disconnect()
                return {"valid": False, "error": "Сессия не авторизована"}
        
        # Получаем информацию о пользователе
        me = await client.get_me()
        new_session = client.session.save()
        await client.disconnect()
        
        return {
            "valid": True,
            "session_string": new_session,
            "user_info": {
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "has_2fa": False
            }
        }
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        return {"valid": False, "error": str(e)}

async def sign_in_with_code(session_string: str, phone: str, code: str, phone_code_hash: str) -> dict:
    """Вход в аккаунт с кодом подтверждения"""
    client = await create_telethon_client(session_string)
    try:
        await client.connect()
        await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        new_session = client.session.save()
        await client.disconnect()
        
        return {
            "success": True,
            "session_string": new_session,
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
        return {"success": True, "session_string": session_string, "need_2fa": True}
    except (PhoneCodeInvalidError, PhoneCodeExpiredError):
        await client.disconnect()
        return {"success": False, "error": "Неверный или истёкший код подтверждения"}
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        return {"success": False, "error": str(e)}

async def sign_in_with_2fa(session_string: str, password: str) -> dict:
    """Вход в аккаунт с 2FA паролем"""
    client = await create_telethon_client(session_string)
    try:
        await client.connect()
        await client.sign_in(password=password)
        me = await client.get_me()
        new_session = client.session.save()
        await client.disconnect()
        
        return {
            "success": True,
            "session_string": new_session,
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
    """
    Получает 5-значный код из последнего сообщения в самом новом чате.
    Используется для получения кода подтверждения после покупки аккаунта.
    """
    client = await create_telethon_client(session_string)
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            return None
        
        # Получаем список диалогов
        dialogs = await client.get_dialogs(limit=10)
        
        for dialog in dialogs:
            # Пропускаем каналы и группы
            if dialog.is_channel or dialog.is_group:
                continue
            
            # Получаем последние сообщения
            messages = await client.get_messages(dialog.entity, limit=5)
            for msg in messages:
                if msg.message:
                    # Ищем 5-значный код
                    codes = re.findall(r'\b\d{5}\b', msg.message)
                    if codes:
                        await client.disconnect()
                        return codes[0]
        
        await client.disconnect()
        return None
    except Exception as e:
        logger.error(f"Ошибка при получении кода из чата: {e}")
        try:
            await client.disconnect()
        except:
            pass
        return None

# ==================== CRYPTO BOT API ====================
async def create_crypto_invoice(amount_rub: int, currency: str) -> dict:
    """Создаёт счёт в Crypto Bot для оплаты криптовалютой"""
    if not CRYPTO_BOT_TOKEN:
        return {"success": False, "error": "Crypto Bot не настроен. Админ должен указать токен."}
    
    try:
        # Примерные курсы (в реальности нужно получать через API)
        rates = {
            "USDT": 90,   # 1 USDT = 90 рублей
            "TON": 400,   # 1 TON = 400 рублей
        }
        
        crypto_amount = round(amount_rub / rates.get(currency, 90), 2)
        
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://pay.crypt.bot/api/createInvoice",
                params={
                    "asset": currency,
                    "amount": str(crypto_amount),
                    "description": f"Пополнение баланса на {amount_rub}₽",
                    "allow_comments": False,
                },
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            ) as resp:
                data = await resp.json()
                
                if data.get("ok"):
                    result = data["result"]
                    return {
                        "success": True,
                        "invoice_id": result["invoice_id"],
                        "pay_url": result["pay_url"],
                        "crypto_amount": str(crypto_amount),
                        "currency": currency
                    }
                
                return {"success": False, "error": data.get("error", "Ошибка API Crypto Bot")}
    except Exception as e:
        logger.error(f"Ошибка создания крипто-счёта: {e}")
        return {"success": False, "error": str(e)}

async def check_crypto_invoice(invoice_id: int) -> str:
    """Проверяет статус оплаты крипто-счёта"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://pay.crypt.bot/api/getInvoices",
                params={"invoice_ids": str(invoice_id)},
                headers={"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            ) as resp:
                data = await resp.json()
                
                if data.get("ok") and data["result"]["items"]:
                    return data["result"]["items"][0]["status"]
        
        return "error"
    except Exception as e:
        logger.error(f"Ошибка проверки крипто-счёта: {e}")
        return "error"

# ==================== FSM STATES ====================
class SellAccount(StatesGroup):
    """Состояния для процесса продажи аккаунта"""
    method = State()
    phone = State()
    code = State()
    fa2 = State()
    session_file = State()
    title = State()
    source = State()
    country = State()
    desc = State()
    price = State()

class BuyAccount(StatesGroup):
    """Состояния для процесса покупки"""
    amount = State()
    crypto_amount = State()

class AdminStates(StatesGroup):
    """Состояния для админ-панели"""
    uid = State()
    amount = State()
    ban_reason = State()
    crypto_token = State()

class FilterStates(StatesGroup):
    """Состояния для фильтров"""
    country = State()
    pf = State()
    pt = State()

class ResellStates(StatesGroup):
    """Состояния для перепродажи"""
    title = State()
    desc = State()
    price = State()

# Глобальные хранилища
user_filters = {}  # Фильтры пользователей
crypto_invoices = {}  # Крипто-счета

# ==================== КЛАВИАТУРЫ ====================
def main_menu():
    """Главное меню бота"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="Продать аккаунт",
        callback_data="sell",
        icon_custom_emoji_id=EMOJI["sell"],
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="Купить аккаунт",
        callback_data="buy_list",
        icon_custom_emoji_id=EMOJI["buy"],
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="Профиль",
        callback_data="profile",
        icon_custom_emoji_id=EMOJI["profile"],
        style="default"
    ))
    return kb.as_markup()

def prof_kb():
    """Клавиатура профиля"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="Пополнить баланс",
        callback_data="add_bal",
        icon_custom_emoji_id=EMOJI["star"],
        style="success"
    ))
    kb.row(InlineKeyboardButton(
        text="Мои покупки",
        callback_data="my_purch",
        icon_custom_emoji_id=EMOJI["box"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="Мои объявления",
        callback_data="my_list",
        icon_custom_emoji_id=EMOJI["tag"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="Вывод средств",
        url=SUPPORT_LINK,
        icon_custom_emoji_id=EMOJI["money"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="main",
        style="default"
    ))
    return kb.as_markup()

def back_kb():
    """Клавиатура с кнопкой Назад"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="main",
        style="default"
    ))
    return kb.as_markup()

def acc_list_kb(accounts, page=1, total=0):
    """Клавиатура со списком аккаунтов и пагинацией"""
    kb = InlineKeyboardBuilder()
    
    # Кнопки фильтров сверху
    kb.row(
        InlineKeyboardButton(
            text="🔍 Фильтры",
            callback_data="filters",
            icon_custom_emoji_id=EMOJI["filter"],
            style="primary"
        ),
        InlineKeyboardButton(
            text="🔄 Сброс",
            callback_data="f_reset",
            style="danger"
        )
    )
    
    # Список аккаунтов
    for acc in accounts:
        # acc[17] = is_pinned
        style = "primary" if acc[17] else "default"
        pin_icon = EMOJI["pin"] if acc[17] else EMOJI["globe"]
        kb.row(InlineKeyboardButton(
            text=f"{acc[2]} | {acc[8]}₽",
            callback_data=f"vacc_{acc[0]}",
            icon_custom_emoji_id=pin_icon,
            style=style
        ))
    
    # Пагинация снизу
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    if total_pages > 1:
        row = []
        if page > 1:
            row.append(InlineKeyboardButton(
                text="⬅️",
                callback_data=f"page_{page - 1}",
                style="default"
            ))
        row.append(InlineKeyboardButton(
            text=f"{page}/{total_pages}",
            callback_data="noop",
            style="default"
        ))
        if page < total_pages:
            row.append(InlineKeyboardButton(
                text="➡️",
                callback_data=f"page_{page + 1}",
                style="default"
            ))
        kb.row(*row)
    
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="main",
        style="default"
    ))
    return kb.as_markup()

def acc_view_kb(account_id, seller_id):
    """Клавиатура просмотра аккаунта"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="Проверить и купить",
        callback_data=f"chk_{account_id}",
        icon_custom_emoji_id=EMOJI["buy"],
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="Профиль продавца",
        callback_data=f"seller_{seller_id}",
        icon_custom_emoji_id=EMOJI["people"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="buy_list",
        style="default"
    ))
    return kb.as_markup()

def confirm_kb(account_id):
    """Клавиатура подтверждения покупки"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="Купить",
        callback_data=f"buy_{account_id}",
        icon_custom_emoji_id=EMOJI["buy"],
        style="success"
    ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data=f"vacc_{account_id}",
        style="default"
    ))
    return kb.as_markup()

def seller_kb(seller_id):
    """Клавиатура профиля продавца"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="Аккаунты продавца",
        callback_data=f"saccs_{seller_id}",
        icon_custom_emoji_id=EMOJI["box"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="buy_list",
        style="default"
    ))
    return kb.as_markup()

def filter_kb():
    """Клавиатура фильтров"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="По стране",
        callback_data="f_country",
        icon_custom_emoji_id=EMOJI["globe"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="По цене (от)",
        callback_data="f_pf",
        icon_custom_emoji_id=EMOJI["money"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="По цене (до)",
        callback_data="f_pt",
        icon_custom_emoji_id=EMOJI["money"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="С 2FA",
        callback_data="f_2fay",
        icon_custom_emoji_id=EMOJI["lock"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="Без 2FA",
        callback_data="f_2fan",
        icon_custom_emoji_id=EMOJI["check"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="Сбросить",
        callback_data="f_reset",
        style="danger"
    ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="buy_list",
        style="default"
    ))
    return kb.as_markup()

def purch_kb(purchase_id, can_resell=True):
    """Клавиатура для просмотра покупки"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="Получить код",
        callback_data=f"gcode_{purchase_id}",
        icon_custom_emoji_id=EMOJI["download"],
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="Скачать сессию",
        callback_data=f"sess_{purchase_id}",
        icon_custom_emoji_id=EMOJI["download"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="Оставить отзыв",
        callback_data=f"rev_{purchase_id}",
        icon_custom_emoji_id=EMOJI["edit"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="Проверить валидность",
        callback_data=f"valid_{purchase_id}",
        icon_custom_emoji_id=EMOJI["valid"],
        style="default"
    ))
    if can_resell:
        kb.row(InlineKeyboardButton(
            text="Перепродать",
            callback_data=f"resell_{purchase_id}",
            icon_custom_emoji_id=EMOJI["resell"],
            style="primary"
        ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="profile",
        style="default"
    ))
    return kb.as_markup()

def rev_kb(purchase_id):
    """Клавиатура для выставления оценки"""
    kb = InlineKeyboardBuilder()
    for i in range(1, 6):
        kb.add(InlineKeyboardButton(
            text=str(i),
            callback_data=f"rate_{purchase_id}_{i}",
            icon_custom_emoji_id=EMOJI["star"],
            style="default"
        ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data=f"purch_{purchase_id}",
        style="default"
    ))
    return kb.as_markup()

def mylist_kb(accounts):
    """Клавиатура со списком моих объявлений"""
    kb = InlineKeyboardBuilder()
    for acc in accounts:
        style = "primary" if acc[17] else "default"
        kb.row(InlineKeyboardButton(
            text=f"{acc[2]} | {acc[8]}₽",
            callback_data=f"list_{acc[0]}",
            icon_custom_emoji_id=EMOJI["tag"],
            style=style
        ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="profile",
        style="default"
    ))
    return kb.as_markup()

def list_act_kb(account_id):
    """Клавиатура действий с объявлением"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="Закрепить (15₽/30мин)",
        callback_data=f"pin_{account_id}",
        icon_custom_emoji_id=EMOJI["pin"],
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="Снять с продажи",
        callback_data=f"rem_{account_id}",
        icon_custom_emoji_id=EMOJI["trash"],
        style="danger"
    ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="my_list",
        style="default"
    ))
    return kb.as_markup()

def adm_kb():
    """Клавиатура админ-панели"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="Изменить баланс",
        callback_data="adm_bal",
        icon_custom_emoji_id=EMOJI["wallet"],
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="Пользователи",
        callback_data="adm_users",
        icon_custom_emoji_id=EMOJI["people"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="Статистика",
        callback_data="adm_stat",
        icon_custom_emoji_id=EMOJI["stats"],
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="Токен Crypto Bot",
        callback_data="adm_crypto",
        icon_custom_emoji_id=EMOJI["crypto"],
        style="default"
    ))
    return kb.as_markup()

def add_bal_kb():
    """Клавиатура выбора способа пополнения"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="⭐ Звёзды Telegram",
        callback_data="bal_stars",
        icon_custom_emoji_id=EMOJI["star"],
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="👾 Crypto Bot",
        callback_data="bal_crypto",
        icon_custom_emoji_id=EMOJI["crypto"],
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="profile",
        style="default"
    ))
    return kb.as_markup()

def crypto_curr_kb(amount):
    """Клавиатура выбора криптовалюты"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="💎 TON",
        callback_data=f"crypto_TON_{amount}",
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="💵 USDT",
        callback_data=f"crypto_USDT_{amount}",
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="add_bal",
        style="default"
    ))
    return kb.as_markup()

def sell_method_kb():
    """Клавиатура выбора способа добавления аккаунта"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="Номер + Код",
        callback_data="sell_phone",
        icon_custom_emoji_id=EMOJI["phone"],
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="Файл сессии",
        callback_data="sell_file",
        icon_custom_emoji_id=EMOJI["download"],
        style="primary"
    ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="main",
        style="default"
    ))
    return kb.as_markup()

def source_kb():
    """Клавиатура выбора происхождения аккаунта"""
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(
        text="Авторег",
        callback_data="src_autoreg",
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="Саморег",
        callback_data="src_selfreg",
        style="default"
    ))
    kb.row(InlineKeyboardButton(
        text="Фишинг",
        callback_data="src_phishing",
        style="danger"
    ))
    kb.row(InlineKeyboardButton(
        text="Стилер",
        callback_data="src_stealer",
        style="danger"
    ))
    return kb.as_markup()

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================
async def background_tasks():
    """Фоновые задачи: проверка холдов и снятие закреплений"""
    while True:
        try:
            process_expired_holds()
            unpin_expired()
        except Exception as e:
            logger.error(f"Ошибка в фоновых задачах: {e}")
        await asyncio.sleep(60)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Обработчик команды /start"""
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username)
        logger.info(f"Создан новый пользователь: {message.from_user.id}")
    
    # Инициализируем фильтры
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {"page": 1}
    
    await message.answer(
        f"{em('bot')} Добро пожаловать в <b>Маркетплейс Telegram аккаунтов</b>!\n\n"
        f"Здесь вы можете безопасно купить или продать аккаунты Telegram.\n\n"
        f"{em('info')} Используйте кнопки ниже для навигации:",
        reply_markup=main_menu()
    )

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Обработчик команды /admin"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer(
        f"{em('settings')} <b>Админ-панель</b>\n\n"
        f"Выберите действие:",
        reply_markup=adm_kb()
    )

# ==================== НАВИГАЦИЯ ====================
@router.callback_query(F.data == "main")
async def cb_main(callback: CallbackQuery):
    """Возврат в главное меню"""
    if is_user_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы в боте", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{em('bot')} Главное меню",
        reply_markup=main_menu()
    )

@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    """Открытие профиля"""
    if is_user_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы в боте", show_alert=True)
        return
    
    user = get_user(callback.from_user.id)
    if not user:
        create_user(callback.from_user.id, callback.from_user.username)
        user = get_user(callback.from_user.id)
    
    # Индексы: 0=id, 1=telegram_id, 2=username, 3=balance, 4=frozen_balance, 5=rating, 6=total_reviews
    balance = user[3]
    frozen = user[4]
    rating = user[5]
    total_reviews = user[6]
    
    rating_text = f"⭐ {rating:.1f}" if total_reviews > 0 else "Нет оценок"
    frozen_text = f"\n{em('frozen')} Заморожено: {frozen} ₽" if frozen > 0 else ""
    
    await callback.message.edit_text(
        f"{em('profile')} <b>Профиль</b>\n\n"
        f"{em('wallet')} Баланс: {balance} ₽"
        f"{frozen_text}\n"
        f"{rating_text} ({total_reviews} отзывов)",
        reply_markup=prof_kb()
    )

# ==================== ПРОДАЖА АККАУНТА ====================
@router.callback_query(F.data == "sell")
async def sell_start(callback: CallbackQuery):
    """Начало процесса продажи"""
    if is_user_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы в боте", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{em('sell')} Выберите способ добавления аккаунта:",
        reply_markup=sell_method_kb()
    )

@router.callback_query(F.data == "sell_phone")
async def sell_phone_start(callback: CallbackQuery, state: FSMContext):
    """Продажа через номер телефона"""
    await state.update_data(method="phone")
    await callback.message.edit_text(
        f"{em('sell')} Введите номер телефона в международном формате:\n"
        f"<code>+79991234567</code>",
        reply_markup=back_kb()
    )
    await state.set_state(SellAccount.phone)

@router.callback_query(F.data == "sell_file")
async def sell_file_start(callback: CallbackQuery, state: FSMContext):
    """Продажа через файл сессии"""
    await state.update_data(method="file")
    await callback.message.edit_text(
        f"{em('download')} Отправьте файл сессии Telethon (.session):",
        reply_markup=back_kb()
    )
    await state.set_state(SellAccount.session_file)

@router.message(StateFilter(SellAccount.session_file), F.document)
async def sell_file_received(message: Message, state: FSMContext):
    """Обработка полученного файла сессии"""
    document = message.document
    
    # Проверяем расширение файла
    if not document.file_name or not document.file_name.endswith('.session'):
        await message.answer(
            f"{em('cross')} Отправьте файл с расширением .session"
        )
        return
    
    # Скачиваем файл
    file_id = document.file_id
    file = await bot.get_file(file_id)
    file_path = f"/tmp/{document.file_name}"
    await bot.download_file(file.file_path, file_path)
    
    try:
        # Пробуем загрузить сессию
        client = TelegramClient(file_path, API_ID, API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            await client.disconnect()
            await message.answer(f"{em('cross')} Файл сессии невалиден")
            await state.clear()
            return
        
        # Получаем информацию об аккаунте
        me = await client.get_me()
        session_string = client.session.save()
        await client.disconnect()
        
        phone = me.phone or "Неизвестен"
        country = get_country_from_phone(phone)
        
        if not country:
            await message.answer(
                f"{em('cross')} Страна номера не поддерживается.\n"
                f"Доступны: {', '.join(ALLOWED_COUNTRIES[:10])}..."
            )
            await state.clear()
            return
        
        # Проверка на дубликат
        if check_duplicate_phone(phone):
            await message.answer(
                f"{em('cross')} Аккаунт с таким номером уже продаётся"
            )
            await state.clear()
            return
        
        # Сохраняем данные
        await state.update_data(
            phone=phone,
            ss=session_string,
            sess_file=file_id,
            country=country,
            au=me.username,
            af=me.first_name,
            al=me.last_name,
            a2fa=False
        )
        
        await message.answer(
            f"{em('check')} Сессия успешно загружена!\n"
            f"{em('globe')} Страна определена: <b>{country}</b>\n\n"
            f"Введите название объявления (макс. 50 символов):"
        )
        await state.set_state(SellAccount.title)
        
    except Exception as e:
        logger.error(f"Ошибка загрузки сессии: {e}")
        await message.answer(f"{em('cross')} Ошибка при загрузке сессии: {e}")
        await state.clear()

@router.message(StateFilter(SellAccount.phone))
async def sell_phone(message: Message, state: FSMContext):
    """Обработка ввода номера телефона"""
    phone = message.text.strip()
    
    # Валидация номера
    if not re.match(r'^\+\d{7,15}$', phone):
        await message.answer(
            f"{em('cross')} Неверный формат номера. "
            f"Используйте международный формат: +79991234567"
        )
        return
    
    # Определяем страну
    country = get_country_from_phone(phone)
    if not country:
        await message.answer(
            f"{em('cross')} Страна номера не поддерживается.\n"
            f"Доступные страны: {', '.join(ALLOWED_COUNTRIES[:10])}..."
        )
        return
    
    # Проверка на дубликат
    if check_duplicate_phone(phone):
        await message.answer(
            f"{em('cross')} Аккаунт с таким номером уже продаётся на площадке"
        )
        return
    
    await state.update_data(phone=phone, country=country)
    
    # Проверяем аккаунт через Telethon
    status_message = await message.answer(
        f"{em('clock')} Проверяю аккаунт..."
    )
    
    result = await verify_account(phone=phone)
    
    if result.get("need_code"):
        # Требуется код подтверждения
        await state.update_data(
            ss=result["session_string"],
            phash=result["phone_code_hash"]
        )
        await status_message.edit_text(
            f"{em('send')} Введите код подтверждения, "
            f"отправленный в Telegram (действителен 2 минуты):"
        )
        await state.set_state(SellAccount.code)
        
    elif result.get("valid"):
        # Аккаунт валиден
        await state.update_data(
            ss=result["session_string"],
            au=result["user_info"]["username"],
            af=result["user_info"]["first_name"],
            al=result["user_info"]["last_name"],
            a2fa=False
        )
        await status_message.edit_text(
            f"{em('check')} Аккаунт валиден!\n"
            f"{em('globe')} Страна: <b>{country}</b>\n\n"
            f"Выберите происхождение аккаунта:",
            reply_markup=source_kb()
        )
        await state.set_state(SellAccount.source)
        
    else:
        # Ошибка валидации
        await status_message.edit_text(
            f"{em('cross')} Ошибка проверки аккаунта:\n"
            f"{result.get('error', 'Неизвестная ошибка')}",
            reply_markup=back_kb()
        )
        await state.clear()

@router.message(StateFilter(SellAccount.code))
async def sell_code(message: Message, state: FSMContext):
    """Обработка ввода кода подтверждения"""
    code = message.text.strip()
    data = await state.get_data()
    
    status_message = await message.answer(
        f"{em('clock')} Проверяю код подтверждения..."
    )
    
    result = await sign_in_with_code(
        data["ss"],
        data["phone"],
        code,
        data["phash"]
    )
    
    if result.get("success") and result.get("need_2fa"):
        # Требуется 2FA
        await state.update_data(ss=result["session_string"])
        await status_message.edit_text(
            f"{em('lock')} Введите пароль двухфакторной аутентификации "
            f"(если 2FA нет — напишите <b>нет</b>):"
        )
        await state.set_state(SellAccount.fa2)
        
    elif result.get("success"):
        # Успешный вход
        await state.update_data(
            ss=result["session_string"],
            au=result["user_info"]["username"],
            af=result["user_info"]["first_name"],
            al=result["user_info"]["last_name"],
            a2fa=False
        )
        await status_message.edit_text(
            f"{em('check')} Аккаунт подтверждён!\n"
            f"{em('globe')} Страна: <b>{data['country']}</b>\n\n"
            f"Выберите происхождение аккаунта:",
            reply_markup=source_kb()
        )
        await state.set_state(SellAccount.source)
        
    else:
        # Ошибка входа
        await status_message.edit_text(
            f"{em('cross')} Ошибка: {result.get('error', 'Неверный код')}",
            reply_markup=back_kb()
        )
        await state.clear()

@router.message(StateFilter(SellAccount.fa2))
async def sell_2fa(message: Message, state: FSMContext):
    """Обработка ввода 2FA пароля"""
    password = message.text.strip()
    data = await state.get_data()
    
    if password.lower() == 'нет':
        password = None
    
    if password:
        status_message = await message.answer(
            f"{em('clock')} Проверяю пароль 2FA..."
        )
        result = await sign_in_with_2fa(data["ss"], password)
    else:
        result = {
            "success": True,
            "session_string": data["ss"],
            "user_info": {
                "username": None,
                "first_name": None,
                "last_name": None,
                "has_2fa": False
            }
        }
        status_message = await message.answer(
            f"{em('clock')} Обрабатываю..."
        )
    
    if result.get("success"):
        await state.update_data(
            ss=result["session_string"],
            au=result["user_info"]["username"],
            af=result["user_info"]["first_name"],
            al=result["user_info"]["last_name"],
            a2fa=result["user_info"]["has_2fa"],
            pwd=password
        )
        await status_message.edit_text(
            f"{em('check')} Аккаунт подтверждён!\n"
            f"{em('globe')} Страна: <b>{data['country']}</b>\n\n"
            f"Выберите происхождение аккаунта:",
            reply_markup=source_kb()
        )
        await state.set_state(SellAccount.source)
    else:
        await status_message.edit_text(
            f"{em('cross')} Ошибка: {result.get('error', 'Неверный пароль 2FA')}",
            reply_markup=back_kb()
        )
        await state.clear()

@router.callback_query(F.data.startswith("src_"), StateFilter(SellAccount.source))
async def sell_source(callback: CallbackQuery, state: FSMContext):
    """Обработка выбора происхождения аккаунта"""
    source = callback.data.split("_")[1]
    await state.update_data(source=source)
    
    await callback.message.edit_text(
        f"{em('edit')} Введите название объявления (макс. 50 символов):"
    )
    await state.set_state(SellAccount.title)

@router.message(StateFilter(SellAccount.title))
async def sell_title(message: Message, state: FSMContext):
    """Обработка ввода названия объявления"""
    title = message.text.strip()
    
    if len(title) > 50:
        await message.answer(
            f"{em('cross')} Название не должно превышать 50 символов. "
            f"Сейчас: {len(title)}"
        )
        return
    
    await state.update_data(title=title)
    
    await message.answer(
        f"{em('edit')} Введите описание аккаунта (до 100 слов):"
    )
    await state.set_state(SellAccount.desc)

@router.message(StateFilter(SellAccount.desc))
async def sell_desc(message: Message, state: FSMContext):
    """Обработка ввода описания"""
    description = message.text.strip()
    words = description.split()
    
    if len(words) > 100:
        await message.answer(
            f"{em('cross')} Описание не должно превышать 100 слов. "
            f"Сейчас: {len(words)} слов."
        )
        return
    
    await state.update_data(desc=description)
    
    await message.answer(
        f"{em('money')} Введите цену аккаунта в рублях (целое число):"
    )
    await state.set_state(SellAccount.price)

@router.message(StateFilter(SellAccount.price))
async def sell_price(message: Message, state: FSMContext):
    """Обработка ввода цены и завершение продажи"""
    try:
        price = int(message.text.strip())
        if price < 1:
            raise ValueError("Цена должна быть больше 0")
    except ValueError:
        await message.answer(
            f"{em('cross')} Введите целое число больше 0"
        )
        return
    
    data = await state.get_data()
    
    # Формируем авто-описание с характеристиками
    auto_description = f"\n\n<b>Характеристики:</b>"
    if data.get("au"):
        auto_description += f"\n• @{data['au']}"
    if data.get("af"):
        auto_description += f"\n• Имя: {data['af']}"
    if data.get("al"):
        auto_description += f"\n• Фамилия: {data['al']}"
    auto_description += f"\n• 2FA: {'Есть' if data.get('a2fa') else 'Нет'}"
    auto_description += f"\n• Тип: {SOURCE_TYPES.get(data.get('source', 'selfreg'), 'Саморег')}"
    
    full_description = data["desc"] + auto_description
    
    # Добавляем аккаунт в базу данных
    account_id = add_account(
        seller_id=message.from_user.id,
        title=data["title"],
        phone=data["phone"],
        password_2fa=data.get("pwd"),
        session_string=data["ss"],
        session_file_id=data.get("sess_file"),
        country=data["country"],
        description=full_description,
        price=price,
        source_type=data.get("source", "selfreg"),
        au=data.get("au"),
        af=data.get("af"),
        al=data.get("al"),
        a2fa=data.get("a2fa", False)
    )
    
    # Уведомляем об успехе
    await message.answer(
        f"{em('check')} <b>Аккаунт успешно выставлен на продажу!</b>\n\n"
        f"{em('tag')} Название: {data['title']}\n"
        f"{em('money')} Цена: {price} ₽\n"
        f"{em('globe')} Страна: {data['country']}\n"
        f"{em('info')} Тип: {SOURCE_TYPES.get(data.get('source', 'selfreg'), 'Саморег')}",
        reply_markup=main_menu()
    )
    
    logger.info(f"Пользователь {message.from_user.id} выставил аккаунт #{account_id} на продажу")
    await state.clear()

# ==================== ПОКУПКА АККАУНТА ====================
@router.callback_query(F.data == "buy_list")
async def buy_list(callback: CallbackQuery):
    """Показ списка доступных аккаунтов"""
    if is_user_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы в боте", show_alert=True)
        return
    
    # Сбрасываем страницу при новом заходе
    if callback.from_user.id not in user_filters:
        user_filters[callback.from_user.id] = {}
    user_filters[callback.from_user.id]["page"] = 1
    
    await show_accs(callback)

async def show_accs(callback: CallbackQuery, page=1):
    """Отображает список доступных аккаунтов с учётом фильтров и пагинации"""
    filters = user_filters.get(callback.from_user.id, {})
    
    # Получаем аккаунты
    accounts = get_available_accounts(
        country=filters.get("country"),
        price_from=filters.get("pf"),
        price_to=filters.get("pt"),
        has_2fa=filters.get("h2fa"),
        source=filters.get("source"),
        page=page
    )
    
    # Получаем общее количество
    total = get_total_accounts(
        country=filters.get("country"),
        price_from=filters.get("pf"),
        price_to=filters.get("pt"),
        has_2fa=filters.get("h2fa"),
        source=filters.get("source")
    )
    
    if not accounts:
        await callback.message.edit_text(
            f"{em('info')} Нет доступных аккаунтов для покупки.\n"
            f"Попробуйте сбросить фильтры или зайдите позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="🔍 Фильтры",
                    callback_data="filters",
                    icon_custom_emoji_id=EMOJI["filter"],
                    style="primary"
                )],
                [InlineKeyboardButton(
                    text="🔄 Сбросить фильтры",
                    callback_data="f_reset",
                    style="danger"
                )],
                [InlineKeyboardButton(
                    text="↩️ Назад",
                    callback_data="main",
                    style="default"
                )],
            ])
        )
        return
    
    # Показываем список
    await callback.message.edit_text(
        f"{em('buy')} <b>Доступные аккаунты</b>\n"
        f"Найдено: {total} | Страница {page}",
        reply_markup=acc_list_kb(accounts, page, total)
    )

@router.callback_query(F.data.startswith("page_"))
async def page_change(callback: CallbackQuery):
    """Переключение страниц"""
    page = int(callback.data.split("_")[1])
    
    if callback.from_user.id not in user_filters:
        user_filters[callback.from_user.id] = {}
    user_filters[callback.from_user.id]["page"] = page
    
    await show_accs(callback, page)

@router.callback_query(F.data.startswith("vacc_"))
async def view_acc(callback: CallbackQuery):
    """Просмотр детальной информации об аккаунте"""
    account_id = int(callback.data.split("_")[1])
    account = get_account(account_id)
    
    # Проверяем доступность
    if not account or account[9] != "active":
        await callback.answer("Аккаунт уже недоступен", show_alert=True)
        await show_accs(callback)
        return
    
    # Получаем информацию о продавце
    seller = get_user(account[1])
    
    # Формируем текст
    # Индексы: 0=id, 1=seller_id, 2=title, 6=country, 7=description, 8=price, 11=source_type, 17=is_pinned
    text = (
        f"{em('tag')} <b>{account[2]}</b>\n\n"
        f"{em('globe')} Страна: {account[6]}\n"
        f"{em('money')} Цена: {account[8]} ₽\n"
        f"Тип: {SOURCE_TYPES.get(account[11], 'Саморег')}\n"
        f"{em('people')} Продавец: {seller[2] or 'Без username'}"
    )
    
    # Добавляем рейтинг если есть
    if seller[6] > 0:
        text += f"\n⭐ Рейтинг: {seller[5]:.1f} ({seller[6]} отзывов)"
    
    # Добавляем описание
    text += f"\n\n{em('info')} {account[7] or 'Нет описания'}"
    
    # Отмечаем закрепление
    if account[17]:
        text += f"\n{em('pin')} <b>Закреплено</b>"
    
    await callback.message.edit_text(
        text,
        reply_markup=acc_view_kb(account_id, account[1])
    )

@router.callback_query(F.data.startswith("chk_"))
async def check_buy(callback: CallbackQuery):
    """Проверка валидности аккаунта перед покупкой"""
    account_id = int(callback.data.split("_")[1])
    account = get_account(account_id)
    
    if not account or account[9] != "active":
        await callback.answer("Аккаунт уже недоступен", show_alert=True)
        await show_accs(callback)
        return
    
    # Сообщаем о начале проверки
    await callback.message.edit_text(
        f"{em('clock')} Проверяю валидность аккаунта..."
    )
    
    # Проверяем валидность через Telethon
    # account[5] = session_string
    result = await verify_account(session_string=account[5])
    
    if not result.get("valid"):
        await callback.message.edit_text(
            f"{em('cross')} Аккаунт не прошёл проверку валидности.\n"
            f"Возможно, сессия устарела или аккаунт заблокирован.",
            reply_markup=back_kb()
        )
        return
    
    # Аккаунт валиден — показываем подтверждение
    await callback.message.edit_text(
        f"{em('tag')} <b>{account[2]}</b>\n\n"
        f"{em('globe')} Страна: {account[6]}\n"
        f"{em('money')} Цена: {account[8]} ₽\n\n"
        f"{em('check')} Аккаунт валиден!\n"
        f"Нажмите <b>Купить</b> для подтверждения покупки.",
        reply_markup=confirm_kb(account_id)
    )

@router.callback_query(F.data.startswith("buy_"))
async def buy_acc(callback: CallbackQuery):
    """Подтверждение и выполнение покупки"""
    account_id = int(callback.data.split("_")[1])
    account = get_account(account_id)
    
    # Проверяем доступность
    if not account or account[9] != "active":
        await callback.answer("Аккаунт уже куплен или снят с продажи", show_alert=True)
        await show_accs(callback)
        return
    
    buyer = get_user(callback.from_user.id)
    
    # Проверяем что покупатель не продавец
    if buyer[0] == account[1]:
        await callback.answer("Нельзя купить свой собственный аккаунт", show_alert=True)
        return
    
    # Проверяем баланс
    # buyer[3] = balance, account[8] = price
    if buyer[3] < account[8]:
        await callback.answer(
            f"Недостаточно средств! Ваш баланс: {buyer[3]} ₽, требуется: {account[8]} ₽",
            show_alert=True
        )
        return
    
    # Списываем средства с покупателя
    update_balance(callback.from_user.id, -account[8])
    
    # Замораживаем средства продавца (холдинг 24 часа)
    freeze_balance(account[1], account[8])
    
    # Записываем транзакции
    add_transaction(
        callback.from_user.id, "purchase", -account[8],
        f"Покупка аккаунта #{account_id}"
    )
    add_transaction(
        account[1], "sale_frozen", account[8],
        f"Продажа аккаунта #{account_id} (заморожено на 24ч)"
    )
    
    # Выполняем покупку
    purchase_id, purchase_uid = buy_account(account_id, callback.from_user.id)
    
    if not purchase_id:
        # Откатываем если ошибка
        update_balance(callback.from_user.id, account[8])
        await callback.answer("Ошибка при покупке, средства возвращены", show_alert=True)
        return
    
    # Показываем результат
    # account[3] = phone, account[4] = password_2fa
    purchase_text = (
        f"{em('check')} <b>Аккаунт успешно куплен!</b>\n\n"
        f"🆔 ID покупки: <code>{purchase_uid}</code>\n"
        f"{em('tag')} {account[2]}\n"
        f"{em('globe')} Страна: {account[6]}\n"
        f"{em('phone')} Номер: <code>{account[3]}</code>\n"
    )
    
    if account[4]:
        purchase_text += f"{em('lock')} 2FA: <code>{account[4]}</code>\n"
    else:
        purchase_text += f"{em('lock')} 2FA: Отсутствует\n"
    
    purchase_text += (
        f"\n{em('money')} Списано: {account[8]} ₽\n"
        f"{em('info')} Код подтверждения можно получить в разделе «Мои покупки»"
    )
    
    await callback.message.edit_text(
        purchase_text,
        reply_markup=back_kb()
    )
    
    # Уведомляем продавца
    try:
        await bot.send_message(
            account[1],
            f"{em('gift')} Ваш аккаунт «{account[2]}» был продан!\n\n"
            f"🆔 ID покупки: <code>{purchase_uid}</code>\n"
            f"{em('money')} Сумма: {account[8]} ₽\n"
            f"{em('clock')} Средства будут зачислены на баланс через 24 часа."
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить продавца {account[1]}: {e}")
    
    logger.info(f"Аккаунт #{account_id} куплен пользователем {callback.from_user.id}")

# ==================== ПРОФИЛЬ ПРОДАВЦА ====================
@router.callback_query(F.data.startswith("seller_"))
async def seller_prof(callback: CallbackQuery):
    """Просмотр профиля продавца"""
    seller_id = int(callback.data.split("_")[1])
    seller = get_user(seller_id)
    
    if not seller:
        await callback.answer("Продавец не найден", show_alert=True)
        return
    
    # Получаем статистику
    stats = get_seller_stats(seller_id)
    reviews = get_seller_reviews(seller_id)
    
    # Формируем текст профиля
    text = (
        f"{em('people')} <b>Профиль продавца</b>\n\n"
        f"Username: {seller[2] or 'Скрыт'}\n"
    )
    
    if seller[6] > 0:
        text += f"⭐ Рейтинг: {seller[5]:.1f} ({seller[6]} отзывов)"
    else:
        text += "⭐ Рейтинг: Нет оценок"
    
    text += (
        f"\n\n{em('stats')} <b>Статистика:</b>\n"
        f"• Продано аккаунтов: {stats['total_sold']}\n"
        f"• Активных объявлений: {stats['active']}"
    )
    
    # Добавляем последние отзывы
    if reviews:
        text += f"\n\n{em('edit')} <b>Последние отзывы:</b>"
        for review in reviews[:5]:
            text += f"\n• {review[0]}⭐ от пользователя {review[2]}"
    
    await callback.message.edit_text(
        text,
        reply_markup=seller_kb(seller_id)
    )

@router.callback_query(F.data.startswith("saccs_"))
async def seller_accs(callback: CallbackQuery):
    """Просмотр активных аккаунтов продавца"""
    seller_id = int(callback.data.split("_")[1])
    accounts = get_seller_accounts(seller_id)
    
    if not accounts:
        await callback.message.edit_text(
            f"{em('info')} У продавца нет активных аккаунтов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="↩️ Назад к профилю",
                    callback_data=f"seller_{seller_id}",
                    style="default"
                )]
            ])
        )
        return
    
    # Создаём кнопки с аккаунтами
    kb = InlineKeyboardBuilder()
    for acc in accounts:
        kb.row(InlineKeyboardButton(
            text=f"{acc[2]} | {acc[8]}₽",
            callback_data=f"vacc_{acc[0]}",
            icon_custom_emoji_id=EMOJI["globe"],
            style="default"
        ))
    kb.row(InlineKeyboardButton(
        text="↩️ Назад к профилю",
        callback_data=f"seller_{seller_id}",
        style="default"
    ))
    
    await callback.message.edit_text(
        f"{em('box')} <b>Аккаунты продавца:</b>",
        reply_markup=kb.as_markup()
    )

# ==================== ФИЛЬТРЫ ====================
@router.callback_query(F.data == "filters")
async def filters_menu(callback: CallbackQuery):
    """Показывает меню фильтров"""
    filters = user_filters.get(callback.from_user.id, {})
    
    filter_text = (
        f"{em('filter')} <b>Фильтры поиска:</b>\n\n"
        f"Страна: {filters.get('country', 'Все')}\n"
        f"Цена от: {filters.get('pf', 'Нет')} ₽\n"
        f"Цена до: {filters.get('pt', 'Нет')} ₽\n"
        f"2FA: {filters.get('h2fa', 'Не важно')}\n"
        f"Тип: {SOURCE_TYPES.get(filters.get('source'), 'Все')}"
    )
    
    await callback.message.edit_text(
        filter_text,
        reply_markup=filter_kb()
    )

@router.callback_query(F.data == "f_country")
async def f_country(callback: CallbackQuery, state: FSMContext):
    """Установка фильтра по стране"""
    await callback.message.edit_text(
        f"{em('globe')} Введите название страны (или «все» для сброса):\n"
        f"Доступные страны: {', '.join(ALLOWED_COUNTRIES)}",
        reply_markup=back_kb()
    )
    await state.set_state(FilterStates.country)

@router.message(StateFilter(FilterStates.country))
async def f_country_set(message: Message, state: FSMContext):
    """Установка значения фильтра страны"""
    country = message.text.strip()
    
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {}
    
    if country.lower() == "все":
        user_filters[message.from_user.id].pop("country", None)
    elif country in ALLOWED_COUNTRIES:
        user_filters[message.from_user.id]["country"] = country
    else:
        await message.answer(
            f"{em('cross')} Страна не найдена в списке доступных"
        )
        return
    
    await state.clear()
    await message.answer(
        f"{em('check')} Фильтр по стране обновлён!",
        reply_markup=main_menu()
    )

@router.callback_query(F.data == "f_pf")
async def f_pf(callback: CallbackQuery, state: FSMContext):
    """Установка фильтра минимальной цены"""
    await callback.message.edit_text(
        f"{em('money')} Введите минимальную цену в рублях (0 для сброса):",
        reply_markup=back_kb()
    )
    await state.set_state(FilterStates.pf)

@router.message(StateFilter(FilterStates.pf))
async def f_pf_set(message: Message, state: FSMContext):
    """Установка значения минимальной цены"""
    try:
        price = int(message.text.strip())
    except ValueError:
        await message.answer(f"{em('cross')} Введите целое число")
        return
    
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {}
    
    if price == 0:
        user_filters[message.from_user.id].pop("pf", None)
    else:
        user_filters[message.from_user.id]["pf"] = price
    
    await state.clear()
    await message.answer(
        f"{em('check')} Фильтр минимальной цены обновлён!",
        reply_markup=main_menu()
    )

@router.callback_query(F.data == "f_pt")
async def f_pt(callback: CallbackQuery, state: FSMContext):
    """Установка фильтра максимальной цены"""
    await callback.message.edit_text(
        f"{em('money')} Введите максимальную цену в рублях (0 для сброса):",
        reply_markup=back_kb()
    )
    await state.set_state(FilterStates.pt)

@router.message(StateFilter(FilterStates.pt))
async def f_pt_set(message: Message, state: FSMContext):
    """Установка значения максимальной цены"""
    try:
        price = int(message.text.strip())
    except ValueError:
        await message.answer(f"{em('cross')} Введите целое число")
        return
    
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {}
    
    if price == 0:
        user_filters[message.from_user.id].pop("pt", None)
    else:
        user_filters[message.from_user.id]["pt"] = price
    
    await state.clear()
    await message.answer(
        f"{em('check')} Фильтр максимальной цены обновлён!",
        reply_markup=main_menu()
    )

@router.callback_query(F.data == "f_2fay")
async def f_2fay(callback: CallbackQuery):
    """Фильтр: только с 2FA"""
    if callback.from_user.id not in user_filters:
        user_filters[callback.from_user.id] = {}
    user_filters[callback.from_user.id]["h2fa"] = True
    await callback.answer("Показываются только аккаунты с 2FA")
    await filters_menu(callback)

@router.callback_query(F.data == "f_2fan")
async def f_2fan(callback: CallbackQuery):
    """Фильтр: только без 2FA"""
    if callback.from_user.id not in user_filters:
        user_filters[callback.from_user.id] = {}
    user_filters[callback.from_user.id]["h2fa"] = False
    await callback.answer("Показываются только аккаунты без 2FA")
    await filters_menu(callback)

@router.callback_query(F.data == "f_reset")
async def f_reset(callback: CallbackQuery):
    """Сброс всех фильтров"""
    user_filters[callback.from_user.id] = {"page": 1}
    await callback.answer("Фильтры сброшены")
    await show_accs(callback)

# ==================== МОИ ПОКУПКИ ====================
@router.callback_query(F.data == "my_purch")
async def my_purch(callback: CallbackQuery):
    """Показывает список покупок пользователя"""
    purchases = get_purchases(callback.from_user.id)
    
    if not purchases:
        await callback.message.edit_text(
            f"{em('info')} У вас пока нет покупок.",
            reply_markup=back_kb()
        )
        return
    
    # Создаём кнопки с покупками
    kb = InlineKeyboardBuilder()
    for purchase in purchases:
        # purchase[11] = title, purchase[1] = purchase_uid
        title = purchase[11] if purchase[11] else f"Покупка {purchase[1]}"
        kb.row(InlineKeyboardButton(
            text=f"{title} | {purchase[1]}",
            callback_data=f"purch_{purchase[0]}",
            icon_custom_emoji_id=EMOJI["box"],
            style="default"
        ))
    
    # Кнопка проверки всех аккаунтов
    kb.row(InlineKeyboardButton(
        text="Проверить всё на валидность",
        callback_data="valid_all",
        icon_custom_emoji_id=EMOJI["valid"],
        style="primary"
    ))
    
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="profile",
        style="default"
    ))
    
    await callback.message.edit_text(
        f"{em('box')} <b>Ваши покупки:</b>\n"
        f"Всего: {len(purchases)}",
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data == "valid_all")
async def valid_all(callback: CallbackQuery):
    """Проверяет валидность всех купленных аккаунтов"""
    purchases = get_purchases(callback.from_user.id)
    
    if not purchases:
        await callback.answer("Нет покупок для проверки", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{em('clock')} Проверяю все аккаунты на валидность..."
    )
    
    results = []
    for purchase in purchases:
        # purchase[8] = session_string
        result = await verify_account(ss=purchase[8])
        status = em('valid') if result.get("valid") else em('invalid')
        title = purchase[11] or purchase[1]
        results.append(f"{status} {title}")
    
    await callback.message.edit_text(
        f"{em('stats')} <b>Результаты проверки:</b>\n\n" + "\n".join(results),
        reply_markup=back_kb()
    )

@router.callback_query(F.data.startswith("valid_"))
async def valid_one(callback: CallbackQuery):
    """Проверяет валидность одного аккаунта"""
    purchase_id = int(callback.data.split("_")[1])
    purchase = get_purchase(purchase_id)
    
    if not purchase or purchase[2] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{em('clock')} Проверяю валидность..."
    )
    
    result = await verify_account(ss=purchase[8])
    status = f"{em('valid')} Валиден" if result.get("valid") else f"{em('invalid')} Невалиден"
    
    await callback.message.edit_text(
        f"{status}\n{purchase[11] or purchase[1]}",
        reply_markup=back_kb()
    )

@router.callback_query(F.data.startswith("purch_"))
async def view_purch(callback: CallbackQuery):
    """Просмотр деталей покупки"""
    purchase_id = int(callback.data.split("_")[1])
    purchase = get_purchase(purchase_id)
    
    if not purchase or purchase[2] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    # Индексы: 0=id, 1=purchase_uid, 2=buyer_id, 3=account_id, 4=purchased_at,
    # 5=phone, 6=password_2fa, 7=session_string, 8=session_file_id,
    # 9=country, 10=description, 11=title, 18=can_resell
    text = (
        f"{em('box')} <b>{purchase[11]}</b>\n\n"
        f"🆔 ID: <code>{purchase[1]}</code>\n"
        f"{em('globe')} Страна: {purchase[9]}\n"
        f"{em('info')} Описание: {purchase[10] or 'Нет'}\n\n"
        f"{em('phone')} Номер: <code>{purchase[5]}</code>\n"
    )
    
    if purchase[6]:
        text += f"{em('lock')} 2FA пароль: <code>{purchase[6]}</code>\n"
    else:
        text += f"{em('lock')} 2FA: Отсутствует\n"
    
    if has_review(purchase_id):
        text += f"\n{em('check')} Отзыв оставлен"
    
    can_resell = purchase[18] if len(purchase) > 18 else True
    
    await callback.message.edit_text(
        text,
        reply_markup=purch_kb(purchase_id, can_resell)
    )

@router.callback_query(F.data.startswith("gcode_"))
async def get_code(callback: CallbackQuery):
    """Получение кода подтверждения из чата"""
    purchase_id = int(callback.data.split("_")[1])
    purchase = get_purchase(purchase_id)
    
    if not purchase or purchase[2] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    await callback.answer("Ищу код подтверждения...")
    
    status_message = await callback.message.answer(
        f"{em('clock')} Ищу код подтверждения в чатах аккаунта..."
    )
    
    # purchase[7] = session_string
    code = await get_code_from_chat(purchase[7])
    
    if code:
        await status_message.edit_text(
            f"{em('check')} Код подтверждения найден!\n\n"
            f"<code>{code}</code>"
        )
    else:
        await status_message.edit_text(
            f"{em('cross')} Код подтверждения не найден.\n"
            f"Возможно, он ещё не пришёл. Попробуйте позже."
        )

@router.callback_query(F.data.startswith("sess_"))
async def get_session(callback: CallbackQuery):
    """Скачивание файла сессии"""
    purchase_id = int(callback.data.split("_")[1])
    purchase = get_purchase(purchase_id)
    
    if not purchase or purchase[2] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    # purchase[8] = session_file_id, purchase[7] = session_string
    if purchase[8]:
        # Отправляем файл сессии
        await callback.message.answer_document(
            purchase[8],
            caption=f"Файл сессии для покупки {purchase[1]}"
        )
        await callback.answer("Файл отправлен")
    elif purchase[7]:
        # Создаём файл из строки сессии
        file = io.BytesIO(purchase[7].encode())
        file.name = f"session_{purchase[1]}.session"
        await callback.message.answer_document(
            file,
            caption=f"Файл сессии (StringSession) для покупки {purchase[1]}"
        )
        await callback.answer("Файл отправлен")
    else:
        await callback.answer("Сессия недоступна для скачивания", show_alert=True)

@router.callback_query(F.data.startswith("rev_"))
async def review(callback: CallbackQuery):
    """Начало процесса оставления отзыва"""
    purchase_id = int(callback.data.split("_")[1])
    purchase = get_purchase(purchase_id)
    
    if not purchase or purchase[2] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    if has_review(purchase_id):
        await callback.answer("Вы уже оставили отзыв об этой покупке", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{em('edit')} Поставьте оценку продавцу (1-5 звёзд):",
        reply_markup=rev_kb(purchase_id)
    )

@router.callback_query(F.data.startswith("rate_"))
async def rate(callback: CallbackQuery):
    """Сохранение оценки"""
    parts = callback.data.split("_")
    purchase_id = int(parts[1])
    rating = int(parts[2])
    
    # Проверяем что покупка существует
    purchase = get_purchase(purchase_id)
    if not purchase or purchase[2] != callback.from_user.id:
        await callback.answer("Ошибка", show_alert=True)
        return
    
    # Сохраняем отзыв
    add_review(purchase_id, rating)
    
    await callback.message.edit_text(
        f"{em('check')} Спасибо за отзыв!\n"
        f"Вы поставили оценку: {rating} ⭐",
        reply_markup=back_kb()
    )
    
    logger.info(f"Пользователь {callback.from_user.id} оставил отзыв {rating}⭐ на покупку #{purchase_id}")

# ==================== ПЕРЕПРОДАЖА ====================
@router.callback_query(F.data.startswith("resell_"))
async def resell_start(callback: CallbackQuery, state: FSMContext):
    """Начало процесса перепродажи"""
    purchase_id = int(callback.data.split("_")[1])
    purchase = get_purchase(purchase_id)
    
    if not purchase or purchase[2] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    # Проверяем что аккаунт можно перепродать
    can_resell = purchase[18] if len(purchase) > 18 else True
    if not can_resell:
        await callback.answer("Этот аккаунт уже был перепродан", show_alert=True)
        return
    
    await state.update_data(resell_pid=purchase_id, resell_aid=purchase[3])
    
    await callback.message.edit_text(
        f"{em('resell')} <b>Перепродажа аккаунта</b>\n\n"
        f"Введите новое название объявления:",
        reply_markup=back_kb()
    )
    await state.set_state(ResellStates.title)

@router.message(StateFilter(ResellStates.title))
async def resell_title(message: Message, state: FSMContext):
    """Ввод названия для перепродажи"""
    title = message.text.strip()
    await state.update_data(title=title)
    await message.answer(f"{em('edit')} Введите новое описание:")
    await state.set_state(ResellStates.desc)

@router.message(StateFilter(ResellStates.desc))
async def resell_desc(message: Message, state: FSMContext):
    """Ввод описания для перепродажи"""
    description = message.text.strip()
    await state.update_data(desc=description)
    await message.answer(f"{em('money')} Введите новую цену в рублях:")
    await state.set_state(ResellStates.price)

@router.message(StateFilter(ResellStates.price))
async def resell_price(message: Message, state: FSMContext):
    """Ввод цены и завершение перепродажи"""
    try:
        price = int(message.text.strip())
        if price < 1:
            raise ValueError
    except ValueError:
        await message.answer(f"{em('cross')} Введите целое число больше 0")
        return
    
    data = await state.get_data()
    
    success = resell_account(
        data["resell_aid"],
        message.from_user.id,
        data["title"],
        data["desc"],
        price
    )
    
    if success:
        await message.answer(
            f"{em('check')} Аккаунт успешно перепродан!\n"
            f"{em('tag')} Новое название: {data['title']}\n"
            f"{em('money')} Новая цена: {price} ₽",
            reply_markup=main_menu()
        )
        logger.info(f"Пользователь {message.from_user.id} перепродал аккаунт #{data['resell_aid']}")
    else:
        await message.answer(
            f"{em('cross')} Ошибка при перепродаже аккаунта",
            reply_markup=back_kb()
        )
    
    await state.clear()

# ==================== МОИ ОБЪЯВЛЕНИЯ ====================
@router.callback_query(F.data == "my_list")
async def my_list(callback: CallbackQuery):
    """Показывает список моих объявлений"""
    accounts = get_seller_accounts(callback.from_user.id)
    
    if not accounts:
        await callback.message.edit_text(
            f"{em('info')} У вас нет активных объявлений.",
            reply_markup=back_kb()
        )
        return
    
    await callback.message.edit_text(
        f"{em('tag')} <b>Ваши объявления:</b>\n"
        f"Активных: {len(accounts)}",
        reply_markup=mylist_kb(accounts)
    )

@router.callback_query(F.data.startswith("list_"))
async def view_list(callback: CallbackQuery):
    """Просмотр своего объявления"""
    account_id = int(callback.data.split("_")[1])
    account = get_account(account_id)
    
    if not account or account[1] != callback.from_user.id:
        await callback.answer("Объявление не найдено", show_alert=True)
        return
    
    text = (
        f"{em('tag')} <b>{account[2]}</b>\n\n"
        f"{em('globe')} Страна: {account[6]}\n"
        f"{em('money')} Цена: {account[8]} ₽\n"
        f"Тип: {SOURCE_TYPES.get(account[11], 'Саморег')}\n"
        f"Статус: {account[9]}"
    )
    
    if account[17]:
        pinned_time = account[18].strftime('%H:%M') if account[18] else '...'
        text += f"\n{em('pin')} Закреплено до {pinned_time}"
    
    text += f"\n\nОписание: {account[7] or 'Нет описания'}"
    
    await callback.message.edit_text(
        text,
        reply_markup=list_act_kb(account_id)
    )

@router.callback_query(F.data.startswith("pin_"))
async def pin_acc(callback: CallbackQuery):
    """Закрепление объявления"""
    account_id = int(callback.data.split("_")[1])
    account = get_account(account_id)
    
    if not account or account[1] != callback.from_user.id:
        await callback.answer("Объявление не найдено", show_alert=True)
        return
    
    user = get_user(callback.from_user.id)
    
    if user[3] < PIN_PRICE:
        await callback.answer(
            f"Недостаточно средств! Нужно {PIN_PRICE} ₽, у вас: {user[3]} ₽",
            show_alert=True
        )
        return
    
    if pin_account(account_id, callback.from_user.id):
        update_balance(callback.from_user.id, -PIN_PRICE)
        add_transaction(
            callback.from_user.id, "pin", -PIN_PRICE,
            f"Закрепление объявления #{account_id}"
        )
        await callback.message.edit_text(
            f"{em('check')} Объявление закреплено на 30 минут!\n"
            f"Списано: {PIN_PRICE} ₽",
            reply_markup=back_kb()
        )
    else:
        await callback.answer("Ошибка при закреплении", show_alert=True)

@router.callback_query(F.data.startswith("rem_"))
async def rem_list(callback: CallbackQuery):
    """Снятие объявления с продажи"""
    account_id = int(callback.data.split("_")[1])
    remove_account(account_id, callback.from_user.id)
    
    await callback.message.edit_text(
        f"{em('check')} Объявление снято с продажи.",
        reply_markup=back_kb()
    )
    
    logger.info(f"Пользователь {callback.from_user.id} снял с продажи аккаунт #{account_id}")

# ==================== ПОПОЛНЕНИЕ БАЛАНСА ====================
@router.callback_query(F.data == "add_bal")
async def add_bal(callback: CallbackQuery):
    """Меню пополнения баланса"""
    if is_user_banned(callback.from_user.id):
        await callback.answer("Вы заблокированы в боте", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{em('star')} <b>Пополнение баланса</b>\n\n"
        f"Выберите способ пополнения:",
        reply_markup=add_bal_kb()
    )

@router.callback_query(F.data == "bal_stars")
async def bal_stars(callback: CallbackQuery, state: FSMContext):
    """Пополнение через звёзды Telegram"""
    await callback.message.edit_text(
        f"{em('star')} Введите сумму пополнения в рублях (минимум 1):\n"
        f"Курс: 1₽ = 1⭐",
        reply_markup=back_kb()
    )
    await state.set_state(BuyAccount.amount)

@router.message(StateFilter(BuyAccount.amount))
async def bal_amount(message: Message, state: FSMContext):
    """Обработка суммы пополнения через звёзды"""
    try:
        amount = int(message.text.strip())
        if amount < 1:
            raise ValueError("Сумма должна быть больше 0")
    except ValueError:
        await message.answer(
            f"{em('cross')} Введите целое число больше 0"
        )
        return
    
    # Создаём счёт на оплату звёздами
    await message.answer_invoice(
        title="Пополнение баланса",
        description=f"Пополнение баланса на {amount} ₽",
        payload=f"bal_{amount}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{amount} ₽", amount=amount * STARS_RATE)],
        provider_token="",
    )
    
    await state.clear()
    logger.info(f"Пользователь {message.from_user.id} запросил пополнение на {amount}₽ через звёзды")

@router.pre_checkout_query()
async def pre_chk(pre_checkout_query: PreCheckoutQuery):
    """Обработчик предварительной проверки платежа"""
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def success_pay(message: Message):
    """Обработчик успешного платежа звёздами"""
    payload = message.successful_payment.invoice_payload
    
    if payload.startswith("bal_"):
        amount = int(payload.split("_")[1])
        
        # Начисляем средства
        update_balance(message.from_user.id, amount)
        add_transaction(
            message.from_user.id, "deposit_stars", amount,
            "Пополнение через звёзды Telegram"
        )
        
        # Получаем обновленный баланс
        user = get_user(message.from_user.id)
        
        await message.answer(
            f"{em('check')} <b>Баланс пополнен!</b>\n\n"
            f"{em('money')} Зачислено: {amount} ₽\n"
            f"{em('wallet')} Текущий баланс: {user[3]} ₽",
            reply_markup=main_menu()
        )
        
        logger.info(f"Пользователь {message.from_user.id} пополнил баланс на {amount}₽ через звёзды")

@router.callback_query(F.data == "bal_crypto")
async def bal_crypto(callback: CallbackQuery, state: FSMContext):
    """Пополнение через Crypto Bot"""
    await callback.message.edit_text(
        f"{em('crypto')} Введите сумму пополнения в рублях:",
        reply_markup=back_kb()
    )
    await state.set_state(BuyAccount.crypto_amount)

@router.message(StateFilter(BuyAccount.crypto_amount))
async def crypto_amount(message: Message, state: FSMContext):
    """Обработка суммы для крипто-пополнения"""
    try:
        amount = int(message.text.strip())
        if amount < 1:
            raise ValueError
    except ValueError:
        await message.answer(f"{em('cross')} Введите целое число больше 0")
        return
    
    await state.update_data(crypto_rub=amount)
    await message.answer(
        f"{em('crypto')} Сумма: {amount} ₽\n"
        f"Выберите криптовалюту для оплаты:",
        reply_markup=crypto_curr_kb(amount)
    )

@router.callback_query(F.data.startswith("crypto_"))
async def crypto_create(callback: CallbackQuery):
    """Создание крипто-счёта"""
    parts = callback.data.split("_")
    currency = parts[1]
    amount = int(parts[2])
    
    await callback.message.edit_text(
        f"{em('clock')} Создаю счёт на оплату..."
    )
    
    result = await create_crypto_invoice(amount, currency)
    
    if result.get("success"):
        # Сохраняем информацию о счёте
        crypto_invoices[result["invoice_id"]] = {
            "user_id": callback.from_user.id,
            "amount": amount
        }
        
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(
            text="Оплатить",
            url=result["pay_url"],
            style="primary"
        ))
        kb.row(InlineKeyboardButton(
            text="Проверить оплату",
            callback_data=f"check_crypto_{result['invoice_id']}_{amount}",
            style="success"
        ))
        kb.row(InlineKeyboardButton(
            text="↩️ Назад",
            callback_data="add_bal",
            style="default"
        ))
        
        await callback.message.edit_text(
            f"{em('crypto')} <b>Счёт создан!</b>\n\n"
            f"Сумма: {amount} ₽\n"
            f"К оплате: {result['crypto_amount']} {currency}\n\n"
            f"Нажмите «Оплатить» для перехода к оплате,\n"
            f"затем «Проверить оплату» для зачисления средств.",
            reply_markup=kb.as_markup()
        )
    else:
        await callback.message.edit_text(
            f"{em('cross')} Ошибка при создании счёта:\n"
            f"{result.get('error', 'Неизвестная ошибка')}",
            reply_markup=back_kb()
        )

@router.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto(callback: CallbackQuery):
    """Проверка оплаты крипто-счёта"""
    parts = callback.data.split("_")
    invoice_id = int(parts[2])
    amount = int(parts[3])
    
    status = await check_crypto_invoice(invoice_id)
    
    if status == "paid":
        # Начисляем средства
        update_balance(callback.from_user.id, amount)
        add_transaction(
            callback.from_user.id, "deposit_crypto", amount,
            f"Пополнение через Crypto Bot #{invoice_id}"
        )
        
        user = get_user(callback.from_user.id)
        await callback.message.edit_text(
            f"{em('check')} <b>Оплата получена!</b>\n\n"
            f"{em('money')} Зачислено: {amount} ₽\n"
            f"{em('wallet')} Текущий баланс: {user[3]} ₽",
            reply_markup=main_menu()
        )
    elif status == "active":
        await callback.answer("Счёт ещё не оплачен", show_alert=True)
    else:
        await callback.answer("Ошибка при проверке оплаты", show_alert=True)

# ==================== АДМИН-ПАНЕЛЬ ====================
@router.callback_query(F.data == "adm_bal")
async def adm_bal(callback: CallbackQuery, state: FSMContext):
    """Начало изменения баланса пользователя"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к админ-панели", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{em('wallet')} <b>Изменение баланса</b>\n\n"
        f"Введите Telegram ID пользователя:",
        reply_markup=back_kb()
    )
    await state.set_state(AdminStates.uid)

@router.message(StateFilter(AdminStates.uid))
async def adm_uid(message: Message, state: FSMContext):
    """Обработка ввода ID пользователя"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer(f"{em('cross')} Введите корректный числовой ID")
        return
    
    user = get_user(user_id)
    if not user:
        await message.answer(
            f"{em('cross')} Пользователь с ID {user_id} не найден"
        )
        await state.clear()
        return
    
    await state.update_data(auid=user_id)
    
    await message.answer(
        f"{em('profile')} <b>Пользователь найден:</b>\n\n"
        f"ID: {user[1]}\n"
        f"Username: {user[2] or 'Не указан'}\n"
        f"{em('wallet')} Баланс: {user[3]} ₽\n"
        f"{em('frozen')} Заморожено: {user[4]} ₽\n"
        f"Статус: {'🚫 Заблокирован' if user[7] else '✅ Активен'}\n\n"
        f"Введите сумму для изменения:\n"
        f"(положительное число — добавить, отрицательное — списать):"
    )
    await state.set_state(AdminStates.amount)

@router.message(StateFilter(AdminStates.amount))
async def adm_amount(message: Message, state: FSMContext):
    """Выполнение изменения баланса"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer(f"{em('cross')} Введите целое число")
        return
    
    data = await state.get_data()
    user_id = data["auid"]
    
    # Изменяем баланс
    update_balance(user_id, amount)
    add_transaction(
        user_id, "admin_change", amount,
        f"Изменение баланса администратором {message.from_user.id}"
    )
    
    # Получаем обновленные данные
    user = get_user(user_id)
    
    await message.answer(
        f"{em('check')} <b>Баланс изменён!</b>\n\n"
        f"Пользователь: {user[2] or user_id}\n"
        f"Изменение: {'+' if amount > 0 else ''}{amount} ₽\n"
        f"{em('wallet')} Новый баланс: {user[3]} ₽",
        reply_markup=main_menu()
    )
    
    logger.info(f"Админ {message.from_user.id} изменил баланс пользователя {user_id} на {amount}₽")
    await state.clear()

@router.callback_query(F.data == "adm_users")
async def adm_users(callback: CallbackQuery):
    """Показывает список всех пользователей"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к админ-панели", show_alert=True)
        return
    
    users = get_all_users()
    
    kb = InlineKeyboardBuilder()
    for user in users[:20]:  # Показываем первых 20
        ban_status = "🚫" if user[7] else "✅"
        username = user[2] or f"ID:{user[1]}"
        kb.row(InlineKeyboardButton(
            text=f"{ban_status} {username} | {user[3]}₽",
            callback_data=f"adm_user_{user[1]}",
            style="default"
        ))
    
    kb.row(InlineKeyboardButton(
        text="↩️ Назад",
        callback_data="main",
        style="default"
    ))
    
    await callback.message.edit_text(
        f"{em('people')} <b>Пользователи бота:</b>\n"
        f"Всего: {len(users)}",
        reply_markup=kb.as_markup()
    )

@router.callback_query(F.data.startswith("adm_user_"))
async def adm_user_view(callback: CallbackQuery):
    """Просмотр профиля пользователя админом"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к админ-панели", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    user = get_user(user_id)
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    kb = InlineKeyboardBuilder()
    
    # Кнопка бана/разбана
    if user[7]:
        kb.row(InlineKeyboardButton(
            text="Разблокировать",
            callback_data=f"adm_unban_{user_id}",
            icon_custom_emoji_id=EMOJI["unban"],
            style="success"
        ))
    else:
        kb.row(InlineKeyboardButton(
            text="Заблокировать",
            callback_data=f"adm_ban_{user_id}",
            icon_custom_emoji_id=EMOJI["ban"],
            style="danger"
        ))
    
    # Кнопка изменения баланса
    kb.row(InlineKeyboardButton(
        text="Изменить баланс",
        callback_data=f"adm_bal_user_{user_id}",
        style="primary"
    ))
    
    kb.row(InlineKeyboardButton(
        text="↩️ Назад к списку",
        callback_data="adm_users",
        style="default"
    ))
    
    text = (
        f"{em('profile')} <b>Профиль пользователя</b>\n\n"
        f"Telegram ID: {user[1]}\n"
        f"Username: {user[2] or 'Не указан'}\n"
        f"{em('wallet')} Баланс: {user[3]} ₽\n"
        f"{em('frozen')} Заморожено: {user[4]} ₽\n"
        f"Рейтинг: {user[5]:.1f} ({user[6]} отзывов)\n"
        f"Статус: {'🚫 Заблокирован' if user[7] else '✅ Активен'}"
    )
    
    if user[7] and user[8]:
        text += f"\nПричина бана: {user[8]}"
    if user[9]:
        text += f"\nЗабанен до: {user[9].strftime('%d.%m.%Y %H:%M')}"
    
    await callback.message.edit_text(text, reply_markup=kb.as_markup())

@router.callback_query(F.data.startswith("adm_ban_"))
async def adm_ban(callback: CallbackQuery, state: FSMContext):
    """Блокировка пользователя"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к админ-панели", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    await state.update_data(ban_uid=user_id)
    
    await callback.message.edit_text(
        f"{em('ban')} Введите причину блокировки:",
        reply_markup=back_kb()
    )
    await state.set_state(AdminStates.ban_reason)

@router.message(StateFilter(AdminStates.ban_reason))
async def adm_ban_reason(message: Message, state: FSMContext):
    """Сохранение причины бана"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    reason = message.text.strip()
    data = await state.get_data()
    
    ban_user(data["ban_uid"], reason)
    
    await message.answer(
        f"{em('check')} Пользователь заблокирован!\n"
        f"Причина: {reason}",
        reply_markup=main_menu()
    )
    await state.clear()
    
    logger.info(f"Админ {message.from_user.id} заблокировал пользователя {data['ban_uid']}")

@router.callback_query(F.data.startswith("adm_unban_"))
async def adm_unban(callback: CallbackQuery):
    """Разблокировка пользователя"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к админ-панели", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[2])
    unban_user(user_id)
    
    await callback.message.edit_text(
        f"{em('check')} Пользователь разблокирован!",
        reply_markup=main_menu()
    )
    
    logger.info(f"Админ {callback.from_user.id} разблокировал пользователя {user_id}")

@router.callback_query(F.data == "adm_crypto")
async def adm_crypto(callback: CallbackQuery, state: FSMContext):
    """Установка токена Crypto Bot"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к админ-панели", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{em('crypto')} Введите API токен Crypto Bot:\n"
        f"Текущий токен: {'Установлен' if CRYPTO_BOT_TOKEN else 'Не установлен'}",
        reply_markup=back_kb()
    )
    await state.set_state(AdminStates.crypto_token)

@router.message(StateFilter(AdminStates.crypto_token))
async def adm_crypto_set(message: Message, state: FSMContext):
    """Сохранение токена Crypto Bot"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    global CRYPTO_BOT_TOKEN
    CRYPTO_BOT_TOKEN = message.text.strip()
    
    await message.answer(
        f"{em('check')} Токен Crypto Bot сохранён!",
        reply_markup=main_menu()
    )
    await state.clear()
    
    logger.info(f"Админ {message.from_user.id} обновил токен Crypto Bot")

@router.callback_query(F.data == "adm_stat")
async def adm_stat(callback: CallbackQuery):
    """Показывает статистику бота"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к админ-панели", show_alert=True)
        return
    
    # Собираем статистику
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM accounts WHERE status='active'")
    active_accounts = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM accounts WHERE status='sold'")
    sold_accounts = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM purchases")
    total_purchases = cur.fetchone()[0]
    
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type LIKE 'deposit%'")
    total_deposits = cur.fetchone()[0]
    
    cur.execute("SELECT COALESCE(SUM(frozen_balance), 0) FROM users")
    total_frozen = cur.fetchone()[0]
    
    stats_text = (
        f"{em('stats')} <b>Статистика бота:</b>\n\n"
        f"{em('profile')} Пользователей: {total_users}\n"
        f"{em('tag')} Активных объявлений: {active_accounts}\n"
        f"{em('check')} Продано аккаунтов: {sold_accounts}\n"
        f"{em('box')} Всего покупок: {total_purchases}\n"
        f"{em('money')} Всего пополнено: {total_deposits} ₽\n"
        f"{em('frozen')} Заморожено средств: {total_frozen} ₽"
    )
    
    await callback.message.edit_text(
        stats_text,
        reply_markup=back_kb()
    )

# ==================== ЗАГЛУШКА ДЛЯ НЕАКТИВНЫХ КНОПОК ====================
@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    """Заглушка для неактивных кнопок"""
    await callback.answer()

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Главная функция запуска бота"""
    # Инициализируем базу данных
    init_db()
    logger.info("База данных инициализирована")
    
    # Запускаем фоновые задачи
    asyncio.create_task(background_tasks())
    logger.info("Фоновые задачи запущены")
    
    # Запускаем бота
    logger.info("Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка при запуске бота: {e}")
