import os
import asyncio
import asyncpg
import logging
import openai
import numpy as np
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command, Text
from sentence_transformers import SentenceTransformer

# ✅ Загружаем переменные окружения
load_dotenv()
TOKEN = os.getenv("API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not TOKEN or not DATABASE_URL or not OPENAI_API_KEY:
    raise ValueError("❌ Ошибка: API_TOKEN, DATABASE_URL или OPENAI_API_KEY не установлены!")

# ✅ Инициализация бота
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

        if score > best_score:
            best_score = score
            best_match = row["answer"]

    return best_match if best_score > 0.75 else None  # Порог уверенности

async def save_to_db(question: str, answer: str):
    """Сохранение нового знания в БД"""
    embedding = model.encode(question).tolist()
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(
        "INSERT INTO knowledge_base (question, answer, embedding) VALUES ($1, $2, $3) ON CONFLICT (question) DO NOTHING",
        question, answer, embedding
    )
    await conn.close()

async def get_openai_answer(question: str):
    """Получение ответа от OpenAI, если в БД нет данных"""
    openai.api_key = OPENAI_API_KEY
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": question}],
        temperature=0.7
    )
    return response["choices"][0]["message"]["content"]

# ============ ОБРАБОТКА КОМАНД ============

@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "Привет! Я бот-ассистент для 3D-визуализаторов. Спроси что угодно!",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="Спросить"), KeyboardButton(text="Учить")],
                [KeyboardButton(text="Помощь"), KeyboardButton(text="Администрирование")],
            ],
            resize_keyboard=True
        )
    )

@dp.message(Text("Спросить"))
async def ask_cmd(message: Message):
    question = message.text
    answer = await search_in_db(question)

    if answer:
        await message.answer(answer)
    else:
        ai_answer = await get_openai_answer(question)
        await message.answer(ai_answer)
        await save_to_db(question, ai_answer)

@dp.message(Text("Учить"))
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

# ============ ЗАПУСК БОТА ============

async def main():
    print("Запуск бота...")
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
