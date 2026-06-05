import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

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
    BotCommand, BotCommandScopeDefault
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
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ============ PREMIUM EMOJI IDS ============
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
    "party": "6041731551845159060",
    "info": "6028435952299413210",
    "calendar": "5890937706803894250",
    "people": "5870772616305839506",
    "code": "5940433880585605708",
    "broadcast_icon": "5370599459661045441",
    "gift": "6032644646587338669",
    "clock": "5983150113483134607",
}

def em(text, eid):
    return f'<tg-emoji emoji-id="{eid}">{text}</tg-emoji>'

# ============ DATABASE HELPERS ============
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
            total_purchases INTEGER DEFAULT 0,
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
            account_id INTEGER REFERENCES accounts(id),
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
            account_id INTEGER REFERENCES accounts(id),
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def db_execute(query, params=None):
    """Execute query with BIGINT cast for all %s placeholders that are integers"""
    conn = get_conn()
    cur = conn.cursor()
    if params:
        new_params = []
        for p in params:
            if isinstance(p, int):
                new_params.append(AsIs(str(p)))
            else:
                new_params.append(p)
        cur.execute(query, tuple(new_params))
    else:
        cur.execute(query)
    conn.commit()
    return cur, conn

def db_fetchone(query, params=None):
    cur, conn = db_execute(query, params)
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def db_fetchall(query, params=None):
    cur, conn = db_execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def ensure_user(user_id: int, username: str = None):
    existing = db_fetchone("SELECT id FROM users WHERE id = %s", (user_id,))
    if not existing:
        db_execute("INSERT INTO users (id, username) VALUES (%s, %s)", (user_id, username))

# ============ BOT INIT ============
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ============ COUNTRIES (45 стран) ============
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

# ============ FSM STATES ============
class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_balance_user = State()
    waiting_balance_amount = State()
    waiting_price_amount = State()
    waiting_media = State()

# ============ KEYBOARDS ============
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Купить аккаунт")],
            [KeyboardButton(text="Мои покупки")],
            [KeyboardButton(text="Профиль")]
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

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            text="Назад",
            callback_data=f"countries_page_{page-1}",
            icon_custom_emoji_id=EMOJI["back"]
        ))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(
            text="Вперед",
            callback_data=f"countries_page_{page+1}",
            icon_custom_emoji_id=EMOJI["back"]
        ))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(
        text="Главное меню",
        callback_data="main_menu",
        icon_custom_emoji_id=EMOJI["home"]
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_payment_keyboard(account_id: int, price: float):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Telegram Stars ({int(price)} ⭐)",
            callback_data=f"pay_stars_{account_id}",
            icon_custom_emoji_id=EMOJI["stars"]
        )],
        [InlineKeyboardButton(
            text=f"Crypto Bot ({price} RUB)",
            callback_data=f"pay_crypto_{account_id}",
            icon_custom_emoji_id=EMOJI["crypto"]
        )],
        [InlineKeyboardButton(
            text=f"Баланс ({price} RUB)",
            callback_data=f"pay_balance_{account_id}",
            icon_custom_emoji_id=EMOJI["wallet"]
        )],
        [InlineKeyboardButton(
            text="Отмена",
            callback_data="cancel_payment",
            icon_custom_emoji_id=EMOJI["cross"]
        )]
    ])

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats", icon_custom_emoji_id=EMOJI["stats"])],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast", icon_custom_emoji_id=EMOJI["broadcast"])],
        [InlineKeyboardButton(text="Изменить баланс", callback_data="admin_balance", icon_custom_emoji_id=EMOJI["wallet"])],
        [InlineKeyboardButton(text="Изменить цены", callback_data="admin_prices", icon_custom_emoji_id=EMOJI["edit"])],
        [InlineKeyboardButton(text="Загрузить медиа", callback_data="admin_media", icon_custom_emoji_id=EMOJI["media"])],
        [InlineKeyboardButton(text="Закрыть", callback_data="main_menu", icon_custom_emoji_id=EMOJI["cross"])]
    ])

# ============ TELETHON ============
async def check_session_valid(session_string: str) -> bool:
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        valid = await client.is_user_authorized()
        await client.disconnect()
        return valid
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
        tg_chat = None
        async for d in client.iter_dialogs():
            if d.name == "Telegram" and d.is_user:
                tg_chat = d
                break
        if not tg_chat:
            await client.disconnect()
            return None
        msgs = await client.get_messages(tg_chat, limit=5)
        await client.disconnect()
        for m in msgs:
            if m.text:
                match = re.search(r'\b\d{5}\b', m.text)
                if match:
                    return match.group(0)
        return None
    except Exception as e:
        logger.error(f"Get code error: {e}")
        return None

# ============ CRYPTO BOT API ============
async def create_crypto_invoice(amount: float, currency: str = "RUB") -> dict | None:
    try:
        async with aiohttp.ClientSession() as s:
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            params = {"asset": currency, "amount": str(amount)}
            async with s.get("https://pay.crypt.bot/api/createInvoice", headers=headers, params=params) as resp:
                data = await resp.json()
                return data["result"] if data.get("ok") else None
    except Exception as e:
        logger.error(f"Crypto create invoice error: {e}")
        return None

async def check_crypto_invoice(invoice_id: int) -> str:
    try:
        async with aiohttp.ClientSession() as s:
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            params = {"invoice_id": invoice_id}
            async with s.get("https://pay.crypt.bot/api/getInvoice", headers=headers, params=params) as resp:
                data = await resp.json()
                return data["result"]["status"] if data.get("ok") else "error"
    except Exception as e:
        logger.error(f"Crypto check error: {e}")
        return "error"

# ============ ACCOUNT LOGIC ============
async def find_and_validate_account(country_code: str) -> dict | None:
    rows = db_fetchall("""
        SELECT id, phone, country, session_string, password_2fa, buy_price
        FROM accounts
        WHERE country = %s AND is_sold = FALSE AND is_valid = TRUE
        AND (is_reserved = FALSE OR reserved_until < NOW())
        LIMIT 10
    """, (country_code,))

    for acc in rows:
        aid, phone, country, ss, pwd, price = acc
        if await check_session_valid(ss):
            db_execute(
                "UPDATE accounts SET is_reserved = TRUE, reserved_until = %s WHERE id = %s",
                (datetime.now() + timedelta(minutes=5), aid)
            )
            return {
                "id": aid, "phone": phone, "country": country,
                "session_string": ss, "password_2fa": pwd, "buy_price": float(price)
            }
        else:
            db_execute("UPDATE accounts SET is_valid = FALSE WHERE id = %s", (aid,))
    return None

async def reserve_timeout(account_id: int, delay: int = 300):
    await asyncio.sleep(delay)
    db_execute(
        "UPDATE accounts SET is_reserved = FALSE, reserved_until = NULL, reserved_by = NULL "
        "WHERE id = %s AND is_sold = FALSE AND is_reserved = TRUE",
        (account_id,)
    )

def complete_purchase(user_id: int, account_id: int, method: str):
    db_execute(
        "UPDATE accounts SET is_sold = TRUE, is_reserved = FALSE, sold_to = %s WHERE id = %s",
        (user_id, account_id)
    )
    db_execute(
        "INSERT INTO purchases (user_id, account_id) VALUES (%s, %s)",
        (user_id, account_id)
    )
    db_execute(
        "UPDATE users SET total_purchases = total_purchases + 1 WHERE id = %s",
        (user_id,)
    )

# ============ COMMAND HANDLERS ============
@router.message(Command("start"))
async def cmd_start(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"{em('🎉', EMOJI['party'])} Добро пожаловать в <b>Vest Market</b>!\n\n"
        f"{em('📦', EMOJI['box'])} Здесь вы можете купить Telegram аккаунты\n"
        f"{em('ℹ️', EMOJI['info'])} Выберите действие в меню:",
        reply_markup=get_main_menu()
    )

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(f"{em('❌', EMOJI['cross'])} У вас нет доступа к админ-панели")
        return
    await message.answer(
        f"{em('⚙️', EMOJI['settings'])} <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )

@router.message(F.text == "Купить аккаунт")
async def handle_buy(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"{em('📦', EMOJI['box'])} <b>Выберите страну:</b>",
        reply_markup=get_countries_keyboard(0)
    )

@router.message(F.text == "Мои покупки")
async def handle_purchases(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    await show_purchases(message, message.from_user.id)

@router.message(F.text == "Профиль")
async def handle_profile(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    user = db_fetchone(
        "SELECT balance, total_purchases, created_at FROM users WHERE id = %s",
        (message.from_user.id,)
    )
    if user:
        balance, total, created = user
        created_str = created.strftime('%d.%m.%Y') if created else '—'
        await message.answer(
            f"{em('👤', EMOJI['profile'])} <b>Профиль</b>\n\n"
            f"{em('👛', EMOJI['wallet'])} Баланс: <b>{balance} RUB</b>\n"
            f"{em('📦', EMOJI['box'])} Куплено аккаунтов: <b>{total}</b>\n"
            f"{em('📅', EMOJI['calendar'])} Дата регистрации: <b>{created_str}</b>"
        )

async def show_purchases(event, user_id: int):
    purchases = db_fetchall("""
        SELECT p.id, a.phone, a.country, p.purchase_date, a.password_2fa, p.code_obtained, a.id
        FROM purchases p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.user_id = %s
        ORDER BY p.purchase_date DESC
    """, (user_id,))

    if not purchases:
        text = f"{em('ℹ️', EMOJI['info'])} У вас пока нет покупок"
        if hasattr(event, 'answer'):
            await event.answer(text)
        else:
            await event.message.edit_text(text)
        return

    buttons = []
    for p in purchases:
        pid, phone, country, date, pwd, code_obt, aid = p
        lock_emoji = EMOJI["lock"] if pwd else EMOJI["unlock"]
        code_prefix = f"{em('✅', EMOJI['check'])} " if code_obt else ""
        buttons.append([InlineKeyboardButton(
            text=f"{code_prefix}{phone} | {country}",
            callback_data=f"purchase_detail_{pid}",
            icon_custom_emoji_id=lock_emoji
        )])

    buttons.append([InlineKeyboardButton(
        text="Главное меню",
        callback_data="main_menu",
        icon_custom_emoji_id=EMOJI["home"]
    )])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    text = f"{em('📁', EMOJI['folder'])} <b>Мои покупки</b>\n\nВыберите аккаунт:"

    if hasattr(event, 'answer'):
        await event.answer(text, reply_markup=kb)
    else:
        await event.message.edit_text(text, reply_markup=kb)

# ============ CALLBACK HANDLERS ============
@router.callback_query(F.data.startswith("countries_page_"))
async def cb_countries_page(callback: CallbackQuery):
    page = int(callback.data.split("_")[-1])
    await callback.message.edit_text(
        f"{em('📦', EMOJI['box'])} <b>Выберите страну:</b>",
        reply_markup=get_countries_keyboard(page)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("country_"))
async def cb_country_selected(callback: CallbackQuery):
    country_code = callback.data.replace("country_", "")

    country_display = country_code
    for name, code, flag in COUNTRIES:
        if code == country_code:
            country_display = f"{flag} {name}"
            break

    await callback.message.edit_text(f"{em('🔄', EMOJI['loading'])} Ищу аккаунт...")
    await callback.answer()

    account = await find_and_validate_account(country_code)

    if not account:
        await callback.message.edit_text(
            f"{em('❌', EMOJI['cross'])} К сожалению, свободных аккаунтов для {country_display} нет.\n"
            f"Попробуйте другую страну или зайдите позже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="К выбору стран",
                    callback_data="countries_page_0",
                    icon_custom_emoji_id=EMOJI["back"]
                )]
            ])
        )
        return

    asyncio.create_task(reserve_timeout(account['id']))

    price = account['buy_price']
    await callback.message.edit_text(
        f"{em('✅', EMOJI['check'])} <b>Аккаунт найден!</b>\n\n"
        f"{em('ℹ️', EMOJI['info'])} Страна: <b>{country_display}</b>\n"
        f"{em('👛', EMOJI['wallet'])} Цена: <b>{price} RUB</b>\n\n"
        f"Выберите способ оплаты:",
        reply_markup=get_payment_keyboard(account['id'], price)
    )

@router.callback_query(F.data.startswith("pay_stars_"))
async def cb_pay_stars(callback: CallbackQuery):
    account_id = int(callback.data.replace("pay_stars_", ""))
    acc = db_fetchone("SELECT buy_price FROM accounts WHERE id = %s", (account_id,))
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    price = int(float(acc[0]))
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Покупка Telegram аккаунта",
        description="Аккаунт Telegram | Vest Market",
        payload=f"stars_{account_id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Аккаунт Telegram", amount=price)],
    )
    await callback.message.delete()
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout: PreCheckoutQuery):
    await pre_checkout.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("stars_"):
        account_id = int(payload.replace("stars_", ""))
        complete_purchase(message.from_user.id, account_id, "stars")
        await send_account_info(message, account_id)

@router.callback_query(F.data.startswith("pay_crypto_"))
async def cb_pay_crypto(callback: CallbackQuery):
    account_id = int(callback.data.replace("pay_crypto_", ""))
    acc = db_fetchone("SELECT buy_price FROM accounts WHERE id = %s", (account_id,))
    if not acc:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    price = float(acc[0])
    invoice = await create_crypto_invoice(price, "RUB")
    if not invoice:
        await callback.answer("Ошибка создания счета", show_alert=True)
        return

    db_execute(
        "INSERT INTO crypto_payments (user_id, invoice_id, amount, currency, account_id) VALUES (%s, %s, %s, %s, %s)",
        (callback.from_user.id, str(invoice["invoice_id"]), price, "RUB", account_id)
    )

    pay_url = invoice.get('pay_url', invoice.get('bot_invoice_url', ''))
    await callback.message.edit_text(
        f"{em('👾', EMOJI['crypto'])} <b>Счет создан!</b>\n\n"
        f"Сумма: <b>{price} RUB</b>\n"
        f"Ссылка: {pay_url}\n\n"
        f"После оплаты нажмите кнопку проверки:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Проверить оплату",
                callback_data=f"check_crypto_{invoice['invoice_id']}_{account_id}",
                icon_custom_emoji_id=EMOJI["loading"]
            )],
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="cancel_payment",
                icon_custom_emoji_id=EMOJI["cross"]
            )]
        ])
    )
    await callback.answer()

@router.callback_query(F.data.startswith("check_crypto_"))
async def cb_check_crypto(callback: CallbackQuery):
    parts = callback.data.split("_")
    invoice_id = parts[2]
    account_id = int(parts[3])

    status = await check_crypto_invoice(int(invoice_id))

    if status == "paid":
        db_execute("UPDATE crypto_payments SET status = 'paid' WHERE invoice_id = %s", (invoice_id,))
        complete_purchase(callback.from_user.id, account_id, "crypto")
        await callback.message.delete()
        await send_account_info(callback.message, account_id)
    elif status == "active":
        await callback.answer("Счет еще не оплачен", show_alert=True)
    else:
        await callback.answer("Ошибка проверки или счет отменен", show_alert=True)

@router.callback_query(F.data.startswith("pay_balance_"))
async def cb_pay_balance(callback: CallbackQuery):
    account_id = int(callback.data.replace("pay_balance_", ""))
    user_id = callback.from_user.id

    acc = db_fetchone("SELECT buy_price FROM accounts WHERE id = %s", (account_id,))
    user = db_fetchone("SELECT balance FROM users WHERE id = %s", (user_id,))

    if not acc or not user:
        await callback.answer("Ошибка", show_alert=True)
        return

    price = float(acc[0])
    balance = float(user[0])

    if balance < price:
        await callback.answer(f"Недостаточно средств! Баланс: {balance} RUB", show_alert=True)
        return

    db_execute("UPDATE users SET balance = balance - %s WHERE id = %s", (price, user_id))
    complete_purchase(user_id, account_id, "balance")
    await callback.message.delete()
    await send_account_info(callback.message, account_id)

@router.callback_query(F.data == "cancel_payment")
async def cb_cancel_payment(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        f"{em('❌', EMOJI['cross'])} Покупка отменена",
        reply_markup=get_main_menu()
    )
    await callback.answer()

async def send_account_info(event, account_id: int):
    acc = db_fetchone(
        "SELECT phone, password_2fa, country FROM accounts WHERE id = %s",
        (account_id,)
    )
    if not acc:
        return

    phone, pwd, country = acc
    pwd_text = pwd if pwd else "Отсутствует"

    text = (
        f"{em('🎉', EMOJI['party'])} <b>Покупка успешна!</b>\n\n"
        f"{em('ℹ️', EMOJI['info'])} Номер: <code>{phone}</code>\n"
        f"{em('🔒', EMOJI['lock'])} 2FA пароль: <code>{pwd_text}</code>\n\n"
        f"Нажмите кнопку ниже чтобы получить код авторизации:"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="Получить код",
            callback_data=f"get_code_{account_id}",
            icon_custom_emoji_id=EMOJI["code"]
        )],
        [InlineKeyboardButton(
            text="Главное меню",
            callback_data="main_menu",
            icon_custom_emoji_id=EMOJI["home"]
        )]
    ])

    if hasattr(event, 'answer'):
        await event.answer(text, reply_markup=kb)
    else:
        await bot.send_message(event.chat.id, text, reply_markup=kb)

@router.callback_query(F.data.startswith("get_code_"))
async def cb_get_code(callback: CallbackQuery):
    account_id = int(callback.data.replace("get_code_", ""))
    user_id = callback.from_user.id

    result = db_fetchone("""
        SELECT a.session_string, a.password_2fa, p.code_obtained, p.id
        FROM accounts a
        JOIN purchases p ON a.id = p.account_id
        WHERE a.id = %s AND p.user_id = %s
    """, (account_id, user_id))

    if not result:
        await callback.answer("Аккаунт не найден", show_alert=True)
        return

    session_string, pwd, code_obtained, purchase_id = result

    if code_obtained:
        await callback.answer(f"{em('ℹ️', EMOJI['info'])} Код уже был получен ранее", show_alert=True)
        return

    await callback.message.edit_text(f"{em('🔄', EMOJI['loading'])} Получаю код авторизации...")

    code = await get_login_code(session_string, pwd)

    if code:
        db_execute("UPDATE purchases SET code_obtained = TRUE WHERE id = %s", (purchase_id,))
        await callback.message.edit_text(
            f"{em('✅', EMOJI['check'])} <b>Код авторизации:</b>\n\n"
            f"<code>{code}</code>\n\n"
            f"{em('ℹ️', EMOJI['info'])} Код можно получить только один раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="main_menu",
                    icon_custom_emoji_id=EMOJI["home"]
                )]
            ])
        )
    else:
        await callback.message.edit_text(
            f"{em('❌', EMOJI['cross'])} Не удалось получить код. Возможно сообщение еще не пришло.\n"
            f"Попробуйте позже в разделе {em('📁', EMOJI['folder'])} Мои покупки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="main_menu",
                    icon_custom_emoji_id=EMOJI["home"]
                )]
            ])
        )

@router.callback_query(F.data == "my_purchases")
async def cb_my_purchases(callback: CallbackQuery):
    await show_purchases(callback, callback.from_user.id)

@router.callback_query(F.data.startswith("purchase_detail_"))
async def cb_purchase_detail(callback: CallbackQuery):
    purchase_id = int(callback.data.replace("purchase_detail_", ""))

    result = db_fetchone("""
        SELECT a.phone, a.country, a.password_2fa, p.purchase_date, p.code_obtained, a.id
        FROM purchases p
        JOIN accounts a ON p.account_id = a.id
        WHERE p.id = %s
    """, (purchase_id,))

    if not result:
        await callback.answer("Покупка не найдена", show_alert=True)
        return

    phone, country, pwd, date, code_obtained, account_id = result
    pwd_text = pwd if pwd else "Отсутствует"
    code_status = f"{em('✅', EMOJI['check'])} Получен" if code_obtained else f"{em('❌', EMOJI['cross'])} Не получен"

    text = (
        f"{em('ℹ️', EMOJI['info'])} <b>Детали аккаунта</b>\n\n"
        f"{em('ℹ️', EMOJI['info'])} Номер: <code>{phone}</code>\n"
        f"{em('ℹ️', EMOJI['info'])} Страна: {country}\n"
        f"{em('🔒', EMOJI['lock'])} 2FA: <code>{pwd_text}</code>\n"
        f"{em('📅', EMOJI['calendar'])} Куплен: {date.strftime('%d.%m.%Y %H:%M') if date else '—'}\n"
        f"{em('🔨', EMOJI['code'])} Код: {code_status}"
    )

    buttons = []
    if not code_obtained:
        buttons.append([InlineKeyboardButton(
            text="Получить код",
            callback_data=f"get_code_{account_id}",
            icon_custom_emoji_id=EMOJI["code"]
        )])
    buttons.append([InlineKeyboardButton(
        text="Назад к покупкам",
        callback_data="my_purchases",
        icon_custom_emoji_id=EMOJI["back"]
    )])

    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        f"{em('🏘', EMOJI['home'])} <b>Главное меню</b>\n\nВыберите действие:",
        reply_markup=get_main_menu()
    )
    await callback.answer()

# ============ ADMIN CALLBACKS ============
@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)

    total_users = db_fetchone("SELECT COUNT(*) FROM users")[0]
    total_accounts = db_fetchone("SELECT COUNT(*) FROM accounts")[0]
    sold = db_fetchone("SELECT COUNT(*) FROM accounts WHERE is_sold = TRUE")[0]
    available = db_fetchone("SELECT COUNT(*) FROM accounts WHERE is_sold = FALSE AND is_valid = TRUE")[0]

    await callback.message.edit_text(
        f"{em('📊', EMOJI['stats'])} <b>Статистика</b>\n\n"
        f"{em('👥', EMOJI['people'])} Пользователей: <b>{total_users}</b>\n"
        f"{em('📦', EMOJI['box'])} Всего аккаунтов: <b>{total_accounts}</b>\n"
        f"{em('✅', EMOJI['check'])} Продано: <b>{sold}</b>\n"
        f"{em('ℹ️', EMOJI['info'])} Доступно: <b>{available}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Назад",
                callback_data="admin_back",
                icon_custom_emoji_id=EMOJI["back"]
            )]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def cb_admin_back(callback: CallbackQuery):
    await callback.message.edit_text(
        f"{em('⚙️', EMOJI['settings'])} <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)

    await callback.message.edit_text(
        f"{em('📣', EMOJI['broadcast_icon'])} <b>Отправьте сообщение для рассылки</b>\n\n"
        f"Можно отправить текст, фото или видео с подписью.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="admin_back",
                icon_custom_emoji_id=EMOJI["cross"]
            )]
        ])
    )
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.answer()

@router.message(AdminStates.waiting_broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return

    users = db_fetchall("SELECT id FROM users")
    sent = 0
    for u in users:
        try:
            if message.photo:
                await bot.send_photo(u[0], message.photo[-1].file_id, caption=message.caption or "")
            elif message.video:
                await bot.send_video(u[0], message.video.file_id, caption=message.caption or "")
            else:
                await bot.send_message(u[0], message.text or message.caption or "")
            sent += 1
        except Exception as e:
            logger.error(f"Broadcast error to {u[0]}: {e}")
        await asyncio.sleep(0.05)

    await message.answer(
        f"{em('✅', EMOJI['check'])} Рассылка завершена!\n"
        f"Отправлено: <b>{sent}</b> из <b>{len(users)}</b>"
    )
    await state.clear()

@router.callback_query(F.data == "admin_balance")
async def cb_admin_balance(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)

    await callback.message.edit_text(
        f"{em('👛', EMOJI['wallet'])} <b>Введите ID пользователя:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="admin_back",
                icon_custom_emoji_id=EMOJI["cross"]
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

        user = db_fetchone("SELECT balance FROM users WHERE id = %s", (user_id,))

        if not user:
            await message.answer(f"{em('❌', EMOJI['cross'])} Пользователь не найден")
            await state.clear()
            return

        await message.answer(
            f"{em('👛', EMOJI['wallet'])} Баланс пользователя: <b>{user[0]} RUB</b>\n\n"
            f"Введите сумму для изменения (+100 или -50):"
        )
        await state.set_state(AdminStates.waiting_balance_amount)
    except ValueError:
        await message.answer(f"{em('❌', EMOJI['cross'])} Введите корректный ID")

@router.message(AdminStates.waiting_balance_amount)
async def balance_amount_input(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        data = await state.get_data()
        user_id = data['balance_user_id']

        db_execute("UPDATE users SET balance = balance + %s WHERE id = %s", (amount, user_id))
        new_balance = db_fetchone("SELECT balance FROM users WHERE id = %s", (user_id,))[0]

        await message.answer(
            f"{em('✅', EMOJI['check'])} Баланс обновлен!\n"
            f"Новый баланс: <b>{new_balance} RUB</b>"
        )
        await state.clear()
    except ValueError:
        await message.answer(f"{em('❌', EMOJI['cross'])} Введите корректную сумму")

@router.callback_query(F.data == "admin_prices")
async def cb_admin_prices(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)

    buttons = []
    for name, code, flag in COUNTRIES:
        row = db_fetchone("SELECT buy_price FROM price_settings WHERE country = %s", (code,))
        price = row[0] if row else 100.0
        buttons.append([InlineKeyboardButton(
            text=f"{flag} {name} - {price} RUB",
            callback_data=f"set_price_{code}"
        )])

    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data="admin_back",
        icon_custom_emoji_id=EMOJI["back"]
    )])

    await callback.message.edit_text(
        f"{em('🖋', EMOJI['edit'])} <b>Выберите страну для изменения цены:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("set_price_"))
async def cb_set_price(callback: CallbackQuery, state: FSMContext):
    country = callback.data.replace("set_price_", "")
    await state.update_data(price_country=country)
    await state.set_state(AdminStates.waiting_price_amount)

    await callback.message.edit_text(
        f"{em('🖋', EMOJI['edit'])} <b>Введите новую цену в RUB:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="admin_back",
                icon_custom_emoji_id=EMOJI["cross"]
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

        db_execute(
            "INSERT INTO price_settings (country, buy_price) VALUES (%s, %s) "
            "ON CONFLICT (country) DO UPDATE SET buy_price = %s",
            (country, amount, amount)
        )

        await message.answer(
            f"{em('✅', EMOJI['check'])} Цена обновлена! Страна: <b>{country}</b>, цена: <b>{amount} RUB</b>"
        )
        await state.clear()
    except ValueError:
        await message.answer(f"{em('❌', EMOJI['cross'])} Введите корректную сумму")

@router.callback_query(F.data == "admin_media")
async def cb_admin_media(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)

    await callback.message.edit_text(
        f"{em('🖼', EMOJI['media'])} <b>Отправьте фото или видео</b>\n\n"
        f"Секции: main, profile, purchases\n"
        f"Отправьте медиа с подписью в формате: секция | подпись",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="Отмена",
                callback_data="admin_back",
                icon_custom_emoji_id=EMOJI["cross"]
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
        db_execute(
            "INSERT INTO media_settings (section, file_id, file_type, caption) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT (section) DO UPDATE SET file_id = %s, file_type = %s, caption = %s",
            (section, file_id, file_type, caption, file_id, file_type, caption)
        )
        await message.answer(f"{em('✅', EMOJI['check'])} Медиа сохранено для секции: <b>{section}</b>")
    else:
        await message.answer(f"{em('❌', EMOJI['cross'])} Отправьте фото или видео")

    await state.clear()

# ============ MAIN ============
async def main():
    init_db()
    logger.info("Vest Market bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
