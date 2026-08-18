import asyncio
import logging
import sqlite3
import os

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ChatJoinRequest,
)
from aiogram.enums import ParseMode

# ============ SOZLAMALAR ============
BOT_TOKEN = os.getenv("BOT_TOKEN", "8950152316:AAHjF3IFPjOf9VIA522qVClZ1eNqLtNvYA4")
ADMIN_IDS = [8309061996]

# Majburiy zayavka uchun kanal. Kanal PRIVATE bo'lishi va
# "Ovoz berishni tasdiqlash" / join-request rejimi YOQILGAN bo'lishi kerak
# (Kanal sozlamalari -> Invite Links -> "Require admin approval for new members")
CHANNEL_ID = -1003994139298          # -100 prefiksi qo'shildi (kanal/superguruh ID formati shunday)
CHANNEL_LINK = "https://t.me/+JNZSVXkMJ9oxMWEy"

DB_PATH = "movies.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)


# ============ FSM HOLATLARI ============
class AddMovie(StatesGroup):
    waiting_video = State()
    waiting_code = State()
    waiting_title = State()


class DelMovie(StatesGroup):
    waiting_code = State()


# ============ BAZA ============
def db_init():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            code TEXT PRIMARY KEY,
            file_id TEXT NOT NULL,
            title TEXT,
            added_by INTEGER
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS join_requests (
            user_id INTEGER PRIMARY KEY
        )
    """)
    conn.commit()
    conn.close()


def db_add_movie(code, file_id, title, added_by):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO movies (code, file_id, title, added_by) VALUES (?, ?, ?, ?)",
        (code, file_id, title, added_by),
    )
    conn.commit()
    conn.close()


def db_get_movie(code):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT file_id, title FROM movies WHERE code = ?", (code,))
    row = cur.fetchone()
    conn.close()
    return row


def db_delete_movie(code) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM movies WHERE code = ?", (code,))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def db_list_movies(limit=30):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT code, title FROM movies ORDER BY rowid DESC LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def db_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM movies")
    n = cur.fetchone()[0]
    conn.close()
    return n


def db_save_join_request(user_id: int):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO join_requests (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()


def db_has_join_request(user_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM join_requests WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row is not None


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ============ KLAVIATURALAR ============
def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Kino qo'shish", callback_data="adm_add"),
            InlineKeyboardButton(text="🗑 Kino o'chirish", callback_data="adm_del"),
        ],
        [
            InlineKeyboardButton(text="📋 Kinolar ro'yxati", callback_data="adm_list"),
            InlineKeyboardButton(text="📊 Statistika", callback_data="adm_stats"),
        ],
    ])


def cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="adm_cancel")]
    ])


def subscribe_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Kanalga o'tish", url=CHANNEL_LINK)],
        [InlineKeyboardButton(text="✅ Tekshirish", callback_data=f"check:{code}")],
    ])


# ============ FOYDALANUVCHI: START ============
@router.message(CommandStart())
async def cmd_start(message: Message):
    await message.answer(
        "🎬 <b>Kino kodi botga xush kelibsiz!</b>\n\n"
        "Kino olish uchun shunchaki kino kodini yuboring.\n"
        "Masalan: <code>1234</code>\n\n"
        f"Hozircha bazada <b>{db_count()}</b> ta kino mavjud."
    )


# ============ ADMIN: PANELNI OCHISH ============
@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("⚙️ <b>Admin panel</b>", reply_markup=admin_panel_kb())


# ============ ADMIN: TUGMALAR ============
@router.callback_query(F.data == "adm_cancel")
async def adm_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("⚙️ <b>Admin panel</b>", reply_markup=admin_panel_kb())
    await call.answer("Bekor qilindi")


@router.callback_query(F.data == "adm_stats")
async def adm_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    await call.message.edit_text(
        f"📊 Bazada jami: <b>{db_count()}</b> ta kino",
        reply_markup=admin_panel_kb(),
    )
    await call.answer()


@router.callback_query(F.data == "adm_list")
async def adm_list(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return await call.answer()
    rows = db_list_movies()
    if not rows:
        text = "Hozircha kino yo'q."
    else:
        text = "📋 <b>Oxirgi kinolar:</b>\n\n" + "\n".join(
            f"• <code>{code}</code> — {title}" for code, title in rows
        )
    await call.message.edit_text(text, reply_markup=admin_panel_kb())
    await call.answer()


@router.callback_query(F.data == "adm_add")
async def adm_add_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer()
    await state.set_state(AddMovie.waiting_video)
    await call.message.edit_text(
        "🎬 Kino videosini (yoki faylini) yuboring.",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(StateFilter(AddMovie.waiting_video))
async def adm_add_get_video(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    video = message.video or message.document
    if not video:
        await message.answer("⚠️ Iltimos, video yoki fayl yuboring.", reply_markup=cancel_kb())
        return
    await state.update_data(file_id=video.file_id)
    await state.set_state(AddMovie.waiting_code)
    await message.answer("🔢 Endi shu kino uchun kod kiriting (masalan: 1234).", reply_markup=cancel_kb())


@router.message(StateFilter(AddMovie.waiting_code))
async def adm_add_get_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    code = message.text.strip()
    if db_get_movie(code):
        await message.answer(
            f"⚠️ <code>{code}</code> kodi band. Boshqa kod kiriting.",
            reply_markup=cancel_kb(),
        )
        return
    await state.update_data(code=code)
    await state.set_state(AddMovie.waiting_title)
    await message.answer("✏️ Endi kino nomini kiriting.", reply_markup=cancel_kb())


@router.message(StateFilter(AddMovie.waiting_title))
async def adm_add_get_title(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    title = message.text.strip()
    db_add_movie(data["code"], data["file_id"], title, message.from_user.id)
    await state.clear()
    await message.answer(
        f"✅ Saqlandi!\nKod: <code>{data['code']}</code>\nNomi: {title}",
        reply_markup=admin_panel_kb(),
    )


@router.callback_query(F.data == "adm_del")
async def adm_del_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return await call.answer()
    await state.set_state(DelMovie.waiting_code)
    await call.message.edit_text(
        "🗑 O'chirmoqchi bo'lgan kino kodini kiriting.",
        reply_markup=cancel_kb(),
    )
    await call.answer()


@router.message(StateFilter(DelMovie.waiting_code))
async def adm_del_get_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    code = message.text.strip()
    await state.clear()
    if db_delete_movie(code):
        await message.answer(f"🗑 <code>{code}</code> o'chirildi.", reply_markup=admin_panel_kb())
    else:
        await message.answer("❌ Bunday kod topilmadi.", reply_markup=admin_panel_kb())


# ============ ZAYAVKA (JOIN REQUEST) KUZATISH ============
@router.chat_join_request()
async def handle_join_request(update: ChatJoinRequest):
    if update.chat.id == CHANNEL_ID:
        db_save_join_request(update.from_user.id)


@router.callback_query(F.data.startswith("check:"))
async def check_subscription(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    user_id = call.from_user.id

    if db_has_join_request(user_id):
        row = db_get_movie(code)
        if row:
            file_id, title = row
            await call.message.delete()
            try:
                await bot.send_video(user_id, file_id, caption=f"🎬 {title}")
            except Exception:
                await bot.send_document(user_id, file_id, caption=f"🎬 {title}")
            await call.answer("✅ Tasdiqlandi!")
        else:
            await call.answer("❌ Kino topilmadi.", show_alert=True)
    else:
        await call.answer(
            "❌ Siz hali kanalga zayavka tashlamagansiz. Avval kanalga o'ting va 'Join'/'A'zo bo'lish' tugmasini bosing.",
            show_alert=True,
        )


# ============ FOYDALANUVCHI: KOD YUBORGANDA ============
@router.message(F.text, StateFilter(None))
async def handle_code(message: Message):
    code = message.text.strip()
    row = db_get_movie(code)

    if not row:
        await message.answer("❌ Bunday kodli kino topilmadi.\nKodni tekshirib qaytadan yuboring.")
        return

    user_id = message.from_user.id
    if not db_has_join_request(user_id):
        await message.answer(
            "🔒 Bu kinoni olishdan oldin kanalimizga zayavka tashlashingiz kerak.\n\n"
            "1️⃣ Pastdagi tugma orqali kanalga o'ting\n"
            "2️⃣ 'Join'/'A'zo bo'lish' tugmasini bosing\n"
            "3️⃣ Shu yerga qaytib '✅ Tekshirish' tugmasini bosing",
            reply_markup=subscribe_kb(code),
        )
        return

    file_id, title = row
    try:
        await message.answer_video(file_id, caption=f"🎬 {title}")
    except Exception:
        await message.answer_document(file_id, caption=f"🎬 {title}")


# ============ ISHGA TUSHIRISH ============
async def main():
    db_init()
    print("Bot ishga tushdi...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
