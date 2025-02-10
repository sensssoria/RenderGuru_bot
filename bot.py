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
