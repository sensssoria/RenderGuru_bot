import os
import asyncio
import openai
import logging
import sqlite3
import numpy as np
from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sentence_transformers import SentenceTransformer

# Загрузка API-ключей
API_TOKEN = os.getenv("API_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL", "bot_data.db")

if not API_TOKEN or not OPENAI_API_KEY:
    raise ValueError("❌ Ошибка: API_TOKEN и OPENAI_API_KEY должны быть заданы в Railway Variables!")

# Настройка бота
bot = Bot(token=API_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()
openai.api_key = OPENAI_API_KEY

# NLP-модель для смыслового сравнения
model = SentenceTransformer("paraphrase-MiniLM-L6-v2")

# Фильтр тематики 3D
allowed_keywords = ["3D", "рендер", "визуализация", "моделирование", "текстуры", "свет", "сцена", "материалы"]

async def is_relevant_question(question: str):
    """Проверяет, относится ли вопрос к 3D"""
    return any(word.lower() in question.lower() for word in allowed_keywords)

# Инициализация базы с векторным поиском
def init_db():
    conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT UNIQUE,
            embedding BLOB,
            answer TEXT
        )
    ''')
    conn.commit()
    conn.close()

async def search_in_db(question: str):
    """Поиск по смыслу (векторное сравнение)"""
    question_embedding = model.encode(question)
    conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT question, embedding, answer FROM questions")
    rows = cursor.fetchall()
    conn.close()

    best_match = None
    best_score = -1

    for stored_question, embedding_blob, answer in rows:
        stored_embedding = np.frombuffer(embedding_blob, dtype=np.float32)
        score = np.dot(question_embedding, stored_embedding) / (np.linalg.norm(question_embedding) * np.linalg.norm(stored_embedding))

        if score > best_score:
            best_score = score
            best_match = (stored_question, answer)

    if best_match and best_score > 0.85:  # Минимальный порог похожести
        return best_match[1]
    return None

async def save_to_db(question: str, answer: str):
    """Сохранение нового вопроса с его вектором"""
    question_embedding = model.encode(question).astype(np.float32).tobytes()
    conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO questions (question, embedding, answer) VALUES (?, ?, ?)", (question, question_embedding, answer))
    conn.commit()
    conn.close()

async def get_openai_answer(question: str):
    """Получение ответа от OpenAI"""
    if not await is_relevant_question(question):
        return "⚠ Я отвечаю только на вопросы по 3D-визуализации."

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Ты эксперт по 3D-визуализации, моделированию и рендерингу. Отвечай только на вопросы по этим темам."},
                {"role": "user", "content": question}
            ],
            temperature=0.7
        )
        return response["choices"][0]["message"]["content"]
    except Exception as e:
        return f"⚠ Ошибка OpenAI: {e}"

# Обработчик /start
@dp.message(Command("start"))
async def start_handler(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Спросить", callback_data="ask")],
            [InlineKeyboardButton(text="Учить", callback_data="learn")],
            [InlineKeyboardButton(text="Помощь", callback_data="help")]
        ]
    )
    await message.answer("👋 Привет! Я RenderGuru. Задай мне любой вопрос по 3D-визуализации!", reply_markup=keyboard)

# Обработчик кнопок
@dp.callback_query()
async def callback_handler(callback: types.CallbackQuery):
    if callback.data == "ask":
        await callback.message.answer("Введите ваш вопрос:")
    elif callback.data == "learn":
        await callback.message.answer("Вы можете научить меня новому! Просто напишите вопрос и ответ.")
    elif callback.data == "help":
        await callback.message.answer("Я - бот по 3D-визуализации. Задайте мне вопрос или используйте кнопки.")
    await callback.answer()

# Обработчик текстовых сообщений
@dp.message()
async def handle_text(message: types.Message):
    """Обрабатывает текстовые сообщения"""
    question = message.text.strip()
    if not question:
        return

    # Поиск по смыслу в базе
    answer = await search_in_db(question)
    if answer:
        await message.answer(answer)
    else:
        ai_answer = await get_openai_answer(question)
        await message.answer(ai_answer)
        await save_to_db(question, ai_answer)

# Запуск Polling
async def main():
    """Запуск бота"""
    logging.basicConfig(level=logging.INFO)
    print("🚀 Бот RenderGuru запущен...")
    init_db()  # Инициализация базы
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
