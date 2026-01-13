# loader.py
import os
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

load_dotenv()

# --- БОТ ДЛЯ БАРБЕРА ---
BARBER_BOT_TOKEN = os.getenv("BARBER_BOT_TOKEN")
# Создаем объекты, но не запускаем их
bot_barber = Bot(token=BARBER_BOT_TOKEN)
dp_barber = Dispatcher(storage=MemoryStorage())

# --- БОТ ДЛЯ КЛИЕНТА ---
CLIENT_BOT_TOKEN = os.getenv("CLIENT_BOT_TOKEN")
bot_client = Bot(token=CLIENT_BOT_TOKEN)
dp_client = Dispatcher(storage=MemoryStorage())

# --- БОТ ДЛЯ АДМИНА ---
ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
bot_admin = Bot(token=ADMIN_BOT_TOKEN)
dp_admin = Dispatcher(storage=MemoryStorage())