import asyncio
import logging
import random
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
import aiosqlite
import os

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789))
PAYMENT_TIMEOUT = int(os.getenv("PAYMENT_TIMEOUT", 1200))
QRIS_IMAGE = "qris.jpg"  # pastikan file ada di project

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

DB_NAME = "database.db"

# ================= DATABASE =================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            blocked INTEGER DEFAULT 0
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS countries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS products(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_id INTEGER,
            code TEXT,
            price INTEGER,
            sold INTEGER DEFAULT 0
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            product_id INTEGER,
            expire_at TEXT,
            status TEXT
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS complaints(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT,
            created_at TEXT
        )
        """)
        await db.commit()

# ================= UTIL =================
def generate_code():
    return str(random.randint(100000000, 999999999))

async def is_blocked(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT blocked FROM users WHERE user_id=?", (user_id,))
        row = await cursor.fetchone()
        return row[0] == 1 if row else False

async def register_user(user_id):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT OR IGNORE INTO users(user_id) VALUES(?)", (user_id,))
        await db.commit()

# ================= START =================
@dp.message(Command("start"))
async def start(message: Message):
    user = message.from_user
    await register_user(user.id)

    if await is_blocked(user.id):
        await message.answer("🚫 Akses Anda telah dibatasi 🚫")
        return

    photos = await bot.get_user_profile_photos(user.id)
    profile_status = "✅ Menggunakan Foto Profil" if photos.total_count > 0 else "❌ Tidak Ada Foto Profil"

    text = f"""
👋 Halo, {user.first_name}! 🎉

Selamat datang di NOKTEL OLD TG 💎

📌 Detail Akun Anda:
• Nama: {user.first_name}
• Username: @{user.username if user.username else 'Tidak Ada'}
• ID: {user.id}
• Status Profil: {profile_status}

Silakan pilih menu di bawah dan ikuti semua peraturan ⚠️
"""

    if user.id == ADMIN_ID:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🛒 Beli Produk", callback_data="buy")],
            [InlineKeyboardButton("📦 Pesanan Saya", callback_data="orders")],
            [InlineKeyboardButton("❓ Bantuan", callback_data="help")],
            [InlineKeyboardButton("👑 Panel Admin", callback_data="admin_panel")]
        ])
    else:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton("🛒 Beli Produk", callback_data="buy")],
            [InlineKeyboardButton("📦 Pesanan Saya", callback_data="orders")],
            [InlineKeyboardButton("❓ Bantuan", callback_data="help")]
        ])

    await message.answer(text, reply_markup=keyboard)

# ================= BUY FLOW =================
@dp.callback_query(F.data == "buy")
async def show_countries(callback: CallbackQuery):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id,name FROM countries")
        rows = await cursor.fetchall()

    if not rows:
        await callback.message.answer("⚠️ Belum ada negara tersedia ⚠️")
        return

    buttons = [[InlineKeyboardButton(row[1], callback_data=f"country_{row[0]}")] for row in rows]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer("🌍 Silakan pilih negara tersedia 🌍", reply_markup=keyboard)

# ================= PAYMENT TIMER =================
async def cancel_order_later(order_id, user_id):
    await asyncio.sleep(PAYMENT_TIMEOUT)

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT status, product_id FROM orders WHERE id=?", (order_id,))
        row = await cursor.fetchone()

        if row and row[0] == "pending":
            await db.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
            await db.execute("UPDATE products SET sold=0 WHERE id=?", (row[1],))
            await db.commit()

            await bot.send_message(user_id,
                "❌ Pesanan dibatalkan otomatis karena waktu habis ⏰\nSilakan lakukan pemesanan ulang jika masih tersedia 💎"
            )

# ================= ADMIN PANEL =================
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("🚫 Akses ditolak 🚫", show_alert=True)
        return

    text = """
👑 PANEL ADMIN NOKTEL OLD TG 💎

📌 Panduan Cepat:

1️⃣ Tambah Negara:
/add_country NamaNegara
Contoh: /add_country Indonesia 🌏

2️⃣ Tambah Produk / ID:
/add_product country_id harga
Contoh: /add_product 1 15000

3️⃣ Hapus Negara:
/remove_country country_id
Contoh: /remove_country 1

4️⃣ Hapus Produk / ID:
/remove_product product_id
Contoh: /remove_product 12

5️⃣ Blokir User:
/block user_id
Contoh: /block 123456789

6️⃣ Buka Blokir User:
/unblock user_id
Contoh: /unblock 123456789

7️⃣ Lihat Order Pending:
/orders
- Menampilkan pesanan aktif menunggu pembayaran atau konfirmasi

💡 Tips:
- Pastikan setiap negara sudah punya produk / ID
- Gunakan harga sesuai ketentuan
- Emoji akan membantu pesan terlihat jelas 🎉
"""
    await callback.message.answer(text)

# ================= MAIN =================
async def main():
    await init_db()

    # 🟢 HAPUS WEBHOOK LAMA (Mencegah TelegramConflictError)
    await bot.delete_webhook(drop_pending_updates=True)

    logging.info("🟢 Memulai polling bot...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
