import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

import psycopg2
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
E = {
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
    "money": "5904462880941545555",
}

def em(text, eid):
    return f'<tg-emoji emoji-id="{eid}">{text}</tg-emoji>'

# ============ DATABASE ============
def get_conn():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
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
            reserved_by INTEGER,
            sold_to INTEGER,
            buy_price DECIMAL DEFAULT 100.0,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
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
            user_id INTEGER,
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

def ensure_user(user_id: int, username: str = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO users (id, username) VALUES (%s, %s)",
            (user_id, username)
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
            icon_custom_emoji_id=E["back"]
        ))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(
            text="Вперед",
            callback_data=f"countries_page_{page+1}",
            icon_custom_emoji_id=E["back"]
        ))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(
        text="Главное меню",
        callback_data="main_menu",
        icon_custom_emoji_id=E["home"]
    )])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_payment_keyboard(account_id: int, price: float):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"Telegram Stars ({int(price)} ⭐)",
            callback_data=f"pay_stars_{account_id}",
            icon_custom_emoji_id=E["stars"]
        )],
        [InlineKeyboardButton(
            text=f"Crypto Bot ({price} RUB)",
            callback_data=f"pay_crypto_{account_id}",
            icon_custom_emoji_id=E["crypto"]
        )],
        [InlineKeyboardButton(
            text=f"Баланс ({price} RUB)",
            callback_data=f"pay_balance_{account_id}",
            icon_custom_emoji_id=E["wallet"]
        )],
        [InlineKeyboardButton(
            text="Отмена",
            callback_data="cancel_payment",
            icon_custom_emoji_id=E["cross"]
        )]
    ])

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Статистика", callback_data="admin_stats", icon_custom_emoji_id=E["stats"])],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin_broadcast", icon_custom_emoji_id=E["broadcast"])],
        [InlineKeyboardButton(text="Изменить баланс", callback_data="admin_balance", icon_custom_emoji_id=E["wallet"])],
        [InlineKeyboardButton(text="Изменить цены", callback_data="admin_prices", icon_custom_emoji_id=E["edit"])],
        [InlineKeyboardButton(text="Загрузить медиа", callback_data="admin_media", icon_custom_emoji_id=E["media"])],
        [InlineKeyboardButton(text="Закрыть", callback_data="main_menu", icon_custom_emoji_id=E["cross"])]
    ])

# ============ TELETHON ============
async def check_session_valid(session_string: str) -> bool:
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.connect()
        valid = await client.is_user_authorized()
        await client.disconnect()
        return valid
    except:
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
    except:
        return None

# ============ CRYPTO ============
async def create_crypto_invoice(amount: float, currency: str = "RUB") -> dict | None:
    try:
        async with aiohttp.ClientSession() as s:
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            params = {"asset": currency, "amount": str(amount)}
            async with s.get("https://pay.crypt.bot/api/createInvoice", headers=headers, params=params) as resp:
                data = await resp.json()
                return data["result"] if data.get("ok") else None
    except:
        return None

async def check_crypto_invoice(invoice_id: int) -> str:
    try:
        async with aiohttp.ClientSession() as s:
            headers = {"Crypto-Pay-API-Token": CRYPTO_BOT_TOKEN}
            params = {"invoice_id": invoice_id}
            async with s.get("https://pay.crypt.bot/api/getInvoice", headers=headers, params=params) as resp:
                data = await resp.json()
                return data["result"]["status"] if data.get("ok") else "error"
    except:
        return "error"

# ============ ACCOUNT LOGIC ============
async def find_and_validate_account(country_code: str) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, phone, country, session_string, password_2fa, buy_price
        FROM accounts
        WHERE country = %s AND is_sold = FALSE AND is_valid = TRUE
        AND (is_reserved = FALSE OR reserved_until < NOW())
        LIMIT 10
    """, (country_code,))
    accounts = cur.fetchall()
    for acc in accounts:
        aid, phone, country, ss, pwd, price = acc
        if await check_session_valid(ss):
            cur.execute("UPDATE accounts SET is_reserved = TRUE, reserved_until = %s WHERE id = %s",
                        (datetime.now() + timedelta(minutes=5), aid))
            conn.commit()
            cur.close()
            conn.close()
            return {"id": aid, "phone": phone, "country": country, "session_string": ss, "password_2fa": pwd, "buy_price": float(price)}
        else:
            cur.execute("UPDATE accounts SET is_valid = FALSE WHERE id = %s", (aid,))
            conn.commit()
    cur.close()
    conn.close()
    return None

async def reserve_timeout(account_id: int, delay: int = 300):
    await asyncio.sleep(delay)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET is_reserved = FALSE, reserved_until = NULL, reserved_by = NULL WHERE id = %s AND is_sold = FALSE AND is_reserved = TRUE", (account_id,))
    conn.commit()
    cur.close()
    conn.close()

def complete_purchase(user_id: int, account_id: int, method: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE accounts SET is_sold = TRUE, is_reserved = FALSE, sold_to = %s WHERE id = %s", (user_id, account_id))
    cur.execute("INSERT INTO purchases (user_id, account_id) VALUES (%s, %s)", (user_id, account_id))
    cur.execute("UPDATE users SET total_purchases = total_purchases + 1 WHERE id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()

# ============ HANDLERS ============
@router.message(Command("start"))
async def start(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"{em('🎉', E['party'])} Добро пожаловать в <b>Vest Market</b>!\n\n"
        f"{em('📦', E['box'])} Здесь вы можете купить Telegram аккаунты\n"
        f"{em('ℹ️', E['info'])} Выберите действие в меню:",
        reply_markup=get_main_menu()
    )

@router.message(Command("admin"))
async def admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer(f"{em('❌', E['cross'])} Нет доступа")
        return
    await message.answer(
        f"{em('⚙️', E['settings'])} <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )

@router.message(F.text == "Купить аккаунт")
async def buy(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"{em('📦', E['box'])} <b>Выберите страну:</b>",
        reply_markup=get_countries_keyboard(0)
    )

@router.message(F.text == "Мои покупки")
async def purchases(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    await show_purchases(message)

@router.message(F.text == "Профиль")
async def profile(message: Message):
    ensure_user(message.from_user.id, message.from_user.username)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT balance, total_purchases, created_at FROM users WHERE id = %s", (message.from_user.id,))
    u = cur.fetchone()
    conn.close()
    if u:
        bal, tot, cr = u
        await message.answer(
            f"{em('👤', E['profile'])} <b>Профиль</b>\n\n"
            f"{em('👛', E['wallet'])} Баланс: <b>{bal} RUB</b>\n"
            f"{em('📦', E['box'])} Куплено: <b>{tot}</b>\n"
            f"{em('📅', E['calendar'])} Регистрация: <b>{cr.strftime('%d.%m.%Y') if cr else '—'}</b>"
        )

async def show_purchases(msg_or_cb, uid=None):
    if uid is None:
        uid = msg_or_cb.from_user.id
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT p.id, a.phone, a.country, p.purchase_date, a.password_2fa, p.code_obtained, a.id
        FROM purchases p JOIN accounts a ON p.account_id = a.id
        WHERE p.user_id = %s ORDER BY p.purchase_date DESC
    """, (uid,))
    rows = cur.fetchall()
    conn.close()

    if not rows:
        txt = f"{em('ℹ️', E['info'])} У вас пока нет покупок"
        if hasattr(msg_or_cb, 'answer'):
            await msg_or_cb.answer(txt)
        else:
            await msg_or_cb.message.edit_text(txt)
        return

    btns = []
    for r in rows:
        pid, phone, country, dt, pwd, cod, aid = r
        lock = E["lock"] if pwd else E["unlock"]
        cs = f"{em('✅', E['check'])} " if cod else ""
        btns.append([InlineKeyboardButton(
            text=f"{cs}{phone} | {country}",
            callback_data=f"purchase_detail_{pid}",
            icon_custom_emoji_id=lock if not cod else None
        )])

    btns.append([InlineKeyboardButton(
        text="Главное меню", callback_data="main_menu",
        icon_custom_emoji_id=E["home"]
    )])

    kb = InlineKeyboardMarkup(inline_keyboard=btns)
    txt = f"{em('📁', E['folder'])} <b>Мои покупки</b>\n\nВыберите аккаунт:"

    if hasattr(msg_or_cb, 'answer'):
        await msg_or_cb.answer(txt, reply_markup=kb)
    else:
        await msg_or_cb.message.edit_text(txt, reply_markup=kb)

# ============ CALLBACKS ============
@router.callback_query(F.data.startswith("countries_page_"))
async def cb_countries(callback: CallbackQuery):
    page = int(callback.data.split("_")[-1])
    await callback.message.edit_text(
        f"{em('📦', E['box'])} <b>Выберите страну:</b>",
        reply_markup=get_countries_keyboard(page)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("country_"))
async def cb_country(callback: CallbackQuery):
    code = callback.data.replace("country_", "")
    cname = code
    for name, c, flag in COUNTRIES:
        if c == code:
            cname = f"{flag} {name}"
            break
    await callback.message.edit_text(f"{em('🔄', E['loading'])} Ищу аккаунт...")
    acc = await find_and_validate_account(code)
    if not acc:
        await callback.message.edit_text(
            f"{em('❌', E['cross'])} Нет аккаунтов для {cname}.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="К выбору стран", callback_data="countries_page_0", icon_custom_emoji_id=E["back"])]
            ])
        )
        return
    asyncio.create_task(reserve_timeout(acc['id']))
    p = acc['buy_price']
    await callback.message.edit_text(
        f"{em('✅', E['check'])} <b>Аккаунт найден!</b>\n\n"
        f"{em('ℹ️', E['info'])} Страна: <b>{cname}</b>\n"
        f"{em('👛', E['wallet'])} Цена: <b>{p} RUB</b>\n\n"
        f"Выберите способ оплаты:",
        reply_markup=get_payment_keyboard(acc['id'], p)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("pay_stars_"))
async def cb_stars(callback: CallbackQuery):
    aid = int(callback.data.replace("pay_stars_", ""))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT buy_price FROM accounts WHERE id = %s", (aid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        await callback.answer("Не найден", show_alert=True)
        return
    price = int(float(row[0]))
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title="Покупка аккаунта",
        description="Telegram аккаунт | Vest Market",
        payload=f"stars_{aid}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Аккаунт", amount=price)]
    )
    await callback.message.delete()
    await callback.answer()

@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)

@router.message(F.successful_payment)
async def success_pay(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("stars_"):
        aid = int(payload.replace("stars_", ""))
        complete_purchase(message.from_user.id, aid, "stars")
        await send_acc_info(message, aid)

@router.callback_query(F.data.startswith("pay_crypto_"))
async def cb_crypto(callback: CallbackQuery):
    aid = int(callback.data.replace("pay_crypto_", ""))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT buy_price FROM accounts WHERE id = %s", (aid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        await callback.answer("Не найден", show_alert=True)
        return
    price = float(row[0])
    inv = await create_crypto_invoice(price)
    if not inv:
        await callback.answer("Ошибка счета", show_alert=True)
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO crypto_payments (user_id, invoice_id, amount, currency, account_id) VALUES (%s,%s,%s,%s,%s)",
                (callback.from_user.id, str(inv["invoice_id"]), price, "RUB", aid))
    conn.commit()
    conn.close()
    url = inv.get('pay_url', inv.get('bot_invoice_url', ''))
    await callback.message.edit_text(
        f"{em('👾', E['crypto'])} <b>Счет создан!</b>\n\nСумма: <b>{price} RUB</b>\nСсылка: {url}\n\nНажмите проверить:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Проверить оплату", callback_data=f"check_crypto_{inv['invoice_id']}_{aid}", icon_custom_emoji_id=E["loading"])],
            [InlineKeyboardButton(text="Отмена", callback_data="cancel_payment", icon_custom_emoji_id=E["cross"])]
        ])
    )
    await callback.answer()

@router.callback_query(F.data.startswith("check_crypto_"))
async def cb_check_crypto(callback: CallbackQuery):
    parts = callback.data.split("_")
    inv_id = parts[2]
    aid = int(parts[3])
    status = await check_crypto_invoice(int(inv_id))
    if status == "paid":
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE crypto_payments SET status='paid' WHERE invoice_id=%s", (inv_id,))
        conn.commit()
        conn.close()
        complete_purchase(callback.from_user.id, aid, "crypto")
        await callback.message.delete()
        await send_acc_info(callback.message, aid)
    elif status == "active":
        await callback.answer("Еще не оплачен", show_alert=True)
    else:
        await callback.answer("Ошибка / отменен", show_alert=True)

@router.callback_query(F.data.startswith("pay_balance_"))
async def cb_balance(callback: CallbackQuery):
    aid = int(callback.data.replace("pay_balance_", ""))
    uid = callback.from_user.id
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT buy_price FROM accounts WHERE id=%s", (aid,))
    acc = cur.fetchone()
    cur.execute("SELECT balance FROM users WHERE id=%s", (uid,))
    usr = cur.fetchone()
    conn.close()
    if not acc or not usr:
        await callback.answer("Ошибка", show_alert=True)
        return
    price = float(acc[0])
    bal = float(usr[0])
    if bal < price:
        await callback.answer(f"Мало средств! Баланс: {bal} RUB", show_alert=True)
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET balance=balance-%s WHERE id=%s", (price, uid))
    conn.commit()
    conn.close()
    complete_purchase(uid, aid, "balance")
    await callback.message.delete()
    await send_acc_info(callback.message, aid)

@router.callback_query(F.data == "cancel_payment")
async def cb_cancel(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(f"{em('❌', E['cross'])} Отменено", reply_markup=get_main_menu())
    await callback.answer()

async def send_acc_info(msg, aid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT phone, password_2fa, country FROM accounts WHERE id=%s", (aid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return
    phone, pwd, country = row
    pwd_txt = pwd or "Отсутствует"
    txt = (
        f"{em('🎉', E['party'])} <b>Покупка успешна!</b>\n\n"
        f"{em('ℹ️', E['info'])} Номер: <code>{phone}</code>\n"
        f"{em('🔒', E['lock'])} 2FA: <code>{pwd_txt}</code>\n\n"
        f"Нажмите чтобы получить код:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Получить код", callback_data=f"get_code_{aid}", icon_custom_emoji_id=E["code"])],
        [InlineKeyboardButton(text="Главное меню", callback_data="main_menu", icon_custom_emoji_id=E["home"])]
    ])
    if hasattr(msg, 'answer'):
        await msg.answer(txt, reply_markup=kb)
    else:
        await bot.send_message(msg.chat.id, txt, reply_markup=kb)

@router.callback_query(F.data.startswith("get_code_"))
async def cb_get_code(callback: CallbackQuery):
    aid = int(callback.data.replace("get_code_", ""))
    uid = callback.from_user.id
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.session_string, a.password_2fa, p.code_obtained, p.id
        FROM accounts a JOIN purchases p ON a.id=p.account_id
        WHERE a.id=%s AND p.user_id=%s
    """, (aid, uid))
    row = cur.fetchone()
    if not row:
        await callback.answer("Не найден", show_alert=True)
        conn.close()
        return
    ss, pwd, cod, pid = row
    if cod:
        await callback.answer("Код уже получен", show_alert=True)
        conn.close()
        return
    await callback.message.edit_text(f"{em('🔄', E['loading'])} Получаю код...")
    code = await get_login_code(ss, pwd)
    if code:
        cur.execute("UPDATE purchases SET code_obtained=TRUE WHERE id=%s", (pid,))
        conn.commit()
        await callback.message.edit_text(
            f"{em('✅', E['check'])} <b>Код:</b>\n\n<code>{code}</code>\n\n{em('ℹ️', E['info'])} Только один раз.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Главное меню", callback_data="main_menu", icon_custom_emoji_id=E["home"])]
            ])
        )
    else:
        await callback.message.edit_text(
            f"{em('❌', E['cross'])} Не удалось. Попробуйте позже в Мои покупки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Главное меню", callback_data="main_menu", icon_custom_emoji_id=E["home"])]
            ])
        )
    conn.close()

@router.callback_query(F.data == "my_purchases")
async def cb_my_purchases(callback: CallbackQuery):
    await show_purchases(callback)

@router.callback_query(F.data.startswith("purchase_detail_"))
async def cb_purchase_detail(callback: CallbackQuery):
    pid = int(callback.data.replace("purchase_detail_", ""))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.phone, a.country, a.password_2fa, p.purchase_date, p.code_obtained, a.id
        FROM purchases p JOIN accounts a ON p.account_id=a.id WHERE p.id=%s
    """, (pid,))
    row = cur.fetchone()
    conn.close()
    if not row:
        await callback.answer("Не найдена", show_alert=True)
        return
    phone, country, pwd, dt, cod, aid = row
    pwd_txt = pwd or "Отсутствует"
    cs = f"{em('✅', E['check'])} Получен" if cod else f"{em('❌', E['cross'])} Не получен"
    txt = (
        f"{em('ℹ️', E['info'])} <b>Детали</b>\n\n"
        f"Номер: <code>{phone}</code>\nСтрана: {country}\n"
        f"2FA: <code>{pwd_txt}</code>\nКуплен: {dt}\nКод: {cs}"
    )
    btns = []
    if not cod:
        btns.append([InlineKeyboardButton(text="Получить код", callback_data=f"get_code_{aid}", icon_custom_emoji_id=E["code"])])
    btns.append([InlineKeyboardButton(text="Назад к покупкам", callback_data="my_purchases", icon_custom_emoji_id=E["back"])])
    await callback.message.edit_text(txt, reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
    await callback.answer()

@router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer(
        f"{em('🏘', E['home'])} <b>Главное меню</b>\n\nВыберите действие:",
        reply_markup=get_main_menu()
    )
    await callback.answer()

# ============ ADMIN CALLBACKS ============
@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    tu = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM accounts")
    ta = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM accounts WHERE is_sold=TRUE")
    ts = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM accounts WHERE is_sold=FALSE AND is_valid=TRUE")
    av = cur.fetchone()[0]
    conn.close()
    await callback.message.edit_text(
        f"{em('📊', E['stats'])} <b>Статистика</b>\n\n"
        f"{em('👥', E['people'])} Пользователей: <b>{tu}</b>\n"
        f"{em('📦', E['box'])} Аккаунтов: <b>{ta}</b>\n"
        f"{em('✅', E['check'])} Продано: <b>{ts}</b>\n"
        f"{em('ℹ️', E['info'])} Доступно: <b>{av}</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Назад", callback_data="admin_back", icon_custom_emoji_id=E["back"])]
        ])
    )
    await callback.answer()

@router.callback_query(F.data == "admin_back")
async def cb_admin_back(callback: CallbackQuery):
    await callback.message.edit_text(
        f"{em('⚙️', E['settings'])} <b>Админ-панель</b>\n\nВыберите действие:",
        reply_markup=get_admin_keyboard()
    )
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)
    await callback.message.edit_text(
        f"{em('📣', E['broadcast_icon'])} <b>Отправьте сообщение для рассылки</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_back", icon_custom_emoji_id=E["cross"])]
        ])
    )
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.answer()

@router.message(AdminStates.waiting_broadcast)
async def broadcast_send(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users")
    users = cur.fetchall()
    conn.close()
    sent = 0
    for u in users:
        try:
            if message.photo:
                await bot.send_photo(u[0], message.photo[-1].file_id, caption=message.caption or "")
            elif message.video:
                await bot.send_video(u[0], message.video.file_id, caption=message.caption or "")
            else:
                await bot.send_message(u[0], message.text or "")
            sent += 1
        except:
            pass
        await asyncio.sleep(0.05)
    await message.answer(f"{em('✅', E['check'])} Рассылка: <b>{sent}</b>/{len(users)}")
    await state.clear()

@router.callback_query(F.data == "admin_balance")
async def cb_admin_balance(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)
    await callback.message.edit_text(
        f"{em('👛', E['wallet'])} <b>Введите ID пользователя:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_back", icon_custom_emoji_id=E["cross"])]
        ])
    )
    await state.set_state(AdminStates.waiting_balance_user)
    await callback.answer()

@router.message(AdminStates.waiting_balance_user)
async def balance_uid(message: Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        await state.update_data(bal_uid=uid)
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT balance FROM users WHERE id=%s", (uid,))
        u = cur.fetchone()
        conn.close()
        if not u:
            await message.answer(f"{em('❌', E['cross'])} Не найден")
            await state.clear()
            return
        await message.answer(f"{em('👛', E['wallet'])} Баланс: <b>{u[0]} RUB</b>\nВведите сумму (+100/-50):")
        await state.set_state(AdminStates.waiting_balance_amount)
    except ValueError:
        await message.answer(f"{em('❌', E['cross'])} Корректный ID")

@router.message(AdminStates.waiting_balance_amount)
async def balance_amt(message: Message, state: FSMContext):
    try:
        amt = float(message.text.strip())
        data = await state.get_data()
        uid = data['bal_uid']
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("UPDATE users SET balance=balance+%s WHERE id=%s", (amt, uid))
        cur.execute("SELECT balance FROM users WHERE id=%s", (uid,))
        nb = cur.fetchone()[0]
        conn.commit()
        conn.close()
        await message.answer(f"{em('✅', E['check'])} Баланс: <b>{nb} RUB</b>")
        await state.clear()
    except ValueError:
        await message.answer(f"{em('❌', E['cross'])} Корректная сумма")

@router.callback_query(F.data == "admin_prices")
async def cb_admin_prices(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)
    btns = []
    for name, code, flag in COUNTRIES:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT buy_price FROM price_settings WHERE country=%s", (code,))
        row = cur.fetchone()
        conn.close()
        price = row[0] if row else 100.0
        btns.append([InlineKeyboardButton(text=f"{flag} {name} - {price} RUB", callback_data=f"set_price_{code}")])
    btns.append([InlineKeyboardButton(text="Назад", callback_data="admin_back", icon_custom_emoji_id=E["back"])])
    await callback.message.edit_text(
        f"{em('🖋', E['edit'])} <b>Выберите страну:</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=btns)
    )
    await callback.answer()

@router.callback_query(F.data.startswith("set_price_"))
async def cb_set_price(callback: CallbackQuery, state: FSMContext):
    code = callback.data.replace("set_price_", "")
    await state.update_data(pr_country=code)
    await state.set_state(AdminStates.waiting_price_amount)
    await callback.message.edit_text(
        f"{em('🖋', E['edit'])} <b>Новая цена (RUB):</b>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_back", icon_custom_emoji_id=E["cross"])]
        ])
    )
    await callback.answer()

@router.message(AdminStates.waiting_price_amount)
async def price_save(message: Message, state: FSMContext):
    try:
        amt = float(message.text.strip())
        data = await state.get_data()
        code = data['pr_country']
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO price_settings (country, buy_price) VALUES (%s,%s) ON CONFLICT (country) DO UPDATE SET buy_price=%s", (code, amt, amt))
        conn.commit()
        conn.close()
        await message.answer(f"{em('✅', E['check'])} Цена {code}: <b>{amt} RUB</b>")
        await state.clear()
    except ValueError:
        await message.answer(f"{em('❌', E['cross'])} Корректная сумма")

@router.callback_query(F.data == "admin_media")
async def cb_admin_media(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID:
        return await callback.answer("Нет доступа", show_alert=True)
    await callback.message.edit_text(
        f"{em('🖼', E['media'])} <b>Отправьте медиа</b>\n\nФормат подписи: секция | текст",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="admin_back", icon_custom_emoji_id=E["cross"])]
        ])
    )
    await state.set_state(AdminStates.waiting_media)
    await callback.answer()

@router.message(AdminStates.waiting_media)
async def media_save(message: Message, state: FSMContext):
    cap = message.caption or ""
    section = "main"
    if "|" in cap:
        parts = cap.split("|", 1)
        section = parts[0].strip()
        cap = parts[1].strip() if len(parts) > 1 else ""
    fid, ftype = None, None
    if message.photo:
        fid, ftype = message.photo[-1].file_id, "photo"
    elif message.video:
        fid, ftype = message.video.file_id, "video"
    if fid:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO media_settings (section, file_id, file_type, caption) VALUES (%s,%s,%s,%s) ON CONFLICT (section) DO UPDATE SET file_id=%s, file_type=%s, caption=%s",
                    (section, fid, ftype, cap, fid, ftype, cap))
        conn.commit()
        conn.close()
        await message.answer(f"{em('✅', E['check'])} Сохранено: <b>{section}</b>")
    else:
        await message.answer(f"{em('❌', E['cross'])} Отправьте фото/видео")
    await state.clear()

# ============ MAIN ============
async def main():
    init_db()
    logger.info("Bot started")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
