import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

TOKEN = "ТВОЙ_ТОКЕН"

# Включаем логирование (можно отключить, если не нужно)
logging.basicConfig(level=logging.INFO)

# Создаем экземпляры бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Пример обработки команды /start
@dp.message(Command("start"))
async def start_handler(message: Message):
    await message.answer("Привет! Я твой Telegram-бот!")

# Главная асинхронная функция
async def main():
    await dp.start_polling(bot)

# Запускаем бота
if __name__ == "__main__":
    asyncio.run(main())

