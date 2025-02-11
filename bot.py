import os
import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message
from aiogram.utils import executor
from sentence_transformers import SentenceTransformer, util
import openai

# Загрузка переменных окружения
API_TOKEN = os.getenv("API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "questions.db")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)

# Инициализация NLP модели
model = SentenceTransformer("all-MiniLM-L6-v2")

def init_db():
    conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT UNIQUE,
            answer TEXT
        )
    ''')
    conn.commit()
    conn.close()

async def search_in_db(question: str):
    """Поиск ответа в базе данных с использованием NLP"""
    conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT question, answer FROM questions")
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return None
    
    questions = [row[0] for row in rows]
    embeddings = model.encode(questions, convert_to_tensor=True)
    query_embedding = model.encode(question, convert_to_tensor=True)
    
    scores = util.pytorch_cos_sim(query_embedding, embeddings)[0]
    best_match_idx = scores.argmax().item()
    
    if scores[best_match_idx] > 0.75:  # Если совпадение выше порога
        return rows[best_match_idx][1]
    return None

async def save_to_db(question: str, answer: str):
    """Сохранение вопроса-ответа в базу данных"""
    conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO questions (question, answer) VALUES (?, ?)", (question, answer))
    conn.commit()
    conn.close()

async def get_ai_response(question: str):
    """Запрос к OpenAI GPT-4"""
    openai.api_key = OPENAI_API_KEY
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Ты RenderGuru – эксперт в 3D-визуализации."},
            {"role": "user", "content": question}
        ]
    )
    return response["choices"][0]["message"]["content"].strip()

@dp.message_handler(commands=['start'])
async def start_command(message: Message):
    await message.answer("Привет! Я RenderGuru. Задай мне любой вопрос по 3D-визуализации!")

@dp.message_handler()
async def handle_message(message: Message):
    logging.info(f"Получено сообщение: {message.text}")
    
    answer = await search_in_db(message.text)
    if answer:
        await message.answer(answer)
        return
    
    ai_answer = await get_ai_response(message.text)
    await save_to_db(message.text, ai_answer)
    await message.answer(ai_answer)

if __name__ == "__main__":
    init_db()
    logging.info("🚀 Бот RenderGuru запущен...")
    executor.start_polling(dp, skip_updates=True)
