import os
import asyncio
import asyncpg
import openai
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

# ✅ Загружаем API-ключи из переменных окружения
TOKEN = os.getenv("API_TOKEN")  # Токен Telegram-бота
DATABASE_URL = os.getenv("DATABASE_URL")  # Подключение к PostgreSQL
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # API-ключ OpenAI

# Проверяем, что все переменные окружения заданы
if not TOKEN or not DATABASE_URL or not OPENAI_API_KEY:
    raise ValueError("❌ Ошибка: Переменные API_TOKEN, DATABASE_URL или OPENAI_API_KEY не установлены!")

# ✅ Инициализируем бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ✅ Подключаемся к OpenAI
openai.api_key = OPENAI_API_KEY

# ✅ Функция для получения ответа от OpenAI
async def get_openai_answer(question: str):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": question}],
            temperature=0.7
        )
        return response["choices"][0]["message"]["content"]
    except Exception as e:
        return "⚠ Ошибка при запросе к OpenAI."

# ✅ Команда /start
@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer("Привет! Я бот RenderGuru. Задай мне любой вопрос по 3D-визуализации!")

# ✅ Команда /ask для вопросов к OpenAI
@dp.message(Command("ask"))
async def ask_cmd(message: Message):
    user_question = message.text.replace("/ask", "").strip()
    if not user_question:
        await message.answer("❌ Вопрос не может быть пустым. Используй `/ask Твой вопрос`.")
        return
    answer = await get_openai_answer(user_question)
    await message.answer(answer)

# ✅ Запуск бота
async def main():
    print("🚀 Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
