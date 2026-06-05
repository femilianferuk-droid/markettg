import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from decimal import Decimal

import psycopg2
from psycopg2.extensions import AsIs
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, LabeledPrice, PreCheckoutQuery,
)
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import aiohttp

load_dotenv()

# ============ CONFIG ============
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"
ADMIN_ID = 7973988177

# ============ LOGGING ============
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ EMOJI IDS ============
EMOJI = {
    "box": "5884479287171485878",
    "folder": "5870528606328852614",
    "profile": "5891207662678317861",
    "settings": "5870982283724328568",
    "home": "5873147866364514353",
    "check": "5870633910337015697",
    "cross": "5870657884844462243",
    "lock": "6037249452824072506",
    "unlock": "6037496202990194718",
    "stats": "5870930636742595124",
    "broadcast": "6039422865189638057",
    "edit": "5870676941614354370",
    "media": "6035128606563241721",
    "wallet": "5769126056262898415",
    "crypto": "5260752406890711732",
    "stars": "5904462880941545555",
    "loading": "5345906554510012647",
    "back": "5893057118545646106",
    "money": "5904462880941545555",
    "gift": "6032644646587338669",
    "clock": "5983150113483134607",
    "party": "6041731551845159060",
    "bot": "6030400221232501136",
    "info": "6028435952299413210",
    "trash": "5870875489362513438",
    "tag": "5886285355279193209",
    "calendar": "5890937706803894250",
    "people": "5870772616305839506",
    "eye": "6037397706505195857",
    "send": "5963103826075456248",
    "download": "6039802767931871481",
    "bell": "6039486778597970865",
    "pin": "6042011682497106307",
    "link": "5769289093221454192",
    "clip": "6039451237743595514",
    "code": "5940433880585605708",
    "write": "5870753782874246579",
    "apps": "5778672437122045013",
    "brush": "6050679691004612757",
    "time_past": "5775896410780079073",
    "add_text": "5771851822897566479",
    "resize": "5778479949572738874",
    "send_money": "5890848474563352982",
    "accept_money": "5879814368572478751",
    "smile": "5870764288364252592",
    "stats2": "5870921681735781843",
    "person_check": "5891207662678317861",
    "person_cross": "5893192487324880883",
    "eye_hide": "6037243349675544634",
    "font": "5870801517140775623",
    "broadcast_icon": "5370599459661045441",
    "blue": "5373141891321699086",
    "red": "5370810157871667232",
    "green": "5471984997361523302",
    "subscribe": "6039450962865688331",
    "check_sub": "5774022692642492953",
}

def em(text, emoji_id):
    return f'<tg-emoji emoji-id="{emoji_id}">{text}</tg-emoji>'

# ============ DATABASE ============
def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY,
            username TEXT,
            balance DECIMAL DEFAULT 0,
            total_purchases INT DEFAULT 0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id SERIAL PRIMARY KEY,
            phone TEXT UNIQUE,
            country TEXT,
            session_string TEXT,
            password_2fa TEXT,
            is_sold BOOLEAN DEFAULT FALSE,
            is_valid BOOLEAN DEFAULT TRUE,
            is_reserved BOOLEAN DEFAULT FALSE,
            reserved_until TIMESTAMP,
            reserved_by BIGINT,
            sold_to BIGINT,
            buy_price DECIMAL DEFAULT 100.0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            account_id INT REFERENCES accounts(id),
            purchase_date TIMESTAMP DEFAULT NOW(),
            code_obtained BOOLEAN DEFAULT FALSE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS price_settings (
            country TEXT PRIMARY KEY,
            buy_price DECIMAL DEFAULT 100.0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS media_settings (
            section TEXT PRIMARY KEY,
            file_id TEXT,
            file_type TEXT,
            caption TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS crypto_payments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            payment_id TEXT,
            invoice_id TEXT UNIQUE,
            amount DECIMAL,
            currency TEXT,
            status TEXT DEFAULT 'pending',
            account_id INT REFERENCES accounts(id),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def ensure_user(user_id: int, username: str = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE id = %s", (AsIs(str(user_id)),))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (id, username) VALUES (%s, %s)",
            (AsIs(str(user_id)), username)
        )
        conn.commit()
    cur.close()
    conn.close()

# ============ BOT INIT ============
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ============ COUNTRIES ============
COUNTRIES = [
    ("Россия", "russia", "🇷🇺"),
    ("США", "usa", "🇺🇸"),
    ("Германия", "germany", "🇩🇪"),
    ("Франция", "france", "🇫🇷"),
    ("Великобритания", "uk", "🇬🇧"),
    ("Италия", "italy", "🇮🇹"),
    ("Испания", "spain", "🇪🇸"),
    ("Польша", "poland", "🇵🇱"),
    ("Нидерланды", "netherlands", "🇳🇱"),
    ("Бельгия", "belgium", "🇧🇪"),
    ("Швейцария", "switzerland", "🇨🇭"),
    ("Австрия", "austria", "🇦🇹"),
    ("Швеция", "sweden", "🇸🇪"),
    ("Норвегия", "norway", "🇳🇴"),
    ("Дания", "denmark", "🇩🇰"),
    ("Финляндия", "finland", "🇫🇮"),
    ("Португалия", "portugal", "🇵🇹"),
    ("Греция", "greece", "🇬🇷"),
    ("Чехия", "czech", "🇨🇿"),
    ("Румыния", "romania", "🇷🇴"),
    ("Венгрия", "hungary", "🇭🇺"),
    ("Украина", "ukraine", "🇺🇦"),
    ("Беларусь", "belarus", "🇧🇾"),
    ("Казахстан", "kazakhstan", "🇰🇿"),
    ("Турция", "turkey", "🇹🇷"),
    ("Бразилия", "brazil", "🇧🇷"),
    ("Мексика", "mexico", "🇲🇽"),
    ("Аргентина", "argentina", "🇦🇷"),
    ("Канада", "canada", "🇨🇦"),
    ("Австралия", "australia", "🇦🇺"),
    ("Япония", "japan", "🇯🇵"),
    ("Южная Корея", "south_korea", "🇰🇷"),
    ("Китай", "china", "🇨🇳"),
    ("Индия", "india", "🇮🇳"),
    ("Индонезия", "indonesia", "🇮🇩"),
    ("Вьетнам", "vietnam", "🇻🇳"),
    ("Таиланд", "thailand", "🇹🇭"),
    ("Филиппины", "philippines", "🇵🇭"),
    ("Малайзия", "malaysia", "🇲🇾"),
    ("Сингапур", "singapore", "🇸🇬"),
    ("ОАЭ", "uae", "🇦🇪"),
    ("Саудовская Аравия", "saudi_arabia", "🇸🇦"),
    ("ЮАР", "south_africa", "🇿🇦"),
    ("Нигерия", "nigeria", "🇳🇬"),
    ("Египет", "egypt", "🇪🇬"),
]

ITEMS_PER_PAGE = 10

# ============ STATES ============
class BuyStates(StatesGroup):
    waiting_payment = State()

class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_balance_user = State()
    waiting_balance_amount = State()
    waiting_price_country = State()
    waiting_price_amount = State()
    waiting_media = State()

# ============ KEYBOARDS ============
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(
                text=f"{em('', EMOJI['box'])} Купить аккаунт",
            )],
            [KeyboardButton(
                text=f"{em('', EMOJI['folder'])} Мои покупки",
            )],
            [KeyboardButton(
                text=f"{em('', EMOJI['profile'])} Профиль",
            )]
        ],
        resize_keyboard=True
    )

def get_countries_keyboard(page: int = 0):
    total_pages = (len(COUNTRIES) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_countries = COUNTRIES[start:end]

    buttons = []
    for name, code, flag in page_countries:
        buttons.append([InlineKeyboardButton(
            text=f"{flag} {name}",
            callback_data=f"country_{code}"
        )])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            text=f"{em('', EMOJI['back'])} Назад",
            callback_data=f"countries_page_{page-1}"
        ))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton(
            text=f"Вперед {em('', EMOJI['back'])}",
            callback_data=f"countries_page_{page+1}"
        ))

    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.append([InlineKeyboardButton(
        text=f"{em('', EMOJI['home'])} Главное меню",
        callback_data="main_menu"
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_payment_keyboard(account_id: int, price: float):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['stars'])} Telegram Stars ({int(price)} ⭐)",
            callback_data=f"pay_stars_{account_id}"
        )],
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['crypto'])} Crypto Bot ({price} RUB)",
            callback_data=f"pay_crypto_{account_id}"
        )],
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['wallet'])} Баланс ({price} RUB)",
            callback_data=f"pay_balance_{account_id}"
        )],
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['cross'])} Отмена",
            callback_data="cancel_payment"
        )]
    ])

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['stats'])} Статистика",
            callback_data="admin_stats"
        )],
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['broadcast'])} Рассылка",
            callback_data="admin_broadcast"
        )],
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['wallet'])} Изменить баланс",
            callback_data="admin_balance"
        )],
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['edit'])} Изменить цены",
            callback_data="admin_prices"
        )],
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['media'])} Загрузить медиа",
            callback_data="admin_media"
        )],
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['cross'])} Закрыть",
            callback_data="main_menu"
        )]
    ])

def get_back_to_purchases_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['back'])} Назад",
            callback_data="my_purchases"
        )]
    ])

# ============ TELETHON UTILS ============
async def check_session_valid(session_string: str) -> bool:
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        is_valid = await client.is_user_authorized()
        await client.disconnect()
        return is_valid
    except Exception as e:
        logger.error(f"Session check error: {e}")
        return False

async def get_login_code(session_string: str, password_2fa: str = None) -> str | None:
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()

        if not await client.is_user_authorized():
            await client.disconnect()
            return None

        if password_2fa:
            try:
                await client.sign_in(password=password_2fa)
            except SessionPasswordNeededError:
                pass

        telegram_chat = None
        async for dialog in client.iter_dialogs():
            if dialog.name == "Telegram" and dialog.is_user:
                telegram_chat = dialog
                break

        if not telegram_chat:
            await client.disconnect()
            return None

        messages = await client.get_messages(telegram_chat, limit=5)
        await client.disconnect()

        for msg in messages:
            if msg.text:
                match = re.search(r'\b\d{5}\b', msg.text)
                if match:
                    return match.group(0)

        return None
    except Exception as e:
        logger.error(f"Get code error: {e}")
        return None

# ============ CRYPTO BOT API ============
async def create_crypto_invoice(amount: float, currency: str = "RUB") -> dict | None:
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            data = {
                "asset": currency,
                "amount": str(amount)
            }
            async with session.get(
                "https://pay.crypt.bot/api/createInvoice",
                headers=headers,
                params=data
            ) as resp:
                result = await resp.json()
                if result.get("ok"):
                    return result["result"]
                return None
    except Exception as e:
        logger.error(f"Crypto API error: {e}")
        return None

async def check_crypto_invoice(invoice_id: int) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            params = {"invoice_id": invoice_id}
            async with session.get(
                "https://pay.crypt.bot/api/getInvoice",
                headers=headers,
                params=params
            ) as resp:
                result = await resp.json()
                if result.get("ok"):
                    return result["result"]["status"]
                return "error"
    except Exception as e:
        logger.error(f"Crypto check error: {e}")
        return "error"

# ============ ACCOUNT LOGIC ============
async def find_and_validate_account(country_code: str) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, phone, country, session_string, password_2fa, buy_price
        FROM accounts
        WHERE country = %s
        AND is_sold = FALSE
        AND is_valid = TRUE
        AND (is_reserved = FALSE OR reserved_until < NOW())
        LIMIT 10
    """, (country_code,))

    accounts = cur.fetchall()

    for acc in accounts:
        acc_id, phone, country, session_string, password_2fa, buy_price = acc
        is_valid = await check_session_valid(session_string)

        if is_valid:
            cur.execute(
                "UPDATE accounts SET is_reserved = TRUE, reserved_until = %s WHERE id = %s",
                (datetime.now() + timedelta(minutes=5), acc_id)
            )
            conn.commit()
            cur.close()
            conn.close()
            return {
                "id": acc_id,
                "phone": phone,
                "country": country,
                "session_string": session_string,
                "password_2fa": password_2fa,
                "buy_price": float(buy_price)
            }
        else:
            cur.execute("UPDATE accounts SET is_valid = FALSE WHERE id = %s", (acc_id,))
            conn.commit()

    cur.close()
    conn.close()
    return None

async def reserve_timeout(account_id: int, delay: int = 300):
    await asyncio.sleep(delay)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE accounts
        SET is_reserved = FALSE, reserved_until = NULL, reserved_by = NULL
        WHERE id = %s AND is_sold = FALSE AND is_reserved = TRUE
    """, (account_id,))
    conn.commit()
    cur.close()
    conn.close()

def complete_purchase(user_id: int, account_id: int, payment_method: str):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        UPDATE accounts
        SET is_sold = TRUE, is_reserved = FALSE, sold_to = %s
        WHERE id = %s
    """, (AsIs(str(user_id)), account_id))

    cur.execute(
        "INSERT INTO purchases (user_id, account_id) VALUES (%s, %s)",
        (AsIs(str(user_id)), account_id)
    )

    cur.execute("""
        UPDATE users SET total_purchases = total_purchases + 1
        WHERE id = %s
    """, (AsIs(str(user_id)),))

    conn.commit()
    cur.close()
    conn.close()

# ============ HANDLERS ============
@router.message(Command("start"))
async def cmd_start(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"{em('', EMOJI['party'])} Добро пожаловать в <b>Vest Market</b>!\n\n"
        f"{em('', EMOJI['box'])} Здесь вы можете купить Telegram аккаунты\n"
        f"{em('', EMOJI['info'])} Выберите действие в меню:",
        reply_markup=get_main_menu()
    )

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(f"{em('', EMOJI['cross'])} У вас нет доступа к админ-панели")
        return

    await message.answer(
        f"{em('', EMOJI['settings'])} <b>Админ-панель</b>\n\n"
        f"Выберите действие:",
        reply_markup=get_admin_keyboard()
    )

@router.message(F.text.contains("Купить аккаунт"))
async def buy_account(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"{em('', EMOJI['box'])} <b>Выберите страну:</b>",
        reply_markup=get_countries_keyboard(0)
    )

@router.message(F.text.contains("Мои покупки"))
async def my_purchases(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    await show_purchases(message)

@router.message(F.text.contains("Профиль"))
async def profile(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT balance, total_purchases, created_at FROM users WHERE id = %s",
        (AsIs(str(message.from_user.id)),)
    )
    user = cur.fetchone()
    cur.close()
    conn.close()

    if user:
        balance, total, created = user
        await message.answer(
            f"{em('', EMOJI['profile'])} <b>Профиль</b>\n\n"
            f"{em('', EMOJI['wallet'])} Баланс: <b>{balance} RUB</b>\n"
            f"{em('', EMOJI['box'])} Куплено аккаунтов: <b>{total}</b>\n"
            f"{em('', EMOJI['calendar'])} Дата регистрации: <b>{created.strftime('%d.%m.%Y')}</b>"
        )

async def show_purchases(message_or_query, user_id: int = None):
    if user_id is None:
        user_id = message_or_query.from_user.id

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, a.phone, a.country, p.purchase_date, a.password_2fa, p.code_obtained, a.id
        FROM purchases p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.user_id = %s
        ORDER BY p.purchase_date DESC
    """, (AsIs(str(user_id)),))
    purchases = cur.fetchall()
    cur.close()
    conn.close()

    if not purchases:
        text = f"{em('', EMOJI['info'])} У вас пока нет покупок"
        if hasattr(message_or_query, 'answer'):
            await message_or_query.answer(text)
        else:
            await message_or_query.message.edit_text(text)
        return

    buttons = []
    for p in purchases:
        p_id, phone, country, date, pwd, code_obt, acc_id = p
        lock_emoji = EMOJI['lock'] if pwd else EMOJI['unlock']
        code_status = f"{em('', EMOJI['check'])} " if code_obt else ""
        buttons.append([InlineKeyboardButton(
            text=f"{code_status}{phone} | {country} {em('', lock_emoji)}",
            callback_data=f"purchase_detail_{p_id}"
        )])

    buttons.append([InlineKeyboardButton(
        text=f"{em('', EMOJI['home'])} Главное меню",
        callback_data="main_menu"
    )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"{em('', EMOJI['folder'])} <b>Мои покупки</b>\n\nВыберите аккаунт:"

    if hasattr(message_or_query, 'answer'):
        await message_or_query.answer(text, reply_markup=kb)
    else:
        await message_or_query.message.edit_text(text, reply_markup=kb)

# ============ CALLBACK HANDLERS ============
@router.callback_query(F.data.startswith("countries_page_"))
async def countries_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[-1])
    await callback.message.edit_text(
        f"{em('', EMOJI['box'])} <b>Выберите страну:</b>",
        reply_markup=get_countries_keyboard(page)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("country_"))
async def country_selected(callback: CallbackQuery, state: FSMContext):
    country_code = callback.data.replace("country_", "")

    country_name = country_code
    for name, code, flag in COUNTRIES:
        if code == country_code:
            country_name = f"{flag} {name}"
            break

    await callback.message.edit_text(
        f"{em('', EMOJI['loading'])} Ищу аккаунт..."
    )
    await callback.answer()

    account = await find_and_validate_account(country_code)

    if not account:
        await callback.message.edit_text(
            f"{em('', EMOJI['cross'])} К сожалению, свободных аккаунтов для {country_name} нет.\n"
            f"Попробуйте другую страну или зайдите позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{em('', EMOJI['back'])} К выбору стран",
                    callback_data="countries_page_0"
                )]
            ])
        )
        return

    # Запуск таймера резерва
    asyncio.create_task(reserve_timeout(account['id']))

    price = account['buy_price']
    await callback.message.edit_text(
        f"{em('', EMOJI['check'])} <b>Аккаунт найден!</b>\n\n"
        f"{em('', EMOJI['info'])} Страна: <b>{country_name}</b>\n"
        f"{em('', EMOJI['wallet'])} Цена: <b>{price} RUB</b>\n\n"
        f"Выберите способ оплаты:",
        reply_markup=get_payment_keyboard(account['id'], price)
    )

@router.callback_query(F.data.startswith("pay_stars_"))
async def pay_stars(callback: CallbackQuery):
    account_id = int(callback.data.replace("pay_stars_", ""))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT buy_price FROM accounts WHERE id = %s", (account_id,))
    acc = cur.fetchone()
    cur.close()
    conn.close()

    if not acc:
        await callback.answer(f"Аккаунт не найден", show_alert=True)
        return

    price = int(float(acc[0]))

    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Покупка Telegram аккаунта",
        description=f"Аккаунт Telegram | Vest Market",
        payload=f"stars_{account_id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Аккаунт Telegram", amount=price)],
    )

    await callback.message.delete()
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout(pre_checkout: PreCheckoutQuery):
    await pre_checkout.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("stars_"):
        account_id = int(payload.replace("stars_", ""))
        complete_purchase(message.from_user.id, account_id, "stars")
        await send_account_info(message, account_id)

@router.callback_query(F.data.startswith("pay_crypto_"))
async def pay_crypto(callback: CallbackQuery):
    account_id = int(callback.data.replace("pay_crypto_", ""))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT buy_price FROM accounts WHERE id = %s", (account_id,))
    acc = cur.fetchone()
    cur.close()
    conn.close()

    if not acc:
        await callback.answer(f"Аккаунт не найден", show_alert=True)
        return

    price = float(acc[0])

    invoice = await create_crypto_invoice(price, "RUB")
    if not invoice:
        await callback.answer(f"Ошибка создания счета", show_alert=True)
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO crypto_payments (user_id, invoice_id, amount, currency, account_id) VALUES (%s, %s, %s, %s, %s)",
        (AsIs(str(callback.from_user.id)), str(invoice["invoice_id"]), price, "RUB", account_id)
    )
    conn.commit()
    cur.close()
    conn.close()

    await callback.message.edit_text(
        f"{em('', EMOJI['crypto'])} <b>Счет создан!</b>\n\n"
        f"Сумма: <b>{price} RUB</b>\n"
        f"Ссылка: {invoice.get('pay_url', invoice.get('bot_invoice_url', ''))}\n\n"
        f"После оплаты нажмите кнопку проверки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{em('', EMOJI['loading'])} Проверить оплату",
                callback_data=f"check_crypto_{invoice['invoice_id']}_{account_id}"
            )],
            [InlineKeyboardButton(
                text=f"{em('', EMOJI['cross'])} Отмена",
                callback_data="cancel_payment"
            )]
        ])
    )
    await callback.answer()

@router.callback_query(F.data.startswith("check_crypto_"))
async def check_crypto(callback: CallbackQuery):
    parts = callback.data.split("_")
    invoice_id = parts[2]
    account_id = int(parts[3])

    status = await check_crypto_invoice(int(invoice_id))

    if status == "paid":
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE crypto_payments SET status = 'paid' WHERE invoice_id = %s",
            (invoice_id,)
        )
        conn.commit()
        cur.close()
        conn.close()

        complete_purchase(callback.from_user.id, account_id, "crypto")
        await callback.message.delete()
        await send_account_info(callback.message, account_id)
    elif status == "active":
        await callback.answer("Счет еще не оплачен", show_alert=True)
    else:
        await callback.answer("Ошибка проверки или счет отменен", show_alert=True)

@router.callback_query(F.data.startswith("pay_balance_"))
async def pay_balance(callback: CallbackQuery):
    account_id = int(callback.data.replace("pay_balance_", ""))
    user_id = callback.from_user.id

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT buy_price FROM accounts WHERE id = %s", (account_id,))
    acc = cur.fetchone()
    cur.execute("SELECT balance FROM users WHERE id = %s", (AsIs(str(user_id)),))
    user = cur.fetchone()
    cur.close()
    conn.close()

    if not acc or not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    price = float(acc[0])
    balance = float(user[0])

    if balance < price:
        await callback.answer(f"Недостаточно средств! Баланс: {balance} RUB", show_alert=True)
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET balance = balance - %s WHERE id = %s",
        (price, AsIs(str(user_id)))
    )
    conn.commit()
    cur.close()
    conn.close()

    complete_purchase(user_id, account_id, "balance")
    await callback.message.delete()
    await send_account_info(callback.message, account_id)
    await callback.answer(f"{em('', EMOJI['check'])} Оплачено с баланса!", show_alert=True)

@router.callback_query(F.data == "cancel_payment")
async def cancel_payment(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        f"{em('', EMOJI['cross'])} Покупка отменена",
        reply_markup=get_main_menu()
    )
    await callback.answer()

async def send_account_info(message_or_query, account_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT phone, password_2fa, country FROM accounts WHERE id = %s", (account_id,))
    acc = cur.fetchone()
    cur.close()
    conn.close()

    if not acc:
        return

    phone, pwd, country = acc
    pwd_text = pwd if pwd else "Отсутствует"

    text = (
        f"{em('', EMOJI['party'])} <b>Покупка успешна!</b>\n\n"
        f"{em('', EMOJI['info'])} Номер: <code>{phone}</code>\n"
        f"{em('', EMOJI['lock'])} 2FA пароль: <code>{pwd_text}</code>\n\n"
        f"Нажмите кнопку ниже чтобы получить код авторизации:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['code'])} Получить код",
            callback_data=f"get_code_{account_id}"
        )],
        [InlineKeyboardButton(
            text=f"{em('', EMOJI['home'])} Главное меню",
            callback_data="main_menu"
        )]
    ])

    if hasattr(message_or_query, 'answer'):
        await message_or_query.answer(text, reply_markup=kb)
    else:
        await bot.send_message(message_or_query.chat.id, text, reply_markup=kb)

@router.callback_query(F.data.startswith("get_code_"))
async def get_code(callback: CallbackQuery):
    account_id = int(callback.data.replace("get_code_", ""))
    user_id = callback.from_user.id

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.session_string, a.password_2fa, p.code_obtained, p.id
        FROM accounts a
        JOIN purchases p ON a.id = p.account_id
        WHERE a.id = %s AND p.user_id = %s
    """, (account_id, AsIs(str(user_id))))
    result = cur.fetchone()

    if not result:
        await callback.answer("Аккаунт не найден", show_alert=True)
        cur.close()
        conn.close()
        return

    session_string, pwd, code_obtained, purchase_id = result

    if code_obtained:
        await callback.answer(f"{em('', EMOJI['info'])} Код уже был получен ранее", show_alert=True)
        cur.close()
        conn.close()
        return

    await callback.answer(f"{em('', EMOJI['loading'])} Получаю код...")
    await callback.message.edit_text(f"{em('', EMOJI['loading'])} Получаю код авторизации...")

    code = await get_login_code(session_string, pwd)

    if code:
        cur.execute(
            "UPDATE purchases SET code_obtained = TRUE WHERE id = %s",
            (purchase_id,)
        )
        conn.commit()

        await callback.message.edit_text(
            f"{em('', EMOJI['check'])} <b>Код авторизации:</b>\n\n"
            f"<code>{code}</code>\n\n"
            f"{em('', EMOJI['info'])} Код можно получить только один раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{em('', EMOJI['home'])} Главное меню",
                    callback_data="main_menu"
                )]
            ])
        )
    else:
        await callback.message.edit_text(
            f"{em('', EMOJI['cross'])} Не удалось получить код. Возможно сообщение еще не пришло.\n"
            f"Попробуйте позже в разделе {em('', EMOJI['folder'])} Мои покупки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{em('', EMOJI['home'])} Главное меню",
                    callback_data="main_menu"
                )]
            ])
        )

    cur.close()
    conn.close()

@router.callback_query(F.data == "my_purchases")
async def show_purchases_callback(callback: CallbackQuery):
    await show_purchases(callback)

@router.callback_query(F.data.startswith("purchase_detail_"))
async def purchase_detail(callback: CallbackQuery):
    purchase_id = int(callback.data.replace("purchase_detail_", ""))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.phone, a.country, a.password_2fa, p.purchase_date, p.code_obtained, a.id
        FROM purchases p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.id = %s
    """, (purchase_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()

    if not result:
        await callback.answer("Покупка не найдена", show_alert=True)
        return

    phone, country, pwd, date, code_obtained, account_id = result
    pwd_text = pwd if pwd else "Отсутствует"
    code_status = f"{em('', EMOJI['check'])} Получен" if code_obtained else f"{em('', EMOJI['cross'])} Не получен"

    text = (
        f"{em('', EMOJI['info'])} <b>Детали аккаунта</b>\n\n"
        f"{em('', EMOJI['info'])} Номер: <code>{phone}</code>\n"
        f"{em('', EMOJI['info'])} Страна: {country}\n"
        f"{em('', EMOJI['lock'])} 2FA: <code>{pwd_text}</code>\n"
        f"{em('', EMOJI['calendar'])} Куплен: {date.strftime('%d.%m.%Y %H:%M')}\n"
        f"{em('', EMOJI['code'])} Код: {code_status}"
    )

    buttons = []
    if not code_obtained:
        buttons.append([InlineKeyboardButton(
            text=f"{em('', EMOJI['code'])} Получить код",
            callback_data=f"get_code_{account_id}"
        )])
    buttons.append([InlineKeyboardButton(
        text=f"{em('', EMOJI['back'])} Назад к покупкам",
        callback_data="my_purchases"
    )])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def main_menu_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        f"{em('', EMOJI['home'])} <b>Главное меню</b>\n\nВыберите действие:",
        reply_markup=get_main_menu()
    )
    await callback.answer()

# ============ ADMIN HANDLERS ============
@router.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    total_users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM accounts")
    total_accounts = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM accounts WHERE is_sold = TRUE")
    sold = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM accounts WHERE is_sold = FALSE AND is_valid = TRUE")
    available = cur.fetchone()[0]
    cur.close()
    conn.close()

    await callback.message.edit_text(
        f"{em('', EMOJI['stats'])} <b>Статистика</b>\n\n"
        f"{em('', EMOJI['people'])} Пользователей: <b>{total_users}</b>\n"
        f"{em('', EMOJI['box'])} Всего аккаунтов: <b>{total_accounts}</b>\n"
        f"{em('', EMOJI['check'])} Продано: <b>{sold}</b>\n"
        f"{em('', EMOJI['info'])} Доступно: <b>{available}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{em('', EMOJI['back'])} Назад",
                callback_data="admin_back"
            )]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    await callback.message.edit_text(
        f"{em('', EMOJI['settings'])} <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        f"{em('', EMOJI['broadcast_icon'])} <b>Отправьте сообщение для рассылки</b>\n\n"
        f"Можно отправить текст, фото или видео с подписью.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{em('', EMOJI['cross'])} Отмена",
                callback_data="admin_back"
            )]
        ])
    )
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.answer()

@router.message(AdminStates.waiting_broadcast)
async def broadcast_message(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()

    sent = 0
    for user in users:
        try:
            if message.photo:
                await bot.send_photo(
                    user[0],
                    message.photo[-1].file_id,
                    caption=message.caption or ""
                )
            elif message.video:
                await bot.send_video(
                    user[0],
                    message.video.file_id,
                    caption=message.caption or ""
                )
            else:
                await bot.send_message(user[0], message.text or message.caption or "")
            sent += 1
        except Exception as e:
            logger.error(f"Broadcast error to {user[0]}: {e}")
        await asyncio.sleep(0.05)

    await message.answer(
        f"{em('', EMOJI['check'])} Рассылка завершена!\n"
        f"Отправлено: <b>{sent}</b> из <b>{len(users)}</b>"
    )
    await state.clear()

@router.callback_query(F.data == "admin_balance")
async def admin_balance(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        f"{em('', EMOJI['wallet'])} <b>Введите ID пользователя:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{em('', EMOJI['cross'])} Отмена",
                callback_data="admin_back"
            )]
        ])
    )
    await state.set_state(AdminStates.waiting_balance_user)
    await callback.answer()

@router.message(AdminStates.waiting_balance_user)
async def balance_user_input(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
        await state.update_data(balance_user_id=user_id)

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT balance FROM users WHERE id = %s", (AsIs(str(user_id)),))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user:
            await message.answer(f"{em('', EMOJI['cross'])} Пользователь не найден")
            await state.clear()
            return

        await message.answer(
            f"{em('', EMOJI['wallet'])} Баланс пользователя: <b>{user[0]} RUB</b>\n\n"
            f"Введите сумму для изменения (+100 или -50):"
        )
        await state.set_state(AdminStates.waiting_balance_amount)
    except ValueError:
        await message.answer(f"{em('', EMOJI['cross'])} Введите корректный ID")

@router.message(AdminStates.waiting_balance_amount)
async def balance_amount_input(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        data = await state.get_data()
        user_id = data['balance_user_id']

        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE id = %s",
            (amount, AsIs(str(user_id)))
        )
        cur.execute("SELECT balance FROM users WHERE id = %s", (AsIs(str(user_id)),))
        new_balance = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()

        await message.answer(
            f"{em('', EMOJI['check'])} Баланс обновлен!\n"
            f"Новый баланс: <b>{new_balance} RUB</b>"
        )
        await state.clear()
    except ValueError:
        await message.answer(f"{em('', EMOJI['cross'])} Введите корректную сумму")

@router.callback_query(F.data == "admin_prices")
async def admin_prices(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    buttons = []
    for name, code, flag in COUNTRIES:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT buy_price FROM price_settings WHERE country = %s", (code,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        price = row[0] if row else 100.0
        buttons.append([InlineKeyboardButton(
            text=f"{flag} {name} - {price} RUB",
            callback_data=f"set_price_{code}"
        )])

    buttons.append([InlineKeyboardButton(
        text=f"{em('', EMOJI['back'])} Назад",
        callback_data="admin_back"
    )])

    await callback.message.edit_text(
        f"{em('', EMOJI['edit'])} <b>Выберите страну для изменения цены:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("set_price_"))
async def set_price_country(callback: CallbackQuery, state: FSMContext):
    country = callback.data.replace("set_price_", "")
    await state.update_data(price_country=country)
    await state.set_state(AdminStates.waiting_price_amount)

    await callback.message.edit_text(
        f"{em('', EMOJI['edit'])} <b>Введите новую цену в RUB:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{em('', EMOJI['cross'])} Отмена",
                callback_data="admin_back"
            )]
        ])
    )
    await callback.answer()

@router.message(AdminStates.waiting_price_amount)
async def price_amount_input(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        data = await state.get_data()
        country = data['price_country']

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO price_settings (country, buy_price)
            VALUES (%s, %s)
            ON CONFLICT (country) DO UPDATE SET buy_price = %s
        """, (country, amount, amount))
        conn.commit()
        cur.close()
        conn.close()

        await message.answer(
            f"{em('', EMOJI['check'])} Цена обновлена! Страна: <b>{country}</b>, цена: <b>{amount} RUB</b>"
        )
        await state.clear()
    except ValueError:
        await message.answer(f"{em('', EMOJI['cross'])} Введите корректную сумму")

@router.callback_query(F.data == "admin_media")
async def admin_media(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет доступа", show_alert=True)
        return

    await callback.message.edit_text(
        f"{em('', EMOJI['media'])} <b>Отправьте фото или видео</b>\n\n"
        f"Секции: main, profile, purchases\n"
        f"Отправьте медиа с подписью в формате: секция | подпись",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{em('', EMOJI['cross'])} Отмена",
                callback_data="admin_back"
            )]
        ])
    )
    await state.set_state(AdminStates.waiting_media)
    await callback.answer()

@router.message(AdminStates.waiting_media)
async def media_input(message: Message, state: FSMContext):
    caption = message.caption or ""
    section = "main"

    if "|" in caption:
        parts = caption.split("|", 1)
        section = parts[0].strip()
        caption = parts[1].strip() if len(parts) > 1 else ""

    file_id = None
    file_type = None

    if message.photo:
        file_id = message.photo[-1].file_id
        file_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        file_type = "video"

    if file_id:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO media_settings (section, file_id, file_type, caption)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (section) DO UPDATE SET file_id = %s, file_type = %s, caption = %s
        """, (section, file_id, file_type, caption, file_id, file_type, caption))
        conn.commit()
        cur.close()
        conn.close()

        await message.answer(f"{em('', EMOJI['check'])} Медиа сохранено для секции: <b>{section}</b>")
    else:
        await message.answer(f"{em('', EMOJI['cross'])} Отправьте фото или видео")

    await state.clear()

# ============ MAIN ============
async def main():
    init_db()
    logger.info("Bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
