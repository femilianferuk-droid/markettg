import os
import re
import asyncio
import logging
from datetime import datetime, timedelta
from io import BytesIO
from typing import Optional

from dotenv import load_dotenv
import psycopg2
import psycopg2.extras
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    FloodWaitError
)
from telethon.sessions import StringSession

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
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
SUPPORT_USERNAME = "@VestSkypSupport"

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
    "unlock": "6037496202990194718",
    "eye": "6037397706505195857",
    "eye_hidden": "6037243349675544634",
    "house": "5873147866364514353",
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
}

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
        rating FLOAT DEFAULT 0.0,
        total_reviews INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT NOW()
    );
    
    CREATE TABLE IF NOT EXISTS accounts (
        id SERIAL PRIMARY KEY,
        seller_id BIGINT NOT NULL,
        phone TEXT NOT NULL,
        password_2fa TEXT,
        session_string TEXT,
        country TEXT NOT NULL,
        description TEXT,
        price INTEGER NOT NULL,
        status TEXT DEFAULT 'pending_verification',
        is_valid BOOLEAN DEFAULT FALSE,
        auto_username TEXT,
        auto_firstname TEXT,
        auto_lastname TEXT,
        auto_2fa BOOLEAN DEFAULT FALSE,
        buyer_id BIGINT,
        sold_at TIMESTAMP,
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

def add_transaction(user_id: int, t_type: str, amount: int, description: str = None):
    cur.execute(
        "INSERT INTO transactions (user_id, type, amount, description) VALUES (%s, %s, %s, %s)",
        (user_id, t_type, amount, description)
    )

def add_account(seller_id: int, phone: str, password_2fa: str, session_string: str,
                country: str, description: str, price: int, auto_username: str = None,
                auto_firstname: str = None, auto_lastname: str = None, auto_2fa: bool = False):
    cur.execute("""
        INSERT INTO accounts (seller_id, phone, password_2fa, session_string, country,
        description, price, auto_username, auto_firstname, auto_lastname, auto_2fa)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (seller_id, phone, password_2fa, session_string, country, description, price,
          auto_username, auto_firstname, auto_lastname, auto_2fa))
    return cur.fetchone()[0]

def get_available_accounts():
    cur.execute("""
        SELECT a.*, u.rating as seller_rating
        FROM accounts a
        JOIN users u ON a.seller_id = u.telegram_id
        WHERE a.status = 'active' AND a.is_valid = TRUE
        ORDER BY a.created_at DESC
    """)
    return cur.fetchall()

def get_account(account_id: int):
    cur.execute("SELECT * FROM accounts WHERE id = %s", (account_id,))
    return cur.fetchone()

def buy_account(account_id: int, buyer_id: int):
    cur.execute(
        "UPDATE accounts SET status = 'sold', buyer_id = %s, sold_at = NOW() WHERE id = %s",
        (buyer_id, account_id)
    )
    cur.execute(
        "INSERT INTO purchases (buyer_id, account_id) VALUES (%s, %s) RETURNING id",
        (buyer_id, account_id)
    )
    return cur.fetchone()[0]

def get_purchases(buyer_id: int):
    cur.execute("""
        SELECT p.*, a.phone, a.password_2fa, a.session_string, a.country, a.description,
               a.auto_username, a.auto_firstname, a.auto_lastname, a.auto_2fa
        FROM purchases p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.buyer_id = %s
        ORDER BY p.purchased_at DESC
    """, (buyer_id,))
    return cur.fetchall()

def get_purchase(purchase_id: int):
    cur.execute("""
        SELECT p.*, a.phone, a.password_2fa, a.session_string, a.country, a.description,
               a.auto_username, a.auto_firstname, a.auto_lastname, a.auto_2fa
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
        SET total_reviews = total_reviews + 1,
            rating = (rating * (total_reviews - 1) + %s) / total_reviews
        WHERE telegram_id = (
            SELECT a.seller_id FROM accounts a
            JOIN purchases p ON a.id = p.account_id
            WHERE p.id = %s
        )
    """, (rating, purchase_id))

def has_review(purchase_id: int):
    cur.execute("SELECT id FROM reviews WHERE purchase_id = %s", (purchase_id,))
    return cur.fetchone() is not None

def get_seller_accounts(seller_id: int):
    cur.execute("""
        SELECT * FROM accounts
        WHERE seller_id = %s AND status != 'sold'
        ORDER BY created_at DESC
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
    except Exception as e:
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
    waiting_for_country = State()
    waiting_for_description = State()
    waiting_for_price = State()

class BuyAccount(StatesGroup):
    waiting_for_code = State()

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()

# ==================== КЛАВИАТУРЫ ====================
def main_menu_keyboard():
    """Главное меню с premium-эмодзи"""
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
            url=f"tg://resolve?domain=VestSkypSupport",
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

def buy_account_keyboard(account_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Купить",
            callback_data=f"buy_{account_id}",
            icon_custom_emoji_id=EMOJI["buy"]
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
        status_emoji = EMOJI["check"] if acc[7] == "active" else EMOJI["clock"]
        buttons.append([InlineKeyboardButton(
            text=f"{acc[5]} | {acc[8]}⭐",
            callback_data=f"listing_{acc[0]}",
            icon_custom_emoji_id=status_emoji
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
            icon_custom_emoji_id=EMOJI["info"]
        )],
    ])

# ==================== ХЕНДЛЕРЫ ====================
@router.message(Command("start"))
async def cmd_start(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username)
    
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
    
    rating_text = f"⭐ {user[4]:.1f}" if user[5] > 0 else "Нет оценок"
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['profile']}\">👤</tg-emoji> <b>Профиль</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['wallet']}\">👛</tg-emoji> Баланс: {user[3]} ⭐\n"
        f"{rating_text} ({user[5]} отзывов)",
        reply_markup=profile_keyboard()
    )

@router.callback_query(F.data == "back_to_profile")
async def back_to_profile(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    rating_text = f"⭐ {user[4]:.1f}" if user[5] > 0 else "Нет оценок"
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['profile']}\">👤</tg-emoji> <b>Профиль</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['wallet']}\">👛</tg-emoji> Баланс: {user[3]} ⭐\n"
        f"{rating_text} ({user[5]} отзывов)",
        reply_markup=profile_keyboard()
    )

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
            f"отправленный в Telegram:"
        )
        await state.set_state(SellAccount.waiting_for_code)
    elif result["valid"]:
        await state.update_data(session_string=result["session_string"])
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Аккаунт валиден!\n"
            f"Введите страну аккаунта (например, Россия, USA):"
        )
        await state.set_state(SellAccount.waiting_for_country)
    else:
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Ошибка: {result['error']}"
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
        await state.update_data(
            session_string=result["session_string"],
            auto_username=result["user_info"]["username"],
            auto_firstname=result["user_info"]["first_name"],
            auto_lastname=result["user_info"]["last_name"],
            auto_2fa=False
        )
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Аккаунт подтверждён!\n"
            f"Введите страну аккаунта (например, Россия, USA):"
        )
        await state.set_state(SellAccount.waiting_for_country)
    else:
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Ошибка: {result['error']}"
        )
        await state.clear()

@router.message(StateFilter(SellAccount.waiting_for_2fa))
async def sell_account_2fa(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    
    if password.lower() == 'нет':
        password = None
    
    status_msg = await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['clock']}\">⏰</tg-emoji> Проверяю 2FA..."
    )
    
    if password:
        result = await sign_in_with_2fa(data["session_string"], password)
    else:
        result = {"success": True, "session_string": data["session_string"], 
                  "user_info": {"username": None, "first_name": None, "last_name": None, "has_2fa": False}}
    
    if result["success"]:
        await state.update_data(
            session_string=result["session_string"],
            auto_username=result["user_info"]["username"],
            auto_firstname=result["user_info"]["first_name"],
            auto_lastname=result["user_info"]["last_name"],
            auto_2fa=result["user_info"]["has_2fa"],
            password_2fa=password
        )
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Аккаунт подтверждён!\n"
            f"Введите страну аккаунта (например, Россия, USA):"
        )
        await state.set_state(SellAccount.waiting_for_country)
    else:
        await status_msg.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Ошибка: {result['error']}"
        )
        await state.clear()

@router.message(StateFilter(SellAccount.waiting_for_country))
async def sell_account_country(message: Message, state: FSMContext):
    country = message.text.strip()
    await state.update_data(country=country)
    
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
    
    cur.execute(
        "UPDATE accounts SET status = 'active', is_valid = TRUE WHERE id = %s",
        (account_id,)
    )
    
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Аккаунт успешно выставлен на продажу!\n"
        f"<tg-emoji emoji-id=\"{EMOJI['money']}\">🪙</tg-emoji> Цена: {price} ⭐\n"
        f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна: {data['country']}",
        reply_markup=main_menu_keyboard()
    )
    await state.clear()

@router.callback_query(F.data == "buy_account")
async def buy_account_list(callback: CallbackQuery):
    accounts = get_available_accounts()
    
    if not accounts:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> Нет доступных аккаунтов для покупки.",
            reply_markup=back_keyboard()
        )
        return
    
    for acc in accounts:
        seller = get_user(acc[1])
        seller_info = f"Продавец: {seller[2] or 'Нет username'}"
        if seller[5] > 0:
            seller_info += f" | ⭐ {seller[4]:.1f}"
        
        text = (
            f"{seller_info}\n"
            f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна: {acc[5]}\n"
            f"<tg-emoji emoji-id=\"{EMOJI['money']}\">🪙</tg-emoji> Цена: {acc[8]} ⭐\n"
            f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> {acc[6] or 'Нет описания'}"
        )
        
        await callback.message.answer(
            text,
            reply_markup=buy_account_keyboard(acc[0])
        )

@router.callback_query(F.data == "back_to_list")
async def back_to_list(callback: CallbackQuery):
    await buy_account_list(callback)

@router.callback_query(F.data.startswith("buy_"))
async def buy_account_confirm(callback: CallbackQuery):
    account_id = int(callback.data.split("_")[1])
    account = get_account(account_id)
    
    if not account or account[7] != "active":
        await callback.answer("Аккаунт уже не доступен", show_alert=True)
        await callback.message.delete()
        return
    
    buyer = get_user(callback.from_user.id)
    seller = get_user(account[1])
    
    if buyer[3] < account[8]:
        await callback.answer(
            f"Недостаточно средств! Ваш баланс: {buyer[3]} ⭐, нужно: {account[8]} ⭐",
            show_alert=True
        )
        return
    
    await callback.answer("Проверяю актуальность аккаунта...")
    
    result = await verify_account(session_string=account[4])
    
    if not result["valid"]:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['cross']}\">❌</tg-emoji> Аккаунт больше не валиден.",
            reply_markup=back_keyboard()
        )
        return
    
    update_balance(callback.from_user.id, -account[8])
    update_balance(account[1], account[8])
    
    add_transaction(callback.from_user.id, "purchase", -account[8], f"Покупка аккаунта #{account_id}")
    add_transaction(account[1], "sale", account[8], f"Продажа аккаунта #{account_id}")
    
    purchase_id = buy_account(account_id, callback.from_user.id)
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['check']}\">✅</tg-emoji> Вы успешно купили аккаунт!\n"
        f"Списано: {account[8]} ⭐",
        reply_markup=back_keyboard()
    )
    
    try:
        await bot.send_message(
            account[1],
            f"<tg-emoji emoji-id=\"{EMOJI['gift']}\">🎁</tg-emoji> Ваш аккаунт #{account_id} был продан!\n"
            f"На баланс зачислено: {account[8]} ⭐"
        )
    except:
        pass

@router.callback_query(F.data == "my_purchases")
async def my_purchases(callback: CallbackQuery):
    purchases = get_purchases(callback.from_user.id)
    
    if not purchases:
        await callback.message.edit_text(
            f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> У вас пока нет покупок.",
            reply_markup=back_keyboard()
        )
        return
    
    buttons = []
    for p in purchases:
        buttons.append([InlineKeyboardButton(
            text=f"Покупка #{p[0]} | {p[8] if len(p) > 8 else 'Нет данных'}",
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
    
    if not purchase or purchase[1] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    text = (
        f"<tg-emoji emoji-id=\"{EMOJI['box']}\">📦</tg-emoji> <b>Покупка #{purchase[0]}</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна: {purchase[8]}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> Описание: {purchase[9] or 'Нет'}\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['phone']}\">📁</tg-emoji> Номер: <code>{purchase[5]}</code>\n"
    )
    
    if purchase[6]:
        text += f"<tg-emoji emoji-id=\"{EMOJI['lock']}\">🔒</tg-emoji> 2FA: <code>{purchase[6]}</code>\n"
    
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
    
    if not purchase or purchase[1] != callback.from_user.id:
        await callback.answer("Покупка не найдена", show_alert=True)
        return
    
    await callback.answer("Получаю код...")
    
    status_msg = await callback.message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['clock']}\">⏰</tg-emoji> Ищу код в чатах..."
    )
    
    code = await get_code_from_chat(purchase[7])
    
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
    
    if not account or account[1] != callback.from_user.id:
        await callback.answer("Объявление не найдено", show_alert=True)
        return
    
    text = (
        f"<tg-emoji emoji-id=\"{EMOJI['tag']}\">🏷</tg-emoji> <b>Объявление #{account_id}</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['globe']}\">📍</tg-emoji> Страна: {account[5]}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['money']}\">🪙</tg-emoji> Цена: {account[8]} ⭐\n"
        f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> Статус: {account[7]}\n"
        f"Описание: {account[6] or 'Нет'}"
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
    
    await state.update_data(admin_user_id=user_id)
    await message.answer(
        f"<tg-emoji emoji-id=\"{EMOJI['profile']}\">👤</tg-emoji> Пользователь: {user[2] or 'Без username'}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['wallet']}\">👛</tg-emoji> Баланс: {user[3]} ⭐\n\n"
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
    
    await callback.message.edit_text(
        f"<tg-emoji emoji-id=\"{EMOJI['info']}\">ℹ</tg-emoji> <b>Статистика:</b>\n\n"
        f"<tg-emoji emoji-id=\"{EMOJI['profile']}\">👤</tg-emoji> Пользователей: {total_users}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['tag']}\">🏷</tg-emoji> Активных объявлений: {active_accounts}\n"
        f"<tg-emoji emoji-id=\"{EMOJI['box']}\">📦</tg-emoji> Всего покупок: {total_purchases}",
        reply_markup=back_keyboard()
    )

# ==================== ЗАПУСК ====================
async def main():
    init_db()
    print("База данных инициализирована")
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
