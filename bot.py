import os
import asyncio
import logging

import asyncpg
import openai

from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

# Попытка загрузить .env (если есть), чтобы читать переменные окружения локально
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv не установлен, пропускаем загрузку .env")

# Читаем переменные окружения
TOKEN = os.getenv("TOKEN")                # Токен бота
DATABASE_URL = os.getenv("DATABASE_URL")  # Строка подключения к PostgreSQL
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Ключ OpenAI

# Если токен бота не найден — останавливаем
if not TOKEN:
    print("ОШИБКА: Токен бота не найден! Проверь переменные окружения!")
    exit(1)

# Настраиваем логирование (можете поменять уровень на WARNING, если слишком много сообщений)
logging.basicConfig(level=logging.INFO)

# Создаём объекты бота и диспетчера aiogram 3.x
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Настраиваем ключ OpenAI
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
else:
    print("⚠️ Предупреждение: OPENAI_API_KEY не найден. /test_gpt будет выдавать ошибку.")

# =========================== Обработчики команд ===========================

@dp.message(Command("start"))
async def start_cmd(message: Message):
    """Приветствие бота + подсказка."""
    await message.answer(
        "Привет! Я бот на aiogram 3.x. Работаю исправно!\n"
        "Доступные команды:\n"
        "  /test_db  — проверить соединение с PostgreSQL\n"
        "  /test_gpt — проверить запрос к OpenAI GPT\n"
    )

@dp.message(Command("test_db"))
async def test_db_command(message: Message):
    """Проверяем соединение с PostgreSQL."""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("SELECT 1")  # Простой тест
        await conn.close()
        await message.answer("✅ Подключение к базе прошло успешно!")
    except Exception as e:
        await message.answer(f"❌ Ошибка подключения к БД:\n{e}")

@dp.message(Command("test_gpt"))
async def test_gpt_command(message: Message):
    """Проверяем запрос к OpenAI GPT."""
    try:
        question = "Привет, расскажи анекдот!"
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",  # Можно указать gpt-4, если у вас есть доступ
            messages=[{"role": "user", "content": question}]
        )
        gpt_answer = response.choices[0].message.content
        await message.answer(f"GPT ответил:\n{gpt_answer}")
    except Exception as e:
        await message.answer(f"❌ Ошибка GPT:\n{e}")


# =========================== Запуск бота ===========================

async def main():
    """Запускаем бота в режиме polling."""
    # Выведем кусочек токена для контроля, что он не пуст
    print(f"✅ Бот запускается с токеном: {TOKEN[:10]}... (скрыто дальше)")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
