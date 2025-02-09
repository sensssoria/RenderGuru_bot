import os
import asyncio
import logging

# aiogram 3.x
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

# Если используешь python-dotenv, можем попытаться загрузить .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("dotenv не установлен, пропускаем загрузку .env")

# Берём токен из переменных окружения
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    print("ОШИБКА: Токен не найден! Проверь переменные окружения в Railway!")
    exit(1)

# Логирование (можно отключить, если не нужно)
logging.basicConfig(level=logging.INFO)

# Создаём бота и диспетчер
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Обрабатываем команду /start
@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer("Привет! Я бот на aiogram 3.x. Работаю исправно!")

# Основная асинхронная функция
async def main():
    # Выведем кусочек токена для отладки (не весь, чтобы не светить полностью)
    print(f"✅ Бот запускается с токеном: {TOKEN[:10]}... (дальше скрыто)")
    # Запускаем поллинг (опрос Telegram на новые сообщения)
    await dp.start_polling(bot)

# Запуск бота
if __name__ == "__main__":
    asyncio.run(main())
