import os
import asyncio
import logging
import sqlite3
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from sentence_transformers import SentenceTransformer
import openai

# Загружаем токены и ключи из переменных окружения
API_TOKEN = os.getenv("API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# NLP-модель для поиска по смыслу
nlp_model = SentenceTransformer("all-MiniLM-L6-v2")

# Функция для поиска похожего вопроса в БД
async def search_in_db(question: str):
    conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT answer FROM questions WHERE question = ?", (question,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

# Функция для сохранения нового вопроса-ответа
async def save_to_db(question: str, answer: str):
    conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO questions (question, answer) VALUES (?, ?)", (question, answer))
    conn.commit()
    conn.close()

# Обработчик команды /start
@dp.message(Command("start"))
async def send_welcome(message: types.Message):
    await message.answer("Привет! Я RenderGuru. Задай мне любой вопрос по 3D-визуализации!")

# Обработчик вопросов
@dp.message()
async def handle_question(message: types.Message):
    question = message.text.strip().lower()

    # Проверяем наличие ответа в базе
    answer = await search_in_db(question)
    
    if answer:
        await message.answer(answer)
    else:
        # Генерация ответа через OpenAI
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": question}],
            api_key=OPENAI_API_KEY
        )
        ai_answer = response["choices"][0]["message"]["content"]

        # Сохраняем ответ в базу
        await save_to_db(question, ai_answer)

        await message.answer(ai_answer)

# Главная функция
async def main():
    await dp.start_polling(bot)

# Запуск бота
if __name__ == "__main__":
    asyncio.run(main())
