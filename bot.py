import asyncio
import logging
import random
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.filters import Command
import aiosqlite
import os

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 123456789))
PAYMENT_TIMEOUT = int(os.getenv("PAYMENT_TIMEOUT", 1200))  # 20 menit default
QRIS_IMAGE = "qris.jpg"  # pastikan file ada di folder project

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

    buttons = [[InlineKeyboardButton(text=row[1], callback_data=f"country_{row[0]}")] for row in rows]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.answer("🌍 Silakan pilih negara tersedia 🌍", reply_markup=keyboard)

@dp.callback_query(F.data.startswith("country_"))
async def select_country(callback: CallbackQuery):
    country_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT id, code, price FROM products WHERE country_id=? AND sold=0", (country_id,))
        product = await cursor.fetchone()

        if not product:
            await callback.message.answer("⚠️ Produk untuk negara ini sedang habis!")
            return

        product_id, code, price = product
        expire_at = (datetime.utcnow() + timedelta(seconds=PAYMENT_TIMEOUT)).isoformat()
        await db.execute("INSERT INTO orders(user_id, product_id, expire_at, status) VALUES(?,?,?,?)",
                         (callback.from_user.id, product_id, expire_at, "pending"))
        await db.execute("UPDATE products SET sold=1 WHERE id=?", (product_id,))
        await db.commit()

    # Kirim QRIS untuk bayar
    qris_file = InputFile(QRIS_IMAGE)
    await callback.message.answer_photo(
        photo=qris_file,
        caption=f"💎 Pesanan kamu berhasil dibuat!\nKode Produk: {code}\nHarga: {price}\nSilakan bayar menggunakan QRIS di atas.\n⏰ Waktu pembayaran: {PAYMENT_TIMEOUT//60} menit"
    )

    asyncio.create_task(cancel_order_later(product_id, callback.from_user.id))

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
1️⃣ Tambah Negara: /add_country NamaNegara
2️⃣ Hapus Negara: /remove_country country_id
3️⃣ Tambah Produk: /add_product country_id harga
4️⃣ Hapus Produk: /remove_product product_id
5️⃣ Blokir User: /block user_id
6️⃣ Buka Blokir User: /unblock user_id
7️⃣ Lihat Order Pending: /orders
"""
    await callback.message.answer(text)

# ================= ADMIN COMMANDS =================
@dp.message(Command("add_country"))
async def add_country(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2:
        await message.reply("Gunakan format: /add_country NamaNegara")
        return
    name = parts[1].strip()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO countries(name) VALUES(?)", (name,))
        await db.commit()
    await message.reply(f"✅ Negara '{name}' berhasil ditambahkan")

@dp.message(Command("remove_country"))
async def remove_country(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split(maxsplit=1)
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Gunakan format: /remove_country country_id")
        return
    country_id = int(parts[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM countries WHERE id=?", (country_id,))
        await db.commit()
    await message.reply(f"✅ Negara dengan ID {country_id} berhasil dihapus")

@dp.message(Command("add_product"))
async def add_product(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.reply("Gunakan format: /add_product country_id harga")
        return
    country_id = int(parts[1])
    price = int(parts[2])
    code = generate_code()
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("INSERT INTO products(country_id, code, price) VALUES(?,?,?)", (country_id, code, price))
        await db.commit()
    await message.reply(f"✅ Produk berhasil ditambahkan dengan code {code} dan harga {price}")

@dp.message(Command("remove_product"))
async def remove_product(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Gunakan format: /remove_product product_id")
        return
    product_id = int(parts[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("DELETE FROM products WHERE id=?", (product_id,))
        await db.commit()
    await message.reply(f"✅ Produk dengan ID {product_id} berhasil dihapus")

@dp.message(Command("block"))
async def block_user(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Gunakan format: /block user_id")
        return
    user_id = int(parts[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET blocked=1 WHERE user_id=?", (user_id,))
        await db.commit()
    await message.reply(f"🚫 User {user_id} diblokir")

@dp.message(Command("unblock"))
async def unblock_user(message: Message):
    if message.from_user.id != ADMIN_ID: return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.reply("Gunakan format: /unblock user_id")
        return
    user_id = int(parts[1])
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("UPDATE users SET blocked=0 WHERE user_id=?", (user_id,))
        await db.commit()
    await message.reply(f"✅ User {user_id} dibuka blokirnya")

@dp.message(Command("orders"))
async def list_orders(message: Message):
    if message.from_user.id != ADMIN_ID: return
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("""
        SELECT o.id,u.user_id,p.code,p.price,o.status
        FROM orders o
        LEFT JOIN users u ON o.user_id=u.user_id
        LEFT JOIN products p ON o.product_id=p.id
        """)
        rows = await cursor.fetchall()
    if not rows:
        await message.reply("Belum ada pesanan")
        return
    text = "📦 Daftar Pesanan:\n\n"
    for r in rows:
        text += f"ID: {r[0]}, User: {r[1]}, Code: {r[2]}, Harga: {r[3]}, Status: {r[4]}\n"
    await message.reply(text)

# ================= MAIN =================
async def main():
    await init_db()
    logging.info("🟢 Menghapus webhook lama...")
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("🟢 Memulai polling bot...")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
