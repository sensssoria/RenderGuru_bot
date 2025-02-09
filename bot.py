import os
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()
TOKEN = os.getenv("TOKEN")

# Проверяем, загружен ли токен
if not TOKEN:
    print("ОШИБКА: Токен не найден! Проверь переменные окружения в Railway!")
    exit(1)

# Логирование
logging.basicConfig(level=logging.INFO)

# Создание бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Проверка команды /start
@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("Привет! Я т
