import logging
import asyncpg
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.utils import executor

# Настройки бота
TOKEN = "7867162876:AAGikAKxu1HIVXwQC8RfqRib2MPlDsrTk6c"
DATABASE_URL = "postgresql://postgres:***@postgres.railway.internal:5432/railway"

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

logging.basicConfig(level=logging.INFO)

# Проверка работы базы данных
@dp.message_handler(commands=['test_db'])
async def test_db(message: Message):
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("SELECT 1")
        await conn.close()
        await message.answer("База данных работает! 🎉")
    except Exception as e:
        await message.answer(f"Ошибка подключения к БД: {e}")

# Обработчик команды старт
@dp.message_handler(commands=['start'])
async def start(message: Message):
    await message.answer("Привет! Я бот. Отправь /test_db для проверки БД.")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
