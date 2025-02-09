import os
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

# Если .env не подключался раньше – устанавливай python-dotenv в requirements, а потом импортируй и подгружай:
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("У тебя не установлен python-dotenv, пропускаем этот шаг...")

# Читаем токен из переменных окружения
TOKEN = os.getenv("TOKEN")

# Проверяем, что токен нашёлся
if not TOKEN:
    print("ОШИБКА: Токен не найден! Проверь переменные окружения в Railway!")
    exit(1)

# Включаем логирование
logging.basicConfig(level=logging.INFO)

# Создаём экземпляры бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Обработчик команды /start
@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer("Привет! Я бот на aiogram 3.x. Всё работает!")

# Главная асинхронная функция
async def main():
    # Выведем часть токена для проверки, что он не пуст
    print(f"✅ Бот запускается с токеном: {TOKEN[:10]}... (дальше скрыто)")
    await dp.start_polling(bot)

# Запуск бота
if __name__ == "__main__":
    asyncio.run(main())
