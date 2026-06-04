import os
import re
import asyncio
import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv
import psycopg2
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
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery,
)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode

# Загрузка переменных окружения
load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_IDS = [7973988177]
SUPPORT_LINK = "https://t.me/VestMarketSupport"
API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== PREMIUM EMOJI IDS ====================
PREMIUM_EMOJI = {
    "profile": "5870994129244131212",      # 👤
    "wallet": "5769126056262898415",        # 👛
    "money": "5904462880941545555",         # 🪙
    "sell": "5890848474563352982",          # 📤
    "buy": "5879814368572478751",           # 🏧
    "star": "5373141891321699086",          # ⭐
    "check": "5870633910337015697",         # ✅
    "cross": "5870657884844462243",         # ❌
    "lock": "6037249452824072506",          # 🔒
    "globe": "6042011682497106307",         # 📍
    "box": "5884479287171485878",           # 📦
    "gift": "6032644646587338669",          # 🎁
    "clock": "5983150113483134607",         # ⏰
    "send": "5963103826075456248",          # ⬆
    "download": "6039802767931481871",      # ⬇
    "info": "6028435952299413210",          # ℹ
    "bot": "6030400221232501136",           # 🤖
    "tag": "5886285355279193209",           # 🏷
    "trash": "5870875489362513438",         # 🗑
    "edit": "5870676941614354370",          # 🖋
    "phone": "5870528606328852614",         # 📁
    "people": "5870772616305839506",        # 👥
    "filter": "5870930636742595124",        # 📊
    "stats": "5870921681735781843",         # 📊
    "frozen": "6037249452824072506",        # 🔒
    "settings": "5870982283724328568",      # ⚙
    "house": "5873147866364514353",         # 🏘
    "rocket": "6039422865189638057",        # 📣
}

# Функция для генерации premium emoji в HTML
def premium_emoji(emoji_name: str) -> str:
    """Возвращает HTML-код для premium emoji"""
    emoji_map = {
        "profile": "👤", "wallet": "👛", "money": "🪙", "sell": "📤",
        "buy": "🏧", "star": "⭐", "check": "✅", "cross": "❌",
        "lock": "🔒", "globe": "📍", "box": "📦", "gift": "🎁",
        "clock": "⏰", "send": "⬆", "download": "⬇", "info": "ℹ",
        "bot": "🤖", "tag": "🏷", "trash": "🗑", "edit": "🖋",
        "phone": "📁", "people": "👥", "filter": "📊", "stats": "📊",
        "frozen": "🔒", "settings": "⚙", "house": "🏘", "rocket": "📣",
    }
    
    emoji_id = PREMIUM_EMOJI.get(emoji_name, "")
    emoji_char = emoji_map.get(emoji_name, "")
    
    if emoji_id:
        return f'<tg-emoji emoji-id="{emoji_id}">{emoji_char}</tg-emoji>'
    return emoji_char

# Коды стран для определения по номеру телефона
COUNTRY_CODES = {
    '7': 'Россия',
    '380': 'Украина',
    '375': 'Беларусь',
    '1': 'USA',
    '44': 'UK',
    '49': 'Германия',
    '33': 'Франция',
    '39': 'Италия',
    '34': 'Испания',
    '31': 'Нидерланды',
    '48': 'Польша',
    '90': 'Турция',
    '52': 'Мексика',
    '55': 'Бразилия',
    '91': 'Индия',
    '86': 'Китай',
    '81': 'Япония',
    '82': 'Корея',
    '234': 'Нигерия',
    '20': 'Египет',
    '998': 'Узбекистан',
    '77': 'Казахстан',
    '996': 'Киргизия',
    '373': 'Молдова',
    '374': 'Армения',
    '994': 'Азербайджан',
    '995': 'Грузия',
    '371': 'Латвия',
    '370': 'Литва',
    '372': 'Эстония',
    '40': 'Румыния',
    '36': 'Венгрия',
    '420': 'Чехия',
    '421': 'Словакия',
    '386': 'Словения',
    '385': 'Хорватия',
    '381': 'Сербия',
    '359': 'Болгария',
    '30': 'Греция',
    '46': 'Швеция',
    '47': 'Норвегия',
    '45': 'Дания',
    '358': 'Финляндия',
    '61': 'Австралия',
    '64': 'Новая Зеландия',
    '972': 'Израиль',
    '971': 'ОАЭ',
    '966': 'Саудовская Аравия',
    '63': 'Филиппины',
    '84': 'Вьетнам',
    '66': 'Таиланд',
    '62': 'Индонезия',
    '60': 'Малайзия',
    '65': 'Сингапур',
}

def get_country_from_phone(phone: str) -> str:
    """Определяет страну по коду номера телефона"""
    phone = phone.strip().lstrip('+')
    # Сортируем коды по длине (от длинных к коротким)
    for code in sorted(COUNTRY_CODES.keys(), key=len, reverse=True):
        if phone.startswith(code):
            return COUNTRY_CODES[code]
    return "Неизвестно"

# ==================== БАЗА ДАННЫХ ====================
# Подключение к PostgreSQL
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

def init_db():
    """Инициализация базы данных - пересоздание всех таблиц"""
    logger.info("Начинаем инициализацию базы данных...")
    
    # Удаляем таблицы в правильном порядке (с учетом внешних ключей)
    cur.execute("DROP TABLE IF EXISTS reviews CASCADE")
    cur.execute("DROP TABLE IF EXISTS transactions CASCADE")
    cur.execute("DROP TABLE IF EXISTS purchases CASCADE")
    cur.execute("DROP TABLE IF EXISTS accounts CASCADE")
    cur.execute("DROP TABLE IF EXISTS users CASCADE")
    
    # Создаем таблицы заново с правильной структурой
    cur.execute("""
    -- Таблица пользователей
    CREATE TABLE users (
        id SERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        username TEXT,
        balance INTEGER DEFAULT 0,
        frozen_balance INTEGER DEFAULT 0,
        rating FLOAT DEFAULT 0.0,
        total_reviews INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    -- Таблица аккаунтов (товаров)
    CREATE TABLE accounts (
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
    
    -- Таблица покупок
    CREATE TABLE purchases (
        id SERIAL PRIMARY KEY,
        buyer_id BIGINT NOT NULL,
        account_id INTEGER NOT NULL,
        purchased_at TIMESTAMP DEFAULT NOW()
    );
    
    -- Таблица отзывов
    CREATE TABLE reviews (
        id SERIAL PRIMARY KEY,
        purchase_id INTEGER NOT NULL,
        rating INTEGER CHECK (rating >= 1 AND rating <= 5),
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    -- Таблица транзакций
    CREATE TABLE transactions (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        type TEXT NOT NULL,
        amount INTEGER NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    -- Индексы для ускорения запросов
    CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);
    CREATE INDEX IF NOT EXISTS idx_accounts_seller ON accounts(seller_id);
    CREATE INDEX IF NOT EXISTS idx_accounts_valid ON accounts(is_valid);
    CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_id);
    CREATE INDEX IF NOT EXISTS idx_purchases_buyer ON purchases(buyer_id);
    CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
    """)
    
    logger.info("База данных успешно инициализирована")

# ==================== ФУНКЦИИ ДЛЯ РАБОТЫ С БД ====================

def get_user(telegram_id: int):
    """Получает пользователя по telegram_id"""
    cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    return cur.fetchone()

def create_user(telegram_id: int, username: str = None):
    """Создает нового пользователя"""
    cur.execute(
        "INSERT INTO users (telegram_id, username) VALUES (%s, %s) ON CONFLICT (telegram_id) DO NOTHING",
        (telegram_id, username)
    )

def update_balance(telegram_id: int, amount: int):
    """Обновляет баланс пользователя"""
    cur.execute(
        "UPDATE users SET balance = balance + %s WHERE telegram_id = %s",
        (amount, telegram_id)
    )

def freeze_balance(telegram_id: int, amount: int):
    """Замораживает средства на балансе"""
    cur.execute(
        "UPDATE users SET frozen_balance = frozen_balance + %s WHERE telegram_id = %s",
        (amount, telegram_id)
    )

def release_hold(telegram_id: int, amount: int):
    """Размораживает средства и начисляет на баланс"""
    cur.execute(
        "UPDATE users SET frozen_balance = frozen_balance - %s, balance = balance + %s WHERE telegram_id = %s",
        (amount, amount, telegram_id)
    )

def add_transaction(user_id: int, t_type: str, amount: int, description: str = None):
    """Добавляет запись о транзакции"""
    cur.execute(
        "INSERT INTO transactions (user_id, type, amount, description) VALUES (%s, %s, %s, %s)",
        (user_id, t_type, amount, description)
    )

def process_expired_holds():
    """Обрабатывает истекшие холды (замороженные средства)"""
    cur.execute("""
        SELECT id, seller_id, price 
        FROM accounts 
        WHERE status = 'sold' 
        AND hold_until IS NOT NULL 
        AND hold_until <= NOW()
    """)
    expired_holds = cur.fetchall()
    
    for hold in expired_holds:
        try:
            release_hold(hold[1], hold[2])
            add_transaction(hold[1], "sale_released", hold[2], f"Разморозка средств за аккаунт #{hold[0]}")
            cur.execute("UPDATE accounts SET hold_until = NULL WHERE id = %s", (hold[0],))
            logger.info(f"Холд разморожен: аккаунт #{hold[0]}, сумма {hold[2]}")
        except Exception as e:
            logger.error(f"Ошибка при разморозке холда #{hold[0]}: {e}")

def add_account(seller_id: int, title: str, phone: str, password_2fa: str, 
                session_string: str, country: str, description: str, price: int,
                auto_username: str = None, auto_firstname: str = None, 
                auto_lastname: str = None, auto_2fa: bool = False):
    """Добавляет новый аккаунт в базу"""
    cur.execute("""
        INSERT INTO accounts (
            seller_id, title, phone, password_2fa, session_string, 
            country, description, price, status, is_valid,
            auto_username, auto_firstname, auto_lastname, auto_2fa
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', TRUE, %s, %s, %s, %s)
        RETURNING id
    """, (seller_id, title, phone, password_2fa, session_string, 
          country, description, price, auto_username, auto_firstname, 
          auto_lastname, auto_2fa))
    return cur.fetchone()[0]

def get_available_accounts(country_filter: str = None, price_from: int = None,
                          price_to: int = None, has_2fa: bool = None):
    """Получает список доступных для покупки аккаунтов с фильтрами"""
    query = """
        SELECT a.*, u.rating as seller_rating
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
    """Получает информацию об аккаунте по ID"""
    cur.execute("SELECT * FROM accounts WHERE id = %s", (account_id,))
    return cur.fetchone()

def buy_account(account_id: int, buyer_id: int):
    """Покупка аккаунта - меняет статус и создает холд"""
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
    """Получает список покупок пользователя"""
    cur.execute("""
        SELECT 
            p.id, p.buyer_id, p.account_id, p.purchased_at,
            a.phone, a.password_2fa, a.session_string, a.country, 
            a.description, a.title, a.auto_username, a.auto_firstname, 
            a.auto_lastname, a.auto_2fa
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
            p.id, p.buyer_id, p.account_id, p.purchased_at,
            a.phone, a.password_2fa, a.session_string, a.country, 
            a.description, a.title, a.auto_username, a.auto_firstname, 
            a.auto_lastname, a.auto_2fa
        FROM purchases p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.id = %s
    """, (purchase_id,))
    return cur.fetchone()

def add_review(purchase_id: int, rating: int):
    """Добавляет отзыв о покупке и обновляет рейтинг продавца"""
    cur.execute(
        "INSERT INTO reviews (purchase_id, rating) VALUES (%s, %s)",
        (purchase_id, rating)
    )
    # Обновляем рейтинг продавца
    cur.execute("""
        UPDATE users 
        SET 
            total_reviews = COALESCE(total_reviews, 0) + 1,
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
    cur.execute("SELECT id FROM reviews WHERE purchase_id = %s", (purchase_id,))
    return cur.fetchone() is not None

def get_seller_accounts(seller_id: int):
    """Получает активные аккаунты продавца"""
    cur.execute(
        "SELECT * FROM accounts WHERE seller_id = %s AND status = 'active' ORDER BY created_at DESC",
        (seller_id,)
    )
    return cur.fetchall()

def get_seller_stats(seller_id: int):
    """Получает статистику продавца"""
    cur.execute(
        "SELECT COUNT(*) FROM accounts WHERE seller_id = %s AND status = 'sold'",
        (seller_id,)
    )
    total_sold = cur.fetchone()[0]
    
    cur.execute(
        "SELECT COUNT(*) FROM accounts WHERE seller_id = %s AND status = 'active'",
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
        "UPDATE accounts SET status = 'removed' WHERE id = %s AND seller_id = %s",
        (account_id, seller_id)
    )

# ==================== BOT ИНИЦИАЛИЗАЦИЯ ====================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ==================== TELEPHON КЛИЕНТ ====================
async def create_telethon_client(session_string: str = None):
    """Создает клиент Telethon для работы с аккаунтами"""
    if session_string:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    else:
        client = TelegramClient(StringSession(), API_ID, API_HASH)
    return client

async def verify_account(session_string: str = None, phone: str = None) -> dict:
    """
    Проверяет валидность аккаунта Telegram.
    Возвращает словарь с результатом проверки.
    """
    client = await create_telethon_client(session_string)
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            # Если нет сессии - отправляем код подтверждения
            if not session_string:
                sent_code = await client.send_code_request(phone)
                new_session = client.session.save()
                await client.disconnect()
                return {
                    "valid": True,
                    "need_code": True,
                    "session_string": new_session,
                    "phone_code_hash": sent_code.phone_code_hash,
                    "error": None,
                    "user_info": None
                }
            else:
                await client.disconnect()
                return {
                    "valid": False,
                    "need_code": False,
                    "session_string": None,
                    "error": "Сессия не авторизована",
                    "user_info": None
                }
        
        # Получаем информацию о пользователе
        me = await client.get_me()
        user_info = {
            "username": me.username,
            "first_name": me.first_name,
            "last_name": me.last_name,
            "has_2fa": False
        }
        
        new_session = client.session.save()
        await client.disconnect()
        
        return {
            "valid": True,
            "need_code": False,
            "session_string": new_session,
            "error": None,
            "user_info": user_info
        }
        
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        return {
            "valid": False,
            "need_code": False,
            "session_string": None,
            "error": str(e),
            "user_info": None
        }

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
        return {
            "success": True,
            "session_string": session_string,
            "need_2fa": True,
            "user_info": None
        }
    except PhoneCodeInvalidError:
        await client.disconnect()
        return {"success": False, "error": "Неверный код подтверждения"}
    except PhoneCodeExpiredError:
        await client.disconnect()
        return {"success": False, "error": "Код подтверждения истек"}
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

# ==================== СОСТОЯНИЯ FSM ====================
class SellAccountStates(StatesGroup):
    """Состояния для процесса продажи аккаунта"""
    waiting_for_phone = State()
    waiting_for_code = State()
    waiting_for_2fa = State()
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_price = State()

class BuyAccountStates(StatesGroup):
    """Состояния для процесса покупки"""
    waiting_for_amount = State()

class AdminStates(StatesGroup):
    """Состояния для админ-панели"""
    waiting_for_user_id = State()
    waiting_for_amount = State()

class FilterStates(StatesGroup):
    """Состояния для фильтров"""
    waiting_for_country = State()
    waiting_for_price_from = State()
    waiting_for_price_to = State()

# ==================== КЛАВИАТУРЫ ====================
def get_main_menu_keyboard():
    """Главное меню бота"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Продать аккаунт",
            callback_data="menu_sell",
            icon_custom_emoji_id=PREMIUM_EMOJI["sell"]
        )],
        [InlineKeyboardButton(
            text="Купить аккаунт",
            callback_data="menu_buy",
            icon_custom_emoji_id=PREMIUM_EMOJI["buy"]
        )],
        [InlineKeyboardButton(
            text="Профиль",
            callback_data="menu_profile",
            icon_custom_emoji_id=PREMIUM_EMOJI["profile"]
        )],
    ])

def get_profile_keyboard():
    """Клавиатура профиля"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Пополнить баланс",
            callback_data="profile_add_balance",
            icon_custom_emoji_id=PREMIUM_EMOJI["star"]
        )],
        [InlineKeyboardButton(
            text="Мои покупки",
            callback_data="profile_purchases",
            icon_custom_emoji_id=PREMIUM_EMOJI["box"]
        )],
        [InlineKeyboardButton(
            text="Мои объявления",
            callback_data="profile_listings",
            icon_custom_emoji_id=PREMIUM_EMOJI["tag"]
        )],
        [InlineKeyboardButton(
            text="Вывод средств",
            url=SUPPORT_LINK,
            icon_custom_emoji_id=PREMIUM_EMOJI["money"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="nav_back_to_main"
        )],
    ])

def get_back_keyboard():
    """Клавиатура с кнопкой Назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Назад",
            callback_data="nav_back_to_main"
        )]
    ])

def get_accounts_list_keyboard(accounts):
    """Клавиатура со списком доступных аккаунтов"""
    buttons = []
    
    for acc in accounts:
        # acc[2] = title, acc[8] = price
        title = acc[2] if acc[2] else "Без названия"
        price = acc[8] if acc[8] else 0
        buttons.append([InlineKeyboardButton(
            text=f"{title} | {price}⭐",
            callback_data=f"buy_view_{acc[0]}",
            icon_custom_emoji_id=PREMIUM_EMOJI["globe"]
        )])
    
    buttons.append([InlineKeyboardButton(
        text="Фильтры",
        callback_data="buy_filters",
        icon_custom_emoji_id=PREMIUM_EMOJI["filter"]
    )])
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data="nav_back_to_main"
    )])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_account_view_keyboard(account_id: int, seller_id: int):
    """Клавиатура просмотра аккаунта"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Проверить и купить",
            callback_data=f"buy_check_{account_id}",
            icon_custom_emoji_id=PREMIUM_EMOJI["buy"]
        )],
        [InlineKeyboardButton(
            text="Профиль продавца",
            callback_data=f"seller_profile_{seller_id}",
            icon_custom_emoji_id=PREMIUM_EMOJI["people"]
        )],
        [InlineKeyboardButton(
            text="Назад к списку",
            callback_data="nav_back_to_list"
        )],
    ])

def get_confirm_buy_keyboard(account_id: int):
    """Клавиатура подтверждения покупки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Купить",
            callback_data=f"buy_confirm_{account_id}",
            icon_custom_emoji_id=PREMIUM_EMOJI["buy"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data=f"buy_view_{account_id}"
        )],
    ])

def get_seller_profile_keyboard(seller_id: int):
    """Клавиатура профиля продавца"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Аккаунты продавца",
            callback_data=f"seller_accounts_{seller_id}",
            icon_custom_emoji_id=PREMIUM_EMOJI["box"]
        )],
        [InlineKeyboardButton(
            text="Назад к списку",
            callback_data="nav_back_to_list"
        )],
    ])

def get_filter_keyboard():
    """Клавиатура фильтров"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="По стране",
            callback_data="filter_country",
            icon_custom_emoji_id=PREMIUM_EMOJI["globe"]
        )],
        [InlineKeyboardButton(
            text="По цене (от)",
            callback_data="filter_price_from",
            icon_custom_emoji_id=PREMIUM_EMOJI["money"]
        )],
        [InlineKeyboardButton(
            text="По цене (до)",
            callback_data="filter_price_to",
            icon_custom_emoji_id=PREMIUM_EMOJI["money"]
        )],
        [InlineKeyboardButton(
            text="Только с 2FA",
            callback_data="filter_2fa_yes",
            icon_custom_emoji_id=PREMIUM_EMOJI["lock"]
        )],
        [InlineKeyboardButton(
            text="Только без 2FA",
            callback_data="filter_2fa_no",
            icon_custom_emoji_id=PREMIUM_EMOJI["check"]
        )],
        [InlineKeyboardButton(
            text="Сбросить фильтры",
            callback_data="filter_reset"
        )],
        [InlineKeyboardButton(
            text="Назад к списку",
            callback_data="nav_back_to_list"
        )],
    ])

def get_purchase_keyboard(purchase_id: int):
    """Клавиатура для просмотра покупки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Получить код",
            callback_data=f"purchase_code_{purchase_id}",
            icon_custom_emoji_id=PREMIUM_EMOJI["download"]
        )],
        [InlineKeyboardButton(
            text="Оставить отзыв",
            callback_data=f"purchase_review_{purchase_id}",
            icon_custom_emoji_id=PREMIUM_EMOJI["edit"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="nav_back_to_profile"
        )],
    ])

def get_review_keyboard(purchase_id: int):
    """Клавиатура для выставления оценки"""
    buttons = []
    row = []
    for i in range(1, 6):
        row.append(InlineKeyboardButton(
            text=str(i),
            callback_data=f"review_rate_{purchase_id}_{i}",
            icon_custom_emoji_id=PREMIUM_EMOJI["star"]
        ))
    buttons.append(row)
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data=f"purchase_view_{purchase_id}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_my_listings_keyboard(accounts):
    """Клавиатура со списком моих объявлений"""
    buttons = []
    for acc in accounts:
        title = acc[2] if acc[2] else "Без названия"
        price = acc[8] if acc[8] else 0
        buttons.append([InlineKeyboardButton(
            text=f"{title} | {price}⭐",
            callback_data=f"listing_view_{acc[0]}",
            icon_custom_emoji_id=PREMIUM_EMOJI["tag"]
        )])
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data="nav_back_to_profile"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_listing_actions_keyboard(account_id: int):
    """Клавиатура действий с объявлением"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Снять с продажи",
            callback_data=f"listing_remove_{account_id}",
            icon_custom_emoji_id=PREMIUM_EMOJI["trash"]
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data="profile_listings"
        )],
    ])

def get_admin_keyboard():
    """Клавиатура админ-панели"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Изменить баланс",
            callback_data="admin_change_balance",
            icon_custom_emoji_id=PREMIUM_EMOJI["wallet"]
        )],
        [InlineKeyboardButton(
            text="Статистика",
            callback_data="admin_stats",
            icon_custom_emoji_id=PREMIUM_EMOJI["stats"]
        )],
    ])

# Глобальное хранилище фильтров пользователей
user_filters = {}

# ==================== ФОНОВЫЕ ЗАДАЧИ ====================
async def hold_checker():
    """Фоновая проверка истекших холдов каждые 60 секунд"""
    while True:
        try:
            process_expired_holds()
        except Exception as e:
            logger.error(f"Ошибка в hold_checker: {e}")
        await asyncio.sleep(60)

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
@router.message(Command("start"))
async def command_start(message: Message):
    """Обработчик команды /start"""
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username)
        logger.info(f"Создан новый пользователь: {message.from_user.id}")
    
    # Инициализируем фильтры для пользователя
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {}
    
    await message.answer(
        f"{premium_emoji('bot')} Добро пожаловать в <b>Маркетплейс Telegram аккаунтов</b>!\n\n"
        f"Здесь вы можете безопасно купить или продать аккаунты Telegram.\n\n"
        f"{premium_emoji('info')} Используйте кнопки ниже для навигации:",
        reply_markup=get_main_menu_keyboard()
    )

@router.message(Command("admin"))
async def command_admin(message: Message):
    """Обработчик команды /admin - вход в админ-панель"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    await message.answer(
        f"{premium_emoji('settings')} <b>Админ-панель</b>\n\n"
        f"Выберите действие:",
        reply_markup=get_admin_keyboard()
    )

# ==================== НАВИГАЦИЯ ====================
@router.callback_query(F.data == "nav_back_to_main")
async def nav_back_to_main(callback: CallbackQuery):
    """Возврат в главное меню"""
    await callback.message.edit_text(
        f"{premium_emoji('bot')} <b>Главное меню</b>\n\n"
        f"Выберите действие:",
        reply_markup=get_main_menu_keyboard()
    )

@router.callback_query(F.data == "nav_back_to_list")
async def nav_back_to_list(callback: CallbackQuery):
    """Возврат к списку аккаунтов"""
    await show_available_accounts(callback)

@router.callback_query(F.data == "nav_back_to_profile")
async def nav_back_to_profile(callback: CallbackQuery):
    """Возврат в профиль"""
    await show_profile(callback)

# ==================== ПРОФИЛЬ ====================
@router.callback_query(F.data == "menu_profile")
async def menu_profile(callback: CallbackQuery):
    """Открытие профиля"""
    await show_profile(callback)

async def show_profile(callback: CallbackQuery):
    """Показывает профиль пользователя"""
    user = get_user(callback.from_user.id)
    if not user:
        create_user(callback.from_user.id, callback.from_user.username)
        user = get_user(callback.from_user.id)
    
    # Индексы: 0=id, 1=telegram_id, 2=username, 3=balance, 4=frozen_balance, 5=rating, 6=total_reviews, 7=created_at
    balance = user[3]
    frozen = user[4]
    rating = user[5]
    total_reviews = user[6]
    
    # Формируем текст профиля
    rating_text = f"⭐ {rating:.1f}" if total_reviews > 0 else "Нет оценок"
    frozen_text = f"\n{premium_emoji('frozen')} Заморожено: {frozen} ⭐" if frozen > 0 else ""
    
    profile_text = (
        f"{premium_emoji('profile')} <b>Профиль</b>\n\n"
        f"{premium_emoji('wallet')} Баланс: {balance} ⭐"
        f"{frozen_text}\n"
        f"{rating_text} ({total_reviews} отзывов)"
    )
    
    await callback.message.edit_text(
        profile_text,
        reply_markup=get_profile_keyboard()
    )

# ==================== ПРОДАЖА АККАУНТА ====================
@router.callback_query(F.data == "menu_sell")
async def sell_account_start(callback: CallbackQuery, state: FSMContext):
    """Начало процесса продажи аккаунта"""
    await callback.message.edit_text(
        f"{premium_emoji('sell')} <b>Продажа аккаунта</b>\n\n"
        f"Введите номер телефона аккаунта в международном формате:\n"
        f"<code>+79991234567</code>",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(SellAccountStates.waiting_for_phone)

@router.message(StateFilter(SellAccountStates.waiting_for_phone))
async def sell_account_phone(message: Message, state: FSMContext):
    """Обработка ввода номера телефона"""
    phone = message.text.strip()
    
    # Валидация номера телефона
    if not re.match(r'^\+\d{7,15}$', phone):
        await message.answer(
            f"{premium_emoji('cross')} Неверный формат номера. "
            f"Используйте международный формат, например: +79991234567"
        )
        return
    
    await state.update_data(phone=phone)
    
    # Отправляем сообщение о проверке
    status_message = await message.answer(
        f"{premium_emoji('clock')} Проверяю аккаунт..."
    )
    
    # Проверяем аккаунт через Telethon
    result = await verify_account(phone=phone)
    
    if result.get("need_code"):
        # Требуется код подтверждения
        await state.update_data(
            session_string=result["session_string"],
            phone_code_hash=result["phone_code_hash"]
        )
        await status_message.edit_text(
            f"{premium_emoji('send')} Введите код подтверждения, "
            f"отправленный в Telegram (действителен 2 минуты):"
        )
        await state.set_state(SellAccountStates.waiting_for_code)
        
    elif result.get("valid"):
        # Аккаунт валиден, определяем страну
        await state.update_data(session_string=result["session_string"])
        country = get_country_from_phone(phone)
        await state.update_data(country=country)
        
        await status_message.edit_text(
            f"{premium_emoji('check')} Аккаунт валиден!\n"
            f"{premium_emoji('globe')} Страна определена: <b>{country}</b>\n\n"
            f"Введите название объявления (макс. 50 символов):"
        )
        await state.set_state(SellAccountStates.waiting_for_title)
        
    else:
        # Ошибка валидации
        await status_message.edit_text(
            f"{premium_emoji('cross')} Ошибка проверки аккаунта:\n"
            f"{result.get('error', 'Неизвестная ошибка')}",
            reply_markup=get_back_keyboard()
        )
        await state.clear()

@router.message(StateFilter(SellAccountStates.waiting_for_code))
async def sell_account_code(message: Message, state: FSMContext):
    """Обработка ввода кода подтверждения"""
    code = message.text.strip()
    data = await state.get_data()
    
    status_message = await message.answer(
        f"{premium_emoji('clock')} Проверяю код подтверждения..."
    )
    
    # Отправляем код на проверку
    result = await sign_in_with_code(
        data["session_string"],
        data["phone"],
        code,
        data["phone_code_hash"]
    )
    
    if result.get("success") and result.get("need_2fa"):
        # Требуется 2FA
        await state.update_data(session_string=result["session_string"])
        await status_message.edit_text(
            f"{premium_emoji('lock')} Введите пароль двухфакторной аутентификации "
            f"(если 2FA нет — напишите <b>нет</b>):"
        )
        await state.set_state(SellAccountStates.waiting_for_2fa)
        
    elif result.get("success"):
        # Успешный вход
        country = get_country_from_phone(data["phone"])
        await state.update_data(
            session_string=result["session_string"],
            country=country,
            auto_username=result["user_info"]["username"],
            auto_firstname=result["user_info"]["first_name"],
            auto_lastname=result["user_info"]["last_name"],
            auto_2fa=False
        )
        
        await status_message.edit_text(
            f"{premium_emoji('check')} Аккаунт подтверждён!\n"
            f"{premium_emoji('globe')} Страна: <b>{country}</b>\n\n"
            f"Введите название объявления (макс. 50 символов):"
        )
        await state.set_state(SellAccountStates.waiting_for_title)
        
    else:
        # Ошибка входа
        await status_message.edit_text(
            f"{premium_emoji('cross')} Ошибка: {result.get('error', 'Неверный код')}",
            reply_markup=get_back_keyboard()
        )
        await state.clear()

@router.message(StateFilter(SellAccountStates.waiting_for_2fa))
async def sell_account_2fa(message: Message, state: FSMContext):
    """Обработка ввода 2FA пароля"""
    password = message.text.strip()
    data = await state.get_data()
    
    if password.lower() == 'нет':
        password = None
    
    if password:
        status_message = await message.answer(
            f"{premium_emoji('clock')} Проверяю пароль 2FA..."
        )
        result = await sign_in_with_2fa(data["session_string"], password)
    else:
        result = {
            "success": True,
            "session_string": data["session_string"],
            "user_info": {
                "username": None,
                "first_name": None,
                "last_name": None,
                "has_2fa": False
            }
        }
        status_message = await message.answer(f"{premium_emoji('clock')} Обрабатываю...")
    
    if result.get("success"):
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
        
        await status_message.edit_text(
            f"{premium_emoji('check')} Аккаунт подтверждён!\n"
            f"{premium_emoji('globe')} Страна: <b>{country}</b>\n\n"
            f"Введите название объявления (макс. 50 символов):"
        )
        await state.set_state(SellAccountStates.waiting_for_title)
    else:
        await status_message.edit_text(
            f"{premium_emoji('cross')} Ошибка: {result.get('error', 'Неверный пароль 2FA')}",
            reply_markup=get_back_keyboard()
        )
        await state.clear()

@router.message(StateFilter(SellAccountStates.waiting_for_title))
async def sell_account_title(message: Message, state: FSMContext):
    """Обработка ввода названия объявления"""
    title = message.text.strip()
    
    if len(title) > 50:
        await message.answer(
            f"{premium_emoji('cross')} Название не должно превышать 50 символов. "
            f"Сейчас: {len(title)}"
        )
        return
    
    await state.update_data(title=title)
    
    await message.answer(
        f"{premium_emoji('edit')} Введите описание аккаунта (до 100 слов):"
    )
    await state.set_state(SellAccountStates.waiting_for_description)

@router.message(StateFilter(SellAccountStates.waiting_for_description))
async def sell_account_description(message: Message, state: FSMContext):
    """Обработка ввода описания"""
    description = message.text.strip()
    words = description.split()
    
    if len(words) > 100:
        await message.answer(
            f"{premium_emoji('cross')} Описание не должно превышать 100 слов. "
            f"Сейчас: {len(words)} слов."
        )
        return
    
    await state.update_data(description=description)
    
    await message.answer(
        f"{premium_emoji('money')} Введите цену аккаунта в звёздах (целое число):"
    )
    await state.set_state(SellAccountStates.waiting_for_price)

@router.message(StateFilter(SellAccountStates.waiting_for_price))
async def sell_account_price(message: Message, state: FSMContext):
    """Обработка ввода цены и завершение продажи"""
    try:
        price = int(message.text.strip())
        if price < 1:
            raise ValueError("Цена должна быть больше 0")
    except ValueError:
        await message.answer(
            f"{premium_emoji('cross')} Введите целое число больше 0"
        )
        return
    
    data = await state.get_data()
    
    # Формируем авто-описание с характеристиками
    auto_description = f"\n\n<b>Характеристики:</b>"
    if data.get("auto_username"):
        auto_description += f"\n• @{data['auto_username']}"
    if data.get("auto_firstname"):
        auto_description += f"\n• Имя: {data['auto_firstname']}"
    if data.get("auto_lastname"):
        auto_description += f"\n• Фамилия: {data['auto_lastname']}"
    auto_description += f"\n• 2FA: {'Есть' if data.get('auto_2fa') else 'Нет'}"
    
    full_description = data["description"] + auto_description
    
    # Добавляем аккаунт в базу данных
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
    
    # Уведомляем об успехе
    await message.answer(
        f"{premium_emoji('check')} <b>Аккаунт успешно выставлен на продажу!</b>\n\n"
        f"{premium_emoji('tag')} Название: {data['title']}\n"
        f"{premium_emoji('money')} Цена: {price} ⭐\n"
        f"{premium_emoji('globe')} Страна: {data['country']}",
        reply_markup=get_main_menu_keyboard()
    )
    
    logger.info(f"Пользователь {message.from_user.id} выставил аккаунт #{account_id} на продажу")
    await state.clear()

# ==================== ПОКУПКА АККАУНТА ====================
@router.callback_query(F.data == "menu_buy")
async def buy_account_list(callback: CallbackQuery):
    """Показ списка доступных аккаунтов"""
    await show_available_accounts(callback)

async def show_available_accounts(callback: CallbackQuery, filters: dict = None):
    """Отображает список доступных аккаунтов с учетом фильтров"""
    if filters is None:
        filters = user_filters.get(callback.from_user.id, {})
    
    # Получаем аккаунты с фильтрами
    accounts = get_available_accounts(
        country_filter=filters.get("country"),
        price_from=filters.get("price_from"),
        price_to=filters.get("price_to"),
        has_2fa=filters.get("has_2fa")
    )
    
    if not accounts:
        # Нет доступных аккаунтов
        await callback.message.edit_text(
            f"{premium_emoji('info')} Нет доступных аккаунтов для покупки.\n"
            f"Попробуйте сбросить фильтры или зайдите позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Фильтры",
                    callback_data="buy_filters",
                    icon_custom_emoji_id=PREMIUM_EMOJI["filter"]
                )],
                [InlineKeyboardButton(
                    text="Сбросить фильтры",
                    callback_data="filter_reset"
                )],
                [InlineKeyboardButton(
                    text="Назад",
                    callback_data="nav_back_to_main"
                )],
            ])
        )
        return
    
    # Показываем список
    await callback.message.edit_text(
        f"{premium_emoji('buy')} <b>Доступные аккаунты:</b>\n"
        f"Найдено: {len(accounts)}",
        reply_markup=get_accounts_list_keyboard(accounts)
    )

@router.callback_query(F.data.startswith("buy_view_"))
async def view_account_for_buy(callback: CallbackQuery):
    """Просмотр детальной информации об аккаунте"""
    account_id = int(callback.data.split("_")[2])
    account = get_account(account_id)
    
    # Проверяем доступность аккаунта
    if not account or account[9] != "active":
        await callback.answer("Аккаунт уже недоступен", show_alert=True)
        await show_available_accounts(callback)
        return
    
    # Получаем информацию о продавце
    seller = get_user(account[1])
    
    # Формируем текст с информацией об аккаунте
    # Индексы: 0=id, 1=seller_id, 2=title, 3=phone, 4=password_2fa, 5=session_string, 
    #          6=country, 7=description, 8=price, 9=status, 10=is_valid
    account_text = (
        f"{premium_emoji('tag')} <b>{account[2]}</b>\n\n"
        f"{premium_emoji('globe')} Страна: {account[6]}\n"
        f"{premium_emoji('money')} Цена: {account[8]} ⭐\n"
        f"{premium_emoji('people')} Продавец: {seller[2] or 'Без username'}"
    )
    
    # Добавляем рейтинг продавца если есть
    if seller[6] > 0:
        account_text += f"\n⭐ Рейтинг: {seller[5]:.1f} ({seller[6]} отзывов)"
    
    # Добавляем описание
    account_text += f"\n\n{premium_emoji('info')} {account[7] or 'Нет описания'}"
    
    await callback.message.edit_text(
        account_text,
        reply_markup=get_account_view_keyboard(account_id, account[1])
    )

@router.callback_query(F.data.startswith("buy_check_"))
async def check_account_before_buy(callback: CallbackQuery):
    """Проверка валидности аккаунта перед покупкой"""
    account_id = int(callback.data.split("_")[2])
    account = get_account(account_id)
    
    if not account or account[9] != "active":
        await callback.answer("Аккаунт уже недоступен", show_alert=True)
        await show_available_accounts(callback)
        return
    
    # Сообщаем о начале проверки
    await callback.message.edit_text(
        f"{premium_emoji('clock')} Проверяю валидность аккаунта..."
    )
    
    # Проверяем валидность
    result = await verify_account(session_string=account[5])
    
    if not result.get("valid"):
        # Аккаунт невалиден
        await callback.message.edit_text(
            f"{premium_emoji('cross')} Аккаунт не прошёл проверку валидности.\n"
            f"Возможно, сессия устарела.",
            reply_markup=get_back_keyboard()
        )
        return
    
    # Аккаунт валиден - показываем подтверждение покупки
    await callback.message.edit_text(
        f"{premium_emoji('tag')} <b>{account[2]}</b>\n\n"
        f"{premium_emoji('globe')} Страна: {account[6]}\n"
        f"{premium_emoji('money')} Цена: {account[8]} ⭐\n\n"
        f"{premium_emoji('check')} Аккаунт валиден!\n"
        f"Нажмите <b>Купить</b> для подтверждения.",
        reply_markup=get_confirm_buy_keyboard(account_id)
    )

@router.callback_query(F.data.startswith("buy_confirm_"))
async def confirm_buy_account(callback: CallbackQuery):
    """Подтверждение и выполнение покупки"""
    account_id = int(callback.data.split("_")[2])
    account = get_account(account_id)
    
    # Проверяем доступность
    if not account or account[9] != "active":
        await callback.answer("Аккаунт уже куплен или снят с продажи", show_alert=True)
        await show_available_accounts(callback)
        return
    
    buyer = get_user(callback.from_user.id)
    
    # Проверяем что покупатель не продавец
    if buyer[0] == account[1]:
        await callback.answer("Нельзя купить свой собственный аккаунт", show_alert=True)
        return
    
    # Проверяем баланс
    if buyer[3] < account[8]:
        await callback.answer(
            f"Недостаточно средств! Ваш баланс: {buyer[3]} ⭐, требуется: {account[8]} ⭐",
            show_alert=True
        )
        return
    
    # Списываем средства с покупателя
    update_balance(callback.from_user.id, -account[8])
    
    # Замораживаем средства продавца (холдинг 24 часа)
    freeze_balance(account[1], account[8])
    
    # Записываем транзакции
    add_transaction(callback.from_user.id, "purchase", -account[8], f"Покупка аккаунта #{account_id}")
    add_transaction(account[1], "sale_frozen", account[8], f"Продажа аккаунта #{account_id} (заморожено на 24ч)")
    
    # Выполняем покупку
    purchase_id = buy_account(account_id, callback.from_user.id)
    
    if not purchase_id:
        # Откатываем если ошибка
        update_balance(callback.from_user.id, account[8])
        await callback.answer("Ошибка при покупке, средства возвращены", show_alert=True)
        return
    
    # Показываем результат
    purchase_text = (
        f"{premium_emoji('check')} <b>Аккаунт успешно куплен!</b>\n\n"
        f"{premium_emoji('tag')} {account[2]}\n"
        f"{premium_emoji('globe')} Страна: {account[6]}\n"
        f"{premium_emoji('phone')} Номер: <code>{account[3]}</code>\n"
    )
    
    if account[4]:
        purchase_text += f"{premium_emoji('lock')} 2FA: <code>{account[4]}</code>\n"
    else:
        purchase_text += f"{premium_emoji('lock')} 2FA: Отсутствует\n"
    
    purchase_text += f"\n{premium_emoji('money')} Списано: {account[8]} ⭐\n"
    purchase_text += f"{premium_emoji('info')} Код подтверждения можно получить в разделе «Мои покупки»"
    
    await callback.message.edit_text(
        purchase_text,
        reply_markup=get_back_keyboard()
    )
    
    # Уведомляем продавца
    try:
        await bot.send_message(
            account[1],
            f"{premium_emoji('gift')} Ваш аккаунт «{account[2]}» был продан!\n\n"
            f"{premium_emoji('money')} Сумма: {account[8]} ⭐\n"
            f"{premium_emoji('clock')} Средства будут зачислены на баланс через 24 часа."
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить продавца {account[1]}: {e}")
    
    logger.info(f"Аккаунт #{account_id} куплен пользователем {callback.from_user.id}")

# ==================== ПРОФИЛЬ ПРОДАВЦА ====================
@router.callback_query(F.data.startswith("seller_profile_"))
async def view_seller_profile(callback: CallbackQuery):
    """Просмотр профиля продавца"""
    seller_id = int(callback.data.split("_")[2])
    seller = get_user(seller_id)
    
    if not seller:
        await callback.answer("Продавец не найден", show_alert=True)
        return
    
    # Получаем статистику продавца
    stats = get_seller_stats(seller_id)
    reviews = get_seller_reviews(seller_id)
    
    # Формируем профиль
    profile_text = (
        f"{premium_emoji('people')} <b>Профиль продавца</b>\n\n"
        f"Username: {seller[2] or 'Скрыт'}\n"
    )
    
    if seller[6] > 0:
        profile_text += f"⭐ Рейтинг: {seller[5]:.1f} ({seller[6]} отзывов)\n"
    else:
        profile_text += "⭐ Рейтинг: Нет оценок\n"
    
    profile_text += (
        f"\n{premium_emoji('stats')} <b>Статистика:</b>\n"
        f"• Продано аккаунтов: {stats['total_sold']}\n"
        f"• Активных объявлений: {stats['active']}"
    )
    
    # Добавляем последние отзывы
    if reviews:
        profile_text += f"\n\n{premium_emoji('edit')} <b>Последние отзывы:</b>"
        for review in reviews[:5]:
            profile_text += f"\n• {review[0]}⭐ от пользователя {review[2]}"
    
    await callback.message.edit_text(
        profile_text,
        reply_markup=get_seller_profile_keyboard(seller_id)
    )

@router.callback_query(F.data.startswith("seller_accounts_"))
async def view_seller_accounts(callback: CallbackQuery):
    """Просмотр активных аккаунтов продавца"""
    seller_id = int(callback.data.split("_")[2])
    accounts = get_seller_accounts(seller_id)
    
    if not accounts:
        await callback.message.edit_text(
            f"{premium_emoji('info')} У продавца нет активных аккаунтов.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Назад к профилю",
                    callback_data=f"seller_profile_{seller_id}"
                )]
            ])
        )
        return
    
    # Создаем кнопки с аккаунтами
    buttons = []
    for acc in accounts:
        title = acc[2] if acc[2] else "Без названия"
        price = acc[8] if acc[8] else 0
        buttons.append([InlineKeyboardButton(
            text=f"{title} | {price}⭐",
            callback_data=f"buy_view_{acc[0]}",
            icon_custom_emoji_id=PREMIUM_EMOJI["globe"]
        )])
    
    buttons.append([InlineKeyboardButton(
        text="Назад к профилю",
        callback_data=f"seller_profile_{seller_id}"
    )])
    
    await callback.message.edit_text(
        f"{premium_emoji('box')} <b>Аккаунты продавца:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

# ==================== ФИЛЬТРЫ ====================
@router.callback_query(F.data == "buy_filters")
async def show_filters_menu(callback: CallbackQuery):
    """Показывает меню фильтров"""
    filters = user_filters.get(callback.from_user.id, {})
    
    filter_text = (
        f"{premium_emoji('filter')} <b>Фильтры поиска:</b>\n\n"
        f"Страна: {filters.get('country', 'Все')}\n"
        f"Цена от: {filters.get('price_from', 'Нет')}\n"
        f"Цена до: {filters.get('price_to', 'Нет')}\n"
        f"2FA: {filters.get('has_2fa', 'Не важно')}"
    )
    
    await callback.message.edit_text(
        filter_text,
        reply_markup=get_filter_keyboard()
    )

@router.callback_query(F.data == "filter_country")
async def filter_country_start(callback: CallbackQuery, state: FSMContext):
    """Установка фильтра по стране"""
    await callback.message.edit_text(
        f"{premium_emoji('globe')} Введите название страны (или «все» для сброса):\n"
        f"Например: Россия, USA, Германия",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(FilterStates.waiting_for_country)

@router.message(StateFilter(FilterStates.waiting_for_country))
async def filter_country_set(message: Message, state: FSMContext):
    """Установка значения фильтра страны"""
    country = message.text.strip()
    
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {}
    
    if country.lower() == "все":
        user_filters[message.from_user.id].pop("country", None)
    else:
        user_filters[message.from_user.id]["country"] = country
    
    await state.clear()
    await message.answer(
        f"{premium_emoji('check')} Фильтр по стране обновлён!",
        reply_markup=get_main_menu_keyboard()
    )

@router.callback_query(F.data == "filter_price_from")
async def filter_price_from_start(callback: CallbackQuery, state: FSMContext):
    """Установка фильтра минимальной цены"""
    await callback.message.edit_text(
        f"{premium_emoji('money')} Введите минимальную цену (0 для сброса):",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(FilterStates.waiting_for_price_from)

@router.message(StateFilter(FilterStates.waiting_for_price_from))
async def filter_price_from_set(message: Message, state: FSMContext):
    """Установка значения минимальной цены"""
    try:
        price = int(message.text.strip())
    except ValueError:
        await message.answer(f"{premium_emoji('cross')} Введите целое число")
        return
    
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {}
    
    if price == 0:
        user_filters[message.from_user.id].pop("price_from", None)
    else:
        user_filters[message.from_user.id]["price_from"] = price
    
    await state.clear()
    await message.answer(
        f"{premium_emoji('check')} Фильтр минимальной цены обновлён!",
        reply_markup=get_main_menu_keyboard()
    )

@router.callback_query(F.data == "filter_price_to")
async def filter_price_to_start(callback: CallbackQuery, state: FSMContext):
    """Установка фильтра максимальной цены"""
    await callback.message.edit_text(
        f"{premium_emoji('money')} Введите максимальную цену (0 для сброса):",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(FilterStates.waiting_for_price_to)

@router.message(StateFilter(FilterStates.waiting_for_price_to))
async def filter_price_to_set(message: Message, state: FSMContext):
    """Установка значения максимальной цены"""
    try:
        price = int(message.text.strip())
    except ValueError:
        await message.answer(f"{premium_emoji('cross')} Введите целое число")
        return
    
    if message.from_user.id not in user_filters:
        user_filters[message.from_user.id] = {}
    
    if price == 0:
        user_filters[message.from_user.id].pop("price_to", None)
    else:
        user_filters[message.from_user.id]["price_to"] = price
    
    await state.clear()
    await message.answer(
        f"{premium_emoji('check')} Фильтр максимальной цены обновлён!",
        reply_markup=get_main_menu_keyboard()
    )

@router.callback_query(F.data == "filter_2fa_yes")
async def filter_2fa_yes(callback: CallbackQuery):
    """Фильтр: только аккаунты с 2FA"""
    if callback.from_user.id not in user_filters:
        user_filters[callback.from_user.id] = {}
    user_filters[callback.from_user.id]["has_2fa"] = True
    await callback.answer("Показываются только аккаунты с 2FA")
    await show_filters_menu(callback)

@router.callback_query(F.data == "filter_2fa_no")
async def filter_2fa_no(callback: CallbackQuery):
    """Фильтр: только аккаунты без 2FA"""
    if callback.from_user.id not in user_filters:
        user_filters[callback.from_user.id] = {}
    user_filters[callback.from_user.id]["has_2fa"] = False
    await callback.answer("Показываются только аккаунты без 2FA")
    await show_filters_menu(callback)

@router.callback_query(F.data == "filter_reset")
async def filter_reset(callback: CallbackQuery):
    """Сброс всех фильтров"""
    user_filters[callback.from_user.id] = {}
    await callback.answer("Фильтры сброшены")
    await show_available_accounts(callback)

# ==================== МОИ ПОКУПКИ ====================
@router.callback_query(F.data == "profile_purchases")
async def my_purchases_list(callback: CallbackQuery):
    """Показывает список покупок пользователя"""
    purchases = get_purchases(callback.from_user.id)
    
    if not purchases:
        await callback.message.edit_text(
            f"{premium_emoji('info')} У вас пока нет покупок.",
            reply_markup=get_back_keyboard()
        )
        return
    
    # Создаем кнопки с покупками
    buttons = []
    for purchase in purchases:
        # purchase[9] = title
        title = purchase[9] if len(purchase) > 9 and purchase[9] else f"Покупка #{purchase[0]}"
        buttons.append([InlineKeyboardButton(
            text=title,
            callback_data=f"purchase_view_{purchase[0]}",
            icon_custom_emoji_id=PREMIUM_EMOJI["box"]
        )])
    
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data="nav_back_to_profile"
    )])
    
    await callback.message.edit_text(
        f"{premium_emoji('box')} <b>Ваши покупки:</b>\n"
        f"Всего: {len(purchases)}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )

@router.callback_query(F.data.startswith("purchase_view_"))
async def view_purchase_details(callback: CallbackQuery):
    """Просмотр деталей покупки"""
    purchase_id = int(callback.data.split("_")[2])
    purchase = get_purchase(purchase_id)
    
    # Проверяем что покупка принадлежит пользователю
    if not purchase or purchase[1] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    # Индексы: 0=id, 1=buyer_id, 2=account_id, 3=purchased_at, 4=phone, 5=password_2fa,
    #          6=session_string, 7=country, 8=description, 9=title
    purchase_text = (
        f"{premium_emoji('box')} <b>{purchase[9]}</b>\n\n"
        f"{premium_emoji('globe')} Страна: {purchase[7]}\n"
        f"{premium_emoji('info')} Описание: {purchase[8] or 'Нет'}\n\n"
        f"{premium_emoji('phone')} Номер: <code>{purchase[4]}</code>\n"
    )
    
    # Добавляем информацию о 2FA если есть
    if purchase[5]:
        purchase_text += f"{premium_emoji('lock')} 2FA пароль: <code>{purchase[5]}</code>\n"
    else:
        purchase_text += f"{premium_emoji('lock')} 2FA: Отсутствует\n"
    
    # Проверяем оставлен ли отзыв
    if has_review(purchase_id):
        purchase_text += f"\n{premium_emoji('check')} Отзыв оставлен"
    
    await callback.message.edit_text(
        purchase_text,
        reply_markup=get_purchase_keyboard(purchase_id)
    )

@router.callback_query(F.data.startswith("purchase_code_"))
async def get_purchase_code(callback: CallbackQuery):
    """Получение кода подтверждения из чата"""
    purchase_id = int(callback.data.split("_")[2])
    purchase = get_purchase(purchase_id)
    
    if not purchase or purchase[1] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    await callback.answer("Ищу код подтверждения...")
    
    # Отправляем сообщение о поиске
    status_message = await callback.message.answer(
        f"{premium_emoji('clock')} Ищу код подтверждения в чатах аккаунта..."
    )
    
    # Ищем код
    code = await get_code_from_chat(purchase[6])
    
    if code:
        await status_message.edit_text(
            f"{premium_emoji('check')} Код подтверждения найден!\n\n"
            f"<code>{code}</code>"
        )
    else:
        await status_message.edit_text(
            f"{premium_emoji('cross')} Код подтверждения не найден.\n"
            f"Возможно, он ещё не пришёл. Попробуйте позже."
        )

@router.callback_query(F.data.startswith("purchase_review_"))
async def review_purchase_start(callback: CallbackQuery):
    """Начало процесса оставления отзыва"""
    purchase_id = int(callback.data.split("_")[2])
    purchase = get_purchase(purchase_id)
    
    if not purchase or purchase[1] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    if has_review(purchase_id):
        await callback.answer("Вы уже оставили отзыв об этой покупке", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{premium_emoji('edit')} Поставьте оценку продавцу (1-5 звёзд):",
        reply_markup=get_review_keyboard(purchase_id)
    )

@router.callback_query(F.data.startswith("review_rate_"))
async def review_rate_submit(callback: CallbackQuery):
    """Сохранение оценки"""
    parts = callback.data.split("_")
    purchase_id = int(parts[2])
    rating = int(parts[3])
    
    # Проверяем что покупка существует и принадлежит пользователю
    purchase = get_purchase(purchase_id)
    if not purchase or purchase[1] != callback.from_user.id:
        await callback.answer("Ошибка", show_alert=True)
        return
    
    # Сохраняем отзыв
    add_review(purchase_id, rating)
    
    await callback.message.edit_text(
        f"{premium_emoji('check')} Спасибо за отзыв!\n"
        f"Вы поставили оценку: {rating} ⭐",
        reply_markup=get_back_keyboard()
    )
    
    logger.info(f"Пользователь {callback.from_user.id} оставил отзыв {rating}⭐ на покупку #{purchase_id}")

# ==================== МОИ ОБЪЯВЛЕНИЯ ====================
@router.callback_query(F.data == "profile_listings")
async def my_listings_list(callback: CallbackQuery):
    """Показывает список моих объявлений"""
    accounts = get_seller_accounts(callback.from_user.id)
    
    if not accounts:
        await callback.message.edit_text(
            f"{premium_emoji('info')} У вас нет активных объявлений.",
            reply_markup=get_back_keyboard()
        )
        return
    
    await callback.message.edit_text(
        f"{premium_emoji('tag')} <b>Ваши объявления:</b>\n"
        f"Активных: {len(accounts)}",
        reply_markup=get_my_listings_keyboard(accounts)
    )

@router.callback_query(F.data.startswith("listing_view_"))
async def view_my_listing(callback: CallbackQuery):
    """Просмотр своего объявления"""
    account_id = int(callback.data.split("_")[2])
    account = get_account(account_id)
    
    # Проверяем что объявление принадлежит пользователю
    if not account or account[1] != callback.from_user.id:
        await callback.answer("Объявление не найдено", show_alert=True)
        return
    
    listing_text = (
        f"{premium_emoji('tag')} <b>{account[2]}</b>\n\n"
        f"{premium_emoji('globe')} Страна: {account[6]}\n"
        f"{premium_emoji('money')} Цена: {account[8]} ⭐\n"
        f"{premium_emoji('info')} Статус: {account[9]}\n\n"
        f"Описание: {account[7] or 'Нет описания'}"
    )
    
    await callback.message.edit_text(
        listing_text,
        reply_markup=get_listing_actions_keyboard(account_id)
    )

@router.callback_query(F.data.startswith("listing_remove_"))
async def remove_my_listing(callback: CallbackQuery):
    """Снятие объявления с продажи"""
    account_id = int(callback.data.split("_")[2])
    remove_account(account_id, callback.from_user.id)
    
    await callback.message.edit_text(
        f"{premium_emoji('check')} Объявление снято с продажи.",
        reply_markup=get_back_keyboard()
    )
    
    logger.info(f"Пользователь {callback.from_user.id} снял с продажи аккаунт #{account_id}")

# ==================== ПОПОЛНЕНИЕ БАЛАНСА ====================
@router.callback_query(F.data == "profile_add_balance")
async def add_balance_start(callback: CallbackQuery, state: FSMContext):
    """Начало пополнения баланса"""
    await callback.message.edit_text(
        f"{premium_emoji('star')} <b>Пополнение баланса</b>\n\n"
        f"Введите сумму пополнения в звёздах (минимум 1):\n"
        f"Курс: 1⭐ = 1 Telegram Star",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(BuyAccountStates.waiting_for_amount)

@router.message(StateFilter(BuyAccountStates.waiting_for_amount))
async def process_balance_amount(message: Message, state: FSMContext):
    """Обработка суммы пополнения"""
    try:
        amount = int(message.text.strip())
        if amount < 1:
            raise ValueError("Сумма должна быть больше 0")
    except ValueError:
        await message.answer(
            f"{premium_emoji('cross')} Введите целое число больше 0"
        )
        return
    
    # Создаем счет на оплату
    await message.answer_invoice(
        title="Пополнение баланса",
        description=f"Пополнение баланса на {amount} звёзд",
        payload=f"balance_{amount}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{amount} звёзд", amount=amount)],
        provider_token="",
    )
    
    await state.clear()
    logger.info(f"Пользователь {message.from_user.id} запросил пополнение на {amount}⭐")

@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    """Обработчик предварительной проверки платежа"""
    await pre_checkout_query.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    """Обработчик успешного платежа"""
    payload = message.successful_payment.invoice_payload
    
    if payload.startswith("balance_"):
        amount = int(payload.split("_")[1])
        
        # Начисляем средства
        update_balance(message.from_user.id, amount)
        add_transaction(message.from_user.id, "deposit", amount, "Пополнение баланса")
        
        # Получаем обновленный баланс
        user = get_user(message.from_user.id)
        
        await message.answer(
            f"{premium_emoji('check')} <b>Баланс пополнен!</b>\n\n"
            f"{premium_emoji('money')} Зачислено: {amount} ⭐\n"
            f"{premium_emoji('wallet')} Текущий баланс: {user[3]} ⭐",
            reply_markup=get_main_menu_keyboard()
        )
        
        logger.info(f"Пользователь {message.from_user.id} пополнил баланс на {amount}⭐")

# ==================== АДМИН-ПАНЕЛЬ ====================
@router.callback_query(F.data == "admin_change_balance")
async def admin_change_balance_start(callback: CallbackQuery, state: FSMContext):
    """Начало изменения баланса пользователя"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к админ-панели", show_alert=True)
        return
    
    await callback.message.edit_text(
        f"{premium_emoji('wallet')} <b>Изменение баланса</b>\n\n"
        f"Введите Telegram ID пользователя:",
        reply_markup=get_back_keyboard()
    )
    await state.set_state(AdminStates.waiting_for_user_id)

@router.message(StateFilter(AdminStates.waiting_for_user_id))
async def admin_get_user_id(message: Message, state: FSMContext):
    """Обработка ввода ID пользователя"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer(f"{premium_emoji('cross')} Введите корректный числовой ID")
        return
    
    user = get_user(user_id)
    if not user:
        await message.answer(
            f"{premium_emoji('cross')} Пользователь с ID {user_id} не найден"
        )
        await state.clear()
        return
    
    await state.update_data(admin_user_id=user_id)
    
    await message.answer(
        f"{premium_emoji('profile')} <b>Пользователь найден:</b>\n\n"
        f"ID: {user[1]}\n"
        f"Username: {user[2] or 'Не указан'}\n"
        f"{premium_emoji('wallet')} Баланс: {user[3]} ⭐\n"
        f"{premium_emoji('frozen')} Заморожено: {user[4]} ⭐\n\n"
        f"Введите сумму для изменения:\n"
        f"(положительное число — добавить, отрицательное — списать):"
    )
    await state.set_state(AdminStates.waiting_for_amount)

@router.message(StateFilter(AdminStates.waiting_for_amount))
async def admin_change_balance_execute(message: Message, state: FSMContext):
    """Выполнение изменения баланса"""
    if message.from_user.id not in ADMIN_IDS:
        return
    
    try:
        amount = int(message.text.strip())
    except ValueError:
        await message.answer(f"{premium_emoji('cross')} Введите целое число")
        return
    
    data = await state.get_data()
    user_id = data["admin_user_id"]
    
    # Изменяем баланс
    update_balance(user_id, amount)
    add_transaction(user_id, "admin_change", amount, f"Изменение баланса администратором {message.from_user.id}")
    
    # Получаем обновленные данные
    user = get_user(user_id)
    
    await message.answer(
        f"{premium_emoji('check')} <b>Баланс изменён!</b>\n\n"
        f"Пользователь: {user[2] or user_id}\n"
        f"Изменение: {'+' if amount > 0 else ''}{amount} ⭐\n"
        f"{premium_emoji('wallet')} Новый баланс: {user[3]} ⭐",
        reply_markup=get_main_menu_keyboard()
    )
    
    logger.info(f"Админ {message.from_user.id} изменил баланс пользователя {user_id} на {amount}⭐")
    await state.clear()

@router.callback_query(F.data == "admin_stats")
async def admin_statistics(callback: CallbackQuery):
    """Показывает статистику бота"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("У вас нет доступа к админ-панели", show_alert=True)
        return
    
    # Собираем статистику
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM accounts WHERE status = 'active'")
    active_accounts = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM accounts WHERE status = 'sold'")
    sold_accounts = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM purchases")
    total_purchases = cur.fetchone()[0]
    
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE type = 'deposit'")
    total_deposits = cur.fetchone()[0]
    
    cur.execute("SELECT COALESCE(SUM(frozen_balance), 0) FROM users")
    total_frozen = cur.fetchone()[0]
    
    stats_text = (
        f"{premium_emoji('stats')} <b>Статистика бота:</b>\n\n"
        f"{premium_emoji('profile')} Пользователей: {total_users}\n"
        f"{premium_emoji('tag')} Активных объявлений: {active_accounts}\n"
        f"{premium_emoji('check')} Продано аккаунтов: {sold_accounts}\n"
        f"{premium_emoji('box')} Всего покупок: {total_purchases}\n"
        f"{premium_emoji('money')} Всего пополнено: {total_deposits} ⭐\n"
        f"{premium_emoji('frozen')} Заморожено средств: {total_frozen} ⭐"
    )
    
    await callback.message.edit_text(
        stats_text,
        reply_markup=get_back_keyboard()
    )

# ==================== ЗАПУСК БОТА ====================
async def main():
    """Главная функция запуска бота"""
    # Инициализируем базу данных
    init_db()
    logger.info("База данных инициализирована")
    
    # Запускаем фоновую проверку холдов
    asyncio.create_task(hold_checker())
    logger.info("Фоновая проверка холдов запущена")
    
    # Запускаем бота
    logger.info("Бот запускается...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
