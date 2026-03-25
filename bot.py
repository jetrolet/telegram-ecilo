import asyncio
import logging
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandStart
import aiosqlite
import os

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789))
PAYMENT_TIMEOUT = int(os.getenv("PAYMENT_TIMEOUT", 1200))
QRIS_IMAGE = "qris.jpg"  # pastikan ada di root project

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
            status TEXT,
            proof TEXT
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
@dp.message(CommandStart())
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

    buttons = [[InlineKeyboardButton(text=row[1], callback_data=f"country_{row[0]}")] for row in rows]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("🌍 Silakan pilih negara tersedia 🌍", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("country_"))
async def select_country(callback: CallbackQuery):
    country_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, code, price FROM products WHERE country_id=? AND sold=0", (country_id,))
        rows = await cursor.fetchall()

    if not rows:
        await callback.message.answer("⚠️ Produk untuk negara ini sedang habis!")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(f"{row[1]} - Rp{row[2]}", callback_data=f"product_{row[0]}")] for row in rows]
    )
    await callback.message.answer("Pilih produk yang ingin dibeli:", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("product_"))
async def select_product(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    expire_at = (datetime.now() + timedelta(seconds=PAYMENT_TIMEOUT)).isoformat()

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO orders(user_id, product_id, expire_at, status) VALUES(?,?,?,?)",
                         (user_id, product_id, expire_at, "pending"))
        await db.commit()
        cursor = await db.execute("SELECT last_insert_rowid()")
        order_id = (await cursor.fetchone())[0]

    # Kirim QRIS ke user
    if os.path.exists(QRIS_IMAGE):
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton("✅ Kirim Bukti Pembayaran", callback_data=f"pay_{order_id}")]]
        )
        await callback.message.answer_photo(open(QRIS_IMAGE, "rb"),
                                            caption=f"📌 Silakan lakukan pembayaran produk ini.\nID Pesanan: {order_id}\nBatas waktu: {PAYMENT_TIMEOUT//60} menit",
                                            reply_markup=keyboard)
    else:
        await callback.message.answer("⚠️ QRIS belum tersedia!")

    # Start timeout task
    asyncio.create_task(cancel_order_later(order_id, user_id))

@dp.callback_query(F.data.startswith("pay_"))
async def send_proof(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    await callback.message.answer("Silakan kirim bukti pembayaran (foto) untuk pesanan ini.")
    # Simpan state sementara agar bot tahu order_id (di versi sederhana kita bisa pakai dict)
    dp.current_order = order_id  # Sederhana, untuk 1 user aktif

@dp.message()
async def receive_proof(message: Message):
    if not hasattr(dp, "current_order"):
        return
    if not message.photo:
        return
    order_id = dp.current_order
    dp.current_order = None
    photo_file_id = message.photo[-1].file_id

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE orders SET proof=?, status='waiting_approval' WHERE id=?", (photo_file_id, order_id))
        await db.commit()

    await message.answer("✅ Bukti pembayaran diterima. Admin akan memeriksa pesanan Anda.")

    # Notify admin
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{order_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject_{order_id}")]
    ])
    await bot.send_photo(ADMIN_ID, photo=photo_file_id,
                         caption=f"📌 Pesanan ID {order_id} menunggu persetujuan.",
                         reply_markup=keyboard)

# ================= ADMIN APPROVE/REJECT =================
@dp.callback_query(F.data.startswith("approve_"))
async def admin_approve(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id FROM orders WHERE id=?", (order_id,))
        user_id = (await cursor.fetchone())[0]
        await db.execute("UPDATE orders SET status='approved' WHERE id=?", (order_id,))
        await db.commit()

    await callback.message.answer(f"✅ Pesanan ID {order_id} telah disetujui.")
    await bot.send_message(user_id, f"🎉 Pesanan ID {order_id} Anda telah disetujui. Silakan cek produk Anda!")

@dp.callback_query(F.data.startswith("reject_"))
async def admin_reject(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT user_id, product_id FROM orders WHERE id=?", (order_id,))
        row = await cursor.fetchone()
        user_id, product_id = row
        await db.execute("UPDATE orders SET status='rejected' WHERE id=?", (order_id,))
        await db.execute("UPDATE products SET sold=0 WHERE id=?", (product_id,))
        await db.commit()

    await callback.message.answer(f"❌ Pesanan ID {order_id} telah ditolak.")
    await bot.send_message(user_id, f"❌ Pesanan ID {order_id} Anda ditolak. Silakan lakukan pemesanan ulang jika ingin.")

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
                                   "❌ Pesanan dibatalkan otomatis karena waktu habis ⏰\nSilakan lakukan pemesanan ulang jika masih tersedia 💎")

# ================= ADMIN PANEL & COMMANDS =================
# ... tetap sama seperti sebelumnya (add/remove country/product, block/unblock, list orders)

# ================= MAIN =================
async def main():
    await init_db()
    logging.info("🟢 Menghapus webhook lama...")
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🟢 Memulai polling bot...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
