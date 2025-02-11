import os
import asyncio
import asyncpg
import openai
import numpy as np
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command
from sentence_transformers import SentenceTransformer

# ✅ Загружаем API-ключи и БД из переменных окружения
TOKEN = os.getenv("API_TOKEN")  # Токен Telegram-бота
DATABASE_URL = os.getenv("DATABASE_URL")  # Подключение к PostgreSQL
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # API-ключ OpenAI

if not TOKEN or not DATABASE_URL or not OPENAI_API_KEY:
    raise ValueError("❌ Ошибка: API_TOKEN, DATABASE_URL или OPENAI_API_KEY не установлены!")

# ✅ Инициализируем бота
bot = Bot(token=TOKEN)
dp = Dispatcher()

# ✅ NLP-модель для поиска по смыслу
model = SentenceTransformer("all-MiniLM-L6-v2")

# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С БД ============

async def init_db():
    """Создание таблиц в БД"""
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id SERIAL PRIMARY KEY,
            question TEXT UNIQUE NOT NULL,
            answer TEXT NOT NULL,
            embedding VECTOR(384)
        );

        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id BIGINT PRIMARY KEY
        );
    """)
    await conn.close()

async def search_in_db(question: str):
    """Поиск ответа в БД по смыслу"""
    query_embedding = model.encode(question).tolist()
    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch("SELECT answer, embedding FROM knowledge_base")
    await conn.close()

    if not rows:
        return None

    best_match = None
    best_score = -1

    for row in rows:
        stored_embedding = np.array(row["embedding"])
        score = np.dot(query_embedding, stored_embedding) / (np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding))

        if score > 0.75:  # Порог уверенности
            best_match = row["answer"]

    return best_match

async def save_to_db(question: str, answer: str):
    """Сохранение нового знания в БД"""
    embedding = model.encode(question).tolist()
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO knowledge_base (question, answer, embedding) VALUES ($1, $2, $3) ON CONFLICT (question) DO NOTHING",
        question, answer, embedding
    )
    await conn.close()

async def get_available_gpt_model():
    """Проверяем, какие модели OpenAI доступны"""
    openai.api_key = OPENAI_API_KEY
    try:
        response = openai.Model.list()
        available_models = [model["id"] for model in response["data"]]
        print(f"✅ Доступные модели OpenAI: {available_models}")

        if "gpt-4o" in available_models:
            return "gpt-4o"
        elif "gpt-4" in available_models:
            return "gpt-4"
        elif "gpt-3.5-turbo" in available_models:
            return "gpt-3.5-turbo"
        else:
            print("⚠ OpenAI не предоставляет доступные модели.")
            return None
    except Exception as e:
        print(f"⚠ Ошибка при получении списка моделей: {e}")
        return None

async def get_openai_answer(question: str):
    """Получение ответа от OpenAI, если в БД нет данных"""
    openai.api_key = OPENAI_API_KEY
    model_name = await get_available_gpt_model()
    
    if not model_name:
        return "⚠ OpenAI API недоступен или нет подходящих моделей."

    try:
        response = openai.ChatCompletion.create(
            model=model_name,
            messages=[{"role": "user", "content": question}],
            temperature=0.7
        )
        return response["choices"][0]["message"]["content"]
    except Exception as e:
        return f"⚠ Ошибка при запросе к OpenAI: {e}"

# ============ ОБРАБОТКА КОМАНД ============

@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer("Привет! Я RenderGuru. Задай мне любой вопрос по 3D-визуализации!")

@dp.message(Command("ask"))
async def ask_cmd(message: Message):
    question = message.text.replace("/ask", "").strip()
    if not question:
        await message.answer("❌ Вопрос не может быть пустым. Используй `/ask Твой вопрос`.")
        return

    answer = await search_in_db(question)
    if answer:
        await message.answer(answer)
    else:
        ai_answer = await get_openai_answer(question)
        await message.answer(ai_answer)
        await save_to_db(question, ai_answer)

@dp.message(Command("learn"))
async def learn_cmd(message: Message):
    await message.answer("Введите вопрос:")
    await bot.register_next_step_handler(message, get_question)

async def get_question(message: Message):
    question = message.text
    await message.answer("Введите ответ:")
    await bot.register_next_step_handler(message, get_answer, question)

async def get_answer(message: Message, question):
    answer = message.text
    await save_to_db(question, answer)
    await message.answer("✅ Новый ответ сохранён!")

# ============ ЗАПУСК БОТА НА POLLING ============

async def main():
    print("🚀 Бот RenderGuru запущен...")
    await init_db()
    try:
        await bot.delete_webhook(drop_pending_updates=True)  # ✅ Сбрасываем Webhook, если был
        await dp.start_polling(bot)
    except Exception as e:
        print(f"⚠ Ошибка запуска: {e}")

if __name__ == "__main__":
    asyncio.run(main())
