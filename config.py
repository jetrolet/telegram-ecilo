import os

# Token bot Telegram
BOT_TOKEN = os.getenv("BOT_TOKEN", "8703742903:AAFq--XFq2wFFGAtmB2ApwQcpOYKg1ps-cI")

# ID admin Telegram
ADMIN_ID = int(os.getenv("ADMIN_ID", 35055316))

# Timeout pembayaran dalam detik (misal 20 menit = 1200 detik)
PAYMENT_TIMEOUT = int(os.getenv("PAYMENT_TIMEOUT", 1200))

# Nama file QRIS untuk pembayaran
QRIS_IMAGE = "qris.jpg"
