import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    LabeledPrice, PreCheckoutQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.methods import DeleteWebhook

from dotenv import load_dotenv

import asyncpg
from asyncpg import Pool

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    PasswordHashInvalidError, PhoneCodeExpiredError, FloodWaitError
)

load_dotenv()

# --- Конфигурация ---
API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/db")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN", "")
ADMIN_ID = 7973988177

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db_pool: Pool = None

# --- Инициализация БД ---
async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL)
    
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                username TEXT,
                balance FLOAT DEFAULT 0.0,
                total_purchases INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id SERIAL PRIMARY KEY,
                phone TEXT UNIQUE NOT NULL,
                country TEXT NOT NULL,
                session_string TEXT,
                password_2fa TEXT,
                is_sold BOOLEAN DEFAULT FALSE,
                is_valid BOOLEAN DEFAULT TRUE,
                is_reserved BOOLEAN DEFAULT FALSE,
                reserved_until TIMESTAMP,
                reserved_by BIGINT,
                sold_to BIGINT,
                buy_price FLOAT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                account_id INTEGER NOT NULL,
                purchase_date TIMESTAMP DEFAULT NOW(),
                code_obtained BOOLEAN DEFAULT FALSE
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS price_settings (
                country TEXT PRIMARY KEY,
                buy_price FLOAT DEFAULT 100.0
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS media_settings (
                section TEXT PRIMARY KEY,
                file_id TEXT,
                file_type TEXT,
                caption TEXT
            )
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS crypto_payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                payment_id INTEGER,
                invoice_id TEXT UNIQUE,
                amount FLOAT NOT NULL,
                currency TEXT DEFAULT 'RUB',
                status TEXT DEFAULT 'pending',
                account_id INTEGER,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)

# --- Функции БД ---
async def get_user(user_id: int) -> Optional[asyncpg.Record]:
    async with db_pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)

async def create_user(user_id: int, username: str = None):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (id, username) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user_id, username
        )

async def update_balance(user_id: int, amount: float) -> float:
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET balance = balance + $1 WHERE id = $2",
            amount, user_id
        )
        row = await conn.fetchrow("SELECT balance FROM users WHERE id = $1", user_id)
        return row['balance'] if row else 0.0

async def get_free_account(country: str) -> Optional[asyncpg.Record]:
    async with db_pool.acquire() as conn:
        return await conn.fetchrow(
            """
            SELECT * FROM accounts 
            WHERE country = $1 
            AND is_sold = FALSE 
            AND is_valid = TRUE 
            AND (is_reserved = FALSE OR reserved_until < NOW())
            ORDER BY created_at ASC 
            LIMIT 1
            """,
            country
        )

async def reserve_account(account_id: int, user_id: int) -> bool:
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE accounts 
            SET is_reserved = TRUE, reserved_by = $1, reserved_until = $2
            WHERE id = $3 AND is_sold = FALSE AND is_valid = TRUE
            """,
            user_id, datetime.utcnow() + timedelta(minutes=5), account_id
        )
        return result != "UPDATE 0"

async def release_account(account_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE accounts 
            SET is_reserved = FALSE, reserved_by = NULL, reserved_until = NULL
            WHERE id = $1
            """,
            account_id
        )

async def mark_account_sold(account_id: int, user_id: int, price: float):
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                UPDATE accounts 
                SET is_sold = TRUE, is_reserved = FALSE, sold_to = $1, buy_price = $2
                WHERE id = $3
                """,
                user_id, price, account_id
            )
            await conn.execute(
                "INSERT INTO purchases (user_id, account_id) VALUES ($1, $2)",
                user_id, account_id
            )
            await conn.execute(
                "UPDATE users SET total_purchases = total_purchases + 1 WHERE id = $1",
                user_id
            )

async def get_user_purchases(user_id: int) -> List[Dict[str, Any]]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT p.*, a.phone, a.country, a.password_2fa
            FROM purchases p
            JOIN accounts a ON p.account_id = a.id
            WHERE p.user_id = $1
            ORDER BY p.purchase_date DESC
            """,
            user_id
        )
        return [dict(row) for row in rows]

async def get_price(country: str) -> float:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT buy_price FROM price_settings WHERE country = $1", country
        )
        return row['buy_price'] if row else 100.0

async def set_price(country: str, value: float):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO price_settings (country, buy_price) VALUES ($1, $2)
            ON CONFLICT (country) DO UPDATE SET buy_price = $2
            """,
            country, value
        )

async def get_media(section: str) -> Optional[Dict[str, Any]]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM media_settings WHERE section = $1", section
        )
        return dict(row) if row else None

async def set_media(section: str, file_id: str, file_type: str, caption: str = None):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO media_settings (section, file_id, file_type, caption) 
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (section) DO UPDATE 
            SET file_id = $2, file_type = $3, caption = $4
            """,
            section, file_id, file_type, caption
        )

async def get_all_users() -> List[Dict[str, Any]]:
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM users")
        return [dict(row) for row in rows]

async def get_stats() -> Dict[str, Any]:
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")
        total_accounts = await conn.fetchval("SELECT COUNT(*) FROM accounts")
        sold_accounts = await conn.fetchval("SELECT COUNT(*) FROM accounts WHERE is_sold = TRUE")
        available_accounts = await conn.fetchval(
            "SELECT COUNT(*) FROM accounts WHERE is_sold = FALSE AND is_valid = TRUE"
        )
        return {
            "total_users": total_users,
            "total_accounts": total_accounts,
            "sold_accounts": sold_accounts,
            "available_accounts": available_accounts
        }

async def get_account_by_id(account_id: int) -> Optional[Dict[str, Any]]:
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM accounts WHERE id = $1", account_id)
        return dict(row) if row else None

async def update_account_session(account_id: int, session_string: str):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE accounts SET session_string = $1 WHERE id = $2",
            session_string, account_id
        )

async def mark_code_obtained(purchase_id: int):
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE purchases SET code_obtained = TRUE WHERE id = $1",
            purchase_id
        )

async def add_account_to_db(phone: str, country: str, session_string: str = None):
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO accounts (phone, country, session_string, is_valid, is_sold)
            VALUES ($1, $2, $3, TRUE, FALSE)
            """,
            phone, country, session_string
        )

# --- Telethon функции ---
async def check_account_valid(phone: str, session_string: str = None) -> Tuple[bool, Optional[str]]:
    client = None
    try:
        if session_string:
            client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        else:
            client = TelegramClient(StringSession(), API_ID, API_HASH)

        await client.connect()

        if not await client.is_user_authorized():
            return False, None

        return True, StringSession.save(client.session)
    except Exception as e:
        logger.error(f"Error checking account {phone}: {e}")
        return False, None
    finally:
        if client:
            await client.disconnect()

async def get_login_code_from_account(account_id: int) -> Optional[str]:
    account = await get_account_by_id(account_id)
    if not account or not account['session_string']:
        return None

    client = None
    try:
        client = TelegramClient(
            StringSession(account['session_string']), API_ID, API_HASH
        )
        await client.connect()

        if not await client.is_user_authorized():
            return None

        telegram_chat = None
        async for dialog in client.iter_dialogs():
            if dialog.name == "Telegram" and dialog.is_user:
                telegram_chat = dialog
                break

        if not telegram_chat:
            return None

        messages = await client.get_messages(telegram_chat.id, limit=5)

        for message in messages:
            if message.text and re.search(r'\b\d{5}\b', message.text):
                code = re.search(r'\b\d{5}\b', message.text).group()
                return code

        return None
    except Exception as e:
        logger.error(f"Error getting code for account {account_id}: {e}")
        return None
    finally:
        if client:
            await client.disconnect()

# --- Страны ---
COUNTRIES = [
    "🇷🇺 Россия", "🇺🇦 Украина", "🇧🇾 Беларусь", "🇰🇿 Казахстан", "🇺🇿 Узбекистан",
    "🇹🇯 Таджикистан", "🇰🇬 Кыргызстан", "🇦🇿 Азербайджан", "🇦🇲 Армения", "🇬🇪 Грузия",
    "🇲🇩 Молдова", "🇹🇲 Туркменистан", "🇩🇪 Германия", "🇫🇷 Франция", "🇬🇧 Великобритания",
    "🇺🇸 США", "🇨🇦 Канада", "🇹🇷 Турция", "🇵🇱 Польша", "🇮🇹 Италия",
    "🇪🇸 Испания", "🇳🇱 Нидерланды", "🇧🇪 Бельгия", "🇨🇿 Чехия", "🇸🇪 Швеция",
    "🇳🇴 Норвегия", "🇩🇰 Дания", "🇫🇮 Финляндия", "🇵🇹 Португалия", "🇬🇷 Греция",
    "🇨🇭 Швейцария", "🇦🇹 Австрия", "🇷🇸 Сербия", "🇧🇬 Болгария", "🇷🇴 Румыния",
    "🇭🇺 Венгрия", "🇮🇳 Индия", "🇧🇷 Бразилия", "🇦🇷 Аргентина", "🇲🇽 Мексика",
    "🇯🇵 Япония", "🇰🇷 Южная Корея", "🇦🇪 ОАЭ", "🇮🇱 Израиль", "🇪🇪 Эстония"
]

# --- FSM ---
class BuyAccount(StatesGroup):
    waiting_payment = State()

class AdminStates(StatesGroup):
    main = State()
    broadcast_text = State()
    broadcast_confirm = State()
    change_balance_user = State()
    change_balance_amount = State()
    change_price_country = State()
    change_price_value = State()
    upload_media_section = State()

# --- Клавиатуры ---
def get_main_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="Купить аккаунт",
        callback_data="buy_account",
        style="primary",
        icon_custom_emoji_id="5884479287171485878"
    ))
    builder.row(InlineKeyboardButton(
        text="Мои покупки",
        callback_data="my_purchases",
        style="default",
        icon_custom_emoji_id="5870528606328852614"
    ))
    builder.row(InlineKeyboardButton(
        text="Профиль",
        callback_data="profile",
        style="default",
        icon_custom_emoji_id="5891207662678317861"
    ))
    return builder.as_markup()

def get_countries_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    items_per_page = 10
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    countries_chunk = COUNTRIES[start_idx:end_idx]

    for country in countries_chunk:
        builder.row(InlineKeyboardButton(
            text=country,
            callback_data=f"country_{country}",
            style="default",
            icon_custom_emoji_id="5870528606328852614"
        ))

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text="Назад",
            callback_data=f"countries_page_{page - 1}",
            style="default",
            icon_custom_emoji_id="5893057118545646106"
        ))
    if end_idx < len(COUNTRIES):
        nav_buttons.append(InlineKeyboardButton(
            text="Вперед",
            callback_data=f"countries_page_{page + 1}",
            style="default",
            icon_custom_emoji_id="5893057118545646106"
        ))

    if nav_buttons:
        builder.row(*nav_buttons)

    builder.row(InlineKeyboardButton(
        text="Главное меню",
        callback_data="main_menu",
        style="primary",
        icon_custom_emoji_id="5873147866364514353"
    ))
    return builder.as_markup()

def get_payment_keyboard(account_id: int, amount: float) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text=f"Оплатить {int(amount)} ⭐",
        callback_data=f"pay_stars_{account_id}",
        style="primary",
        icon_custom_emoji_id="5904462880941545555"
    ))
    builder.row(InlineKeyboardButton(
        text=f"Оплатить {amount:.2f}₽ (Crypto Bot)",
        callback_data=f"pay_crypto_{account_id}",
        style="success",
        icon_custom_emoji_id="5260752406890711732"
    ))
    builder.row(InlineKeyboardButton(
        text=f"Оплатить с баланса ({amount:.2f}₽)",
        callback_data=f"pay_balance_{account_id}",
        style="default",
        icon_custom_emoji_id="5769126056262898415"
    ))
    builder.row(InlineKeyboardButton(
        text="Отмена",
        callback_data=f"cancel_purchase_{account_id}",
        style="danger",
        icon_custom_emoji_id="5870657884844462243"
    ))
    return builder.as_markup()

def get_admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="Статистика",
        callback_data="admin_stats",
        style="primary",
        icon_custom_emoji_id="5870930636742595124"
    ))
    builder.row(InlineKeyboardButton(
        text="Рассылка",
        callback_data="admin_broadcast",
        style="default",
        icon_custom_emoji_id="6039422865189638057"
    ))
    builder.row(InlineKeyboardButton(
        text="Изменить баланс",
        callback_data="admin_change_balance",
        style="default",
        icon_custom_emoji_id="5769126056262898415"
    ))
    builder.row(InlineKeyboardButton(
        text="Изменить цены",
        callback_data="admin_change_price",
        style="default",
        icon_custom_emoji_id="5870676941614354370"
    ))
    builder.row(InlineKeyboardButton(
        text="Загрузить медиа",
        callback_data="admin_upload_media",
        style="default",
        icon_custom_emoji_id="6035128606563241721"
    ))
    builder.row(InlineKeyboardButton(
        text="Закрыть",
        callback_data="admin_close",
        style="danger",
        icon_custom_emoji_id="5870657884844462243"
    ))
    return builder.as_markup()

def get_code_keyboard(purchase_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="Получить код",
        callback_data=f"get_code_{purchase_id}",
        style="primary",
        icon_custom_emoji_id="6037249452824072506"
    ))
    builder.row(InlineKeyboardButton(
        text="Назад",
        callback_data="my_purchases",
        style="default",
        icon_custom_emoji_id="5893057118545646106"
    ))
    return builder.as_markup()

# --- Инициализация бота ---
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# --- Хендлеры ---
@router.message(Command("start"))
async def cmd_start(message: Message):
    await create_user(message.from_user.id, message.from_user.username)
    
    media = await get_media("main_menu")
    if media and media['file_id']:
        if media['file_type'] == "photo":
            await message.answer_photo(
                photo=media['file_id'],
                caption=f"<tg-emoji emoji-id='5873147866364514353'>🏘</tg-emoji> <b>Добро пожаловать в Vest Market!</b>\n\n"
                        f"<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> Здесь ты можешь купить Telegram аккаунты разных стран.\n\n"
                        f"<tg-emoji emoji-id='5904462880941545555'>🪙</tg-emoji> Выбери действие в меню:",
                reply_markup=get_main_keyboard()
            )
        elif media['file_type'] == "video":
            await message.answer_video(
                video=media['file_id'],
                caption=f"<tg-emoji emoji-id='5873147866364514353'>🏘</tg-emoji> <b>Добро пожаловать в Vest Market!</b>\n\n"
                        f"<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> Здесь ты можешь купить Telegram аккаунты разных стран.\n\n"
                        f"<tg-emoji emoji-id='5904462880941545555'>🪙</tg-emoji> Выбери действие в меню:",
                reply_markup=get_main_keyboard()
            )
    else:
        await message.answer(
            f"<tg-emoji emoji-id='5873147866364514353'>🏘</tg-emoji> <b>Добро пожаловать в Vest Market!</b>\n\n"
            f"<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> Здесь ты можешь купить Telegram аккаунты разных стран.\n\n"
            f"<tg-emoji emoji-id='5904462880941545555'>🪙</tg-emoji> Выбери действие в меню:",
            reply_markup=get_main_keyboard()
        )

@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>У вас нет доступа!</b>"
        )
        return
    
    await state.clear()
    await message.answer(
        "<tg-emoji emoji-id='5870982283724328568'>⚙</tg-emoji> <b>Админ панель</b>\n\n"
        "Выберите действие:",
        reply_markup=get_admin_keyboard()
    )

@router.callback_query(F.data == "main_menu")
async def callback_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "<tg-emoji emoji-id='5873147866364514353'>🏘</tg-emoji> <b>Главное меню</b>\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "buy_account")
async def callback_buy_account(callback: CallbackQuery):
    await callback.message.edit_text(
        "<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> <b>Выберите страну:</b>\n\n"
        "Выберите страну аккаунта, который хотите купить:",
        reply_markup=get_countries_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("countries_page_"))
async def callback_countries_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[2])
    await callback.message.edit_text(
        "<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> <b>Выберите страну:</b>",
        reply_markup=get_countries_keyboard(page)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("country_"))
async def callback_country_selected(callback: CallbackQuery):
    country = callback.data.replace("country_", "")
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='5345906554510012647'>🔄</tg-emoji> <b>Ищу аккаунт {country}...</b>\n\n"
        "Пожалуйста, подождите немного."
    )
    await callback.answer()
    
    await asyncio.sleep(1)
    
    account = await get_free_account(country)
    
    if not account:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Аккаунты в {country} закончились!</b>\n\n"
            "Попробуйте выбрать другую страну.",
            reply_markup=get_countries_keyboard()
        )
        return
    
    is_valid, session = await check_account_valid(account['phone'], account['session_string'])
    
    if not is_valid:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Аккаунт {country} невалидный!</b>\n\n"
            "Попробуйте выбрать другую страну.",
            reply_markup=get_countries_keyboard()
        )
        return
    
    reserved = await reserve_account(account['id'], callback.from_user.id)
    
    if not reserved:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Не удалось зарезервировать аккаунт!</b>\n\n"
            "Попробуйте ещё раз.",
            reply_markup=get_countries_keyboard()
        )
        return
    
    price = await get_price(country)
    
    asyncio.create_task(release_account_after_timeout(account['id'], 300))
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> <b>Аккаунт найден!</b>\n\n"
        f"<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> Страна: {country}\n"
        f"<tg-emoji emoji-id='5904462880941545555'>🪙</tg-emoji> Цена: {price:.2f}₽\n\n"
        "<b>Выберите способ оплаты:</b>",
        reply_markup=get_payment_keyboard(account['id'], price)
    )

async def release_account_after_timeout(account_id: int, seconds: int):
    await asyncio.sleep(seconds)
    await release_account(account_id)

@router.callback_query(F.data.startswith("cancel_purchase_"))
async def callback_cancel_purchase(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    await release_account(account_id)
    await callback.message.edit_text(
        "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Покупка отменена!</b>\n\n"
        "Аккаунт возвращён в список доступных.",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("pay_stars_"))
async def callback_pay_stars(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    account = await get_account_by_id(account_id)
    
    if not account:
        await callback.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Аккаунт не найден!",
            show_alert=True
        )
        return
    
    price = await get_price(account['country'])
    stars = int(price)
    
    await callback.message.answer_invoice(
        title="Покупка Telegram аккаунта",
        description=f"Аккаунт {account['country']} | Vest Market",
        payload=f"stars_{account_id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label=f"Аккаунт {account['country']}", amount=stars)],
        reply_markup=get_payment_keyboard(account_id, price)
    )
    await callback.answer()

@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)

@router.message(F.content_type == types.ContentType.SUCCESSFUL_PAYMENT)
async def process_successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    
    if payload.startswith("stars_"):
        account_id = int(payload.split("_")[1])
        account = await get_account_by_id(account_id)
        
        if not account:
            await message.answer(
                "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Аккаунт не найден!</b>"
            )
            return
        
        price = await get_price(account['country'])
        await mark_account_sold(account_id, message.from_user.id, price)
        
        await message.answer(
            f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> <b>Оплата прошла успешно!</b>\n\n"
            f"<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> Номер: {account['phone']}\n"
            f"<tg-emoji emoji-id='5891207662678317861'>👤</tg-emoji> Страна: {account['country']}\n\n"
            f"<tg-emoji emoji-id='6037249452824072506'>🔒</tg-emoji> 2FA: {'Да' if account['password_2fa'] else 'Нет'}\n\n",
            reply_markup=get_main_keyboard()
        )

@router.callback_query(F.data.startswith("pay_balance_"))
async def callback_pay_balance(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[2])
    account = await get_account_by_id(account_id)
    
    if not account:
        await callback.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Аккаунт не найден!",
            show_alert=True
        )
        return
    
    price = await get_price(account['country'])
    user = await get_user(callback.from_user.id)
    
    if user['balance'] < price:
        await callback.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Недостаточно средств на балансе!",
            show_alert=True
        )
        return
    
    await update_balance(callback.from_user.id, -price)
    await mark_account_sold(account_id, callback.from_user.id, price)
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> <b>Покупка успешна!</b>\n\n"
        f"<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> Номер: {account['phone']}\n"
        f"<tg-emoji emoji-id='5891207662678317861'>👤</tg-emoji> Страна: {account['country']}\n"
        f"<tg-emoji emoji-id='6037249452824072506'>🔒</tg-emoji> 2FA: {'Да' if account['password_2fa'] else 'Нет'}\n\n"
        f"<tg-emoji emoji-id='5769126056262898415'>👛</tg-emoji> Ваш баланс: {user['balance'] - price:.2f}₽",
        reply_markup=get_main_keyboard()
    )
    await callback.answer(
        "<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> Покупка успешна!",
        show_alert=True
    )

@router.callback_query(F.data == "profile")
async def callback_profile(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='5891207662678317861'>👤</tg-emoji> <b>Ваш профиль</b>\n\n"
        f"<tg-emoji emoji-id='5769126056262898415'>👛</tg-emoji> Баланс: {user['balance']:.2f}₽\n"
        f"<tg-emoji emoji-id='5884479287171485878'>📦</tg-emoji> Куплено аккаунтов: {user['total_purchases']}\n"
        f"<tg-emoji emoji-id='5890937706803894250'>📅</tg-emoji> Дата регистрации: {user['created_at'].strftime('%d.%m.%Y')}",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "my_purchases")
async def callback_my_purchases(callback: CallbackQuery):
    purchases = await get_user_purchases(callback.from_user.id)
    
    if not purchases:
        await callback.message.edit_text(
            "<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> <b>Мои покупки</b>\n\n"
            "У вас пока нет купленных аккаунтов.",
            reply_markup=get_main_keyboard()
        )
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    
    for purchase in purchases:
        builder.row(InlineKeyboardButton(
            text=f"{purchase['phone']} | {purchase['country']}",
            callback_data=f"purchase_{purchase['id']}",
            style="default",
            icon_custom_emoji_id="5870528606328852614"
        ))
    
    builder.row(InlineKeyboardButton(
        text="Главное меню",
        callback_data="main_menu",
        style="primary",
        icon_custom_emoji_id="5873147866364514353"
    ))
    
    await callback.message.edit_text(
        "<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> <b>Мои покупки</b>\n\n"
        "Нажмите на аккаунт, чтобы получить код:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@router.callback_query(F.data.startswith("purchase_"))
async def callback_purchase_detail(callback: CallbackQuery):
    purchase_id = int(callback.data.split("_")[1])
    purchases = await get_user_purchases(callback.from_user.id)
    
    purchase = None
    for p in purchases:
        if p['id'] == purchase_id:
            purchase = p
            break
    
    if not purchase:
        await callback.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Покупка не найдена!",
            show_alert=True
        )
        return
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> <b>Аккаунт</b>\n\n"
        f"<tg-emoji emoji-id='5884479287171485878'>📦</tg-emoji> Номер: {purchase['phone']}\n"
        f"<tg-emoji emoji-id='5891207662678317861'>👤</tg-emoji> Страна: {purchase['country']}\n"
        f"<tg-emoji emoji-id='6037249452824072506'>🔒</tg-emoji> 2FA: {'Да' if purchase['password_2fa'] else 'Нет'}\n"
        f"<tg-emoji emoji-id='5890937706803894250'>📅</tg-emoji> Дата: {purchase['purchase_date'].strftime('%d.%m.%Y %H:%M')}\n\n"
        f"<tg-emoji emoji-id='6037249452824072506'>🔒</tg-emoji> Код получен: {'Да' if purchase['code_obtained'] else 'Нет'}",
        reply_markup=get_code_keyboard(purchase_id)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("get_code_"))
async def callback_get_code(callback: CallbackQuery):
    purchase_id = int(callback.data.split("_")[2])
    purchases = await get_user_purchases(callback.from_user.id)
    
    purchase = None
    for p in purchases:
        if p['id'] == purchase_id:
            purchase = p
            break
    
    if not purchase:
        await callback.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Покупка не найдена!",
            show_alert=True
        )
        return
    
    if purchase['code_obtained']:
        await callback.answer(
            "<tg-emoji emoji-id='6028435952299413210'>ℹ</tg-emoji> Код уже был получен!",
            show_alert=True
        )
        return
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='5345906554510012647'>🔄</tg-emoji> <b>Получаю код...</b>\n\n"
        "Пожалуйста, подождите."
    )
    await callback.answer()
    
    code = await get_login_code_from_account(purchase['account_id'])
    
    if not code:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Не удалось получить код!</b>\n\n"
            "Попробуйте ещё раз позже.",
            reply_markup=get_code_keyboard(purchase_id)
        )
        return
    
    await mark_code_obtained(purchase_id)
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> <b>Код получен!</b>\n\n"
        f"<tg-emoji emoji-id='6037249452824072506'>🔒</tg-emoji> Ваш код: <code>{code}</code>\n\n"
        f"<tg-emoji emoji-id='6028435952299413210'>ℹ</tg-emoji> Код действителен в течение нескольких минут.",
        reply_markup=get_main_keyboard()
    )

# --- Админ хендлеры ---
@router.callback_query(F.data == "admin_stats")
async def callback_admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Нет доступа!", show_alert=True)
        return
    
    stats = await get_stats()
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='5870930636742595124'>📊</tg-emoji> <b>Статистика</b>\n\n"
        f"<tg-emoji emoji-id='5870772616305839506'>👥</tg-emoji> Всего пользователей: {stats['total_users']}\n"
        f"<tg-emoji emoji-id='5884479287171485878'>📦</tg-emoji> Всего аккаунтов: {stats['total_accounts']}\n"
        f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> Продано: {stats['sold_accounts']}\n"
        f"<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Доступно: {stats['available_accounts']}",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def callback_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "<tg-emoji emoji-id='6039422865189638057'>📣</tg-emoji> <b>Отправьте сообщение для рассылки:</b>\n\n"
        "Можно отправить текст, фото или видео с подписью.\n"
        "Для отмены нажмите кнопку ниже:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="admin_close",
                style="danger",
                icon_custom_emoji_id="5870657884844462243"
            )]
        ])
    )
    await state.set_state(AdminStates.broadcast_text)
    await callback.answer()

@router.message(StateFilter(AdminStates.broadcast_text))
async def admin_broadcast_message(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    await state.update_data(
        broadcast_type="text",
        broadcast_text=message.text or message.caption or "",
        broadcast_file_id=message.photo[-1].file_id if message.photo else (
            message.video.file_id if message.video else None
        ),
        broadcast_file_type="photo" if message.photo else ("video" if message.video else None)
    )
    
    await state.set_state(AdminStates.broadcast_confirm)
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="Отправить",
        callback_data="broadcast_send",
        style="success",
        icon_custom_emoji_id="5870633910337015697"
    ))
    builder.row(InlineKeyboardButton(
        text="Отмена",
        callback_data="admin_close",
        style="danger",
        icon_custom_emoji_id="5870657884844462243"
    ))
    
    await message.answer(
        "<tg-emoji emoji-id='6039422865189638057'>📣</tg-emoji> <b>Подтвердите рассылку</b>",
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "broadcast_send", StateFilter(AdminStates.broadcast_confirm))
async def callback_broadcast_send(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Нет доступа!", show_alert=True)
        return
    
    data = await state.get_data()
    await state.clear()
    
    users = await get_all_users()
    
    success = 0
    failed = 0
    
    for user in users:
        try:
            if data.get('broadcast_type') == "text" and not data.get('broadcast_file_id'):
                await bot.send_message(
                    chat_id=user['id'],
                    text=data['broadcast_text']
                )
            elif data.get('broadcast_file_type') == "photo":
                await bot.send_photo(
                    chat_id=user['id'],
                    photo=data['broadcast_file_id'],
                    caption=data.get('broadcast_text', '')
                )
            elif data.get('broadcast_file_type') == "video":
                await bot.send_video(
                    chat_id=user['id'],
                    video=data['broadcast_file_id'],
                    caption=data.get('broadcast_text', '')
                )
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            failed += 1
            logger.error(f"Broadcast error for user {user['id']}: {e}")
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> <b>Рассылка завершена!</b>\n\n"
        f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> Успешно: {success}\n"
        f"<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Не удалось: {failed}",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_change_balance")
async def callback_admin_change_balance(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "<tg-emoji emoji-id='5769126056262898415'>👛</tg-emoji> <b>Введите ID пользователя:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="admin_close",
                style="danger",
                icon_custom_emoji_id="5870657884844462243"
            )]
        ])
    )
    await state.set_state(AdminStates.change_balance_user)
    await callback.answer()

@router.message(StateFilter(AdminStates.change_balance_user))
async def admin_change_balance_user(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Неверный ID!</b> Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Отмена",
                    callback_data="admin_close",
                    style="danger",
                    icon_custom_emoji_id="5870657884844462243"
                )]
            ])
        )
        return
    
    user = await get_user(user_id)
    if not user:
        await message.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Пользователь не найден!</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Отмена",
                    callback_data="admin_close",
                    style="danger",
                    icon_custom_emoji_id="5870657884844462243"
                )]
            ])
        )
        return
    
    await state.update_data(change_balance_user=user_id)
    await state.set_state(AdminStates.change_balance_amount)
    
    await message.answer(
        f"<tg-emoji emoji-id='5891207662678317861'>👤</tg-emoji> Пользователь: {user_id}\n"
        f"<tg-emoji emoji-id='5769126056262898415'>👛</tg-emoji> Текущий баланс: {user['balance']:.2f}₽\n\n"
        "<tg-emoji emoji-id='5904462880941545555'>🪙</tg-emoji> <b>Введите сумму для изменения (+ или -):</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="admin_close",
                style="danger",
                icon_custom_emoji_id="5870657884844462243"
            )]
        ])
    )

@router.message(StateFilter(AdminStates.change_balance_amount))
async def admin_change_balance_amount(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        amount = float(message.text)
    except ValueError:
        await message.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Неверная сумма!</b> Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Отмена",
                    callback_data="admin_close",
                    style="danger",
                    icon_custom_emoji_id="5870657884844462243"
                )]
            ])
        )
        return
    
    data = await state.get_data()
    user_id = data['change_balance_user']
    
    new_balance = await update_balance(user_id, amount)
    
    await state.clear()
    
    await message.answer(
        f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> <b>Баланс изменён!</b>\n\n"
        f"<tg-emoji emoji-id='5891207662678317861'>👤</tg-emoji> Пользователь: {user_id}\n"
        f"<tg-emoji emoji-id='5769126056262898415'>👛</tg-emoji> Новый баланс: {new_balance:.2f}₽",
        reply_markup=get_admin_keyboard()
    )

@router.callback_query(F.data == "admin_change_price")
async def callback_admin_change_price(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Нет доступа!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "<tg-emoji emoji-id='5870676941614354370'>🖋</tg-emoji> <b>Выберите страну для изменения цены:</b>",
        reply_markup=get_countries_keyboard()
    )
    await state.set_state(AdminStates.change_price_country)
    await callback.answer()

@router.callback_query(F.data.startswith("country_"), StateFilter(AdminStates.change_price_country))
async def callback_admin_change_price_country(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    country = callback.data.replace("country_", "")
    await state.update_data(change_price_country=country)
    await state.set_state(AdminStates.change_price_value)
    
    current_price = await get_price(country)
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='5870676941614354370'>🖋</tg-emoji> <b>Страна:</b> {country}\n"
        f"<tg-emoji emoji-id='5904462880941545555'>🪙</tg-emoji> Текущая цена: {current_price:.2f}₽\n\n"
        "<b>Введите новую цену:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="admin_close",
                style="danger",
                icon_custom_emoji_id="5870657884844462243"
            )]
        ])
    )
    await callback.answer()

@router.message(StateFilter(AdminStates.change_price_value))
async def admin_change_price_value(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    try:
        price = float(message.text)
    except ValueError:
        await message.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Неверная цена!</b> Попробуйте снова.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Отмена",
                    callback_data="admin_close",
                    style="danger",
                    icon_custom_emoji_id="5870657884844462243"
                )]
            ])
        )
        return
    
    data = await state.get_data()
    country = data['change_price_country']
    
    await set_price(country, price)
    await state.clear()
    
    await message.answer(
        f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> <b>Цена изменена!</b>\n\n"
        f"<tg-emoji emoji-id='5870528606328852614'>📁</tg-emoji> Страна: {country}\n"
        f"<tg-emoji emoji-id='5904462880941545555'>🪙</tg-emoji> Новая цена: {price:.2f}₽",
        reply_markup=get_admin_keyboard()
    )

@router.callback_query(F.data == "admin_upload_media")
async def callback_admin_upload_media(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Нет доступа!", show_alert=True)
        return
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(
        text="Главное меню",
        callback_data="media_section_main_menu",
        style="default",
        icon_custom_emoji_id="5873147866364514353"
    ))
    builder.row(InlineKeyboardButton(
        text="Профиль",
        callback_data="media_section_profile",
        style="default",
        icon_custom_emoji_id="5891207662678317861"
    ))
    builder.row(InlineKeyboardButton(
        text="Мои покупки",
        callback_data="media_section_purchases",
        style="default",
        icon_custom_emoji_id="5870528606328852614"
    ))
    builder.row(InlineKeyboardButton(
        text="Отмена",
        callback_data="admin_close",
        style="danger",
        icon_custom_emoji_id="5870657884844462243"
    ))
    
    await callback.message.edit_text(
        "<tg-emoji emoji-id='6035128606563241721'>🖼</tg-emoji> <b>Выберите раздел для загрузки медиа:</b>",
        reply_markup=builder.as_markup()
    )
    await state.set_state(AdminStates.upload_media_section)
    await callback.answer()

@router.callback_query(F.data.startswith("media_section_"), StateFilter(AdminStates.upload_media_section))
async def callback_media_section(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return
    
    section = callback.data.replace("media_section_", "")
    await state.update_data(upload_media_section=section)
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id='6035128606563241721'>🖼</tg-emoji> <b>Отправьте фото или видео для раздела:</b> {section}\n\n"
        "Можно добавить подпись.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="admin_close",
                style="danger",
                icon_custom_emoji_id="5870657884844462243"
            )]
        ])
    )
    await callback.answer()

@router.message(StateFilter(AdminStates.upload_media_section))
async def admin_upload_media_message(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    
    data = await state.get_data()
    section = data['upload_media_section']
    
    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"
    else:
        await message.answer(
            "<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> <b>Отправьте фото или видео!</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Отмена",
                    callback_data="admin_close",
                    style="danger",
                    icon_custom_emoji_id="5870657884844462243"
                )]
            ])
        )
        return
    
    caption = message.caption or ""
    
    await set_media(section, file_id, file_type, caption)
    await state.clear()
    
    await message.answer(
        f"<tg-emoji emoji-id='5870633910337015697'>✅</tg-emoji> <b>Медиа загружено!</b>\n\n"
        f"<tg-emoji emoji-id='6035128606563241721'>🖼</tg-emoji> Раздел: {section}",
        reply_markup=get_admin_keyboard()
    )

@router.callback_query(F.data == "admin_close")
async def callback_admin_close(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("<tg-emoji emoji-id='5870657884844462243'>❌</tg-emoji> Нет доступа!", show_alert=True)
        return
    
    await state.clear()
    await callback.message.edit_text(
        "<tg-emoji emoji-id='5873147866364514353'>🏘</tg-emoji> <b>Главное меню</b>",
        reply_markup=get_main_keyboard()
    )
    await callback.answer()

# --- Запуск ---
async def main():
    await init_db()
    await bot(DeleteWebhook(drop_pending_updates=True))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
