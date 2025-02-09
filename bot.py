import os
import asyncio
import logging

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.types import Message
from aiogram.filters import Command

# Если используешь dotenv, можешь подключить:
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Читаем переменные окружения
TOKEN = os.getenv("TOKEN")               # Токен бота
DATABASE_URL = os.getenv("DATABASE_URL") # Строка подключения к PostgreSQL

if not TOKEN:
    print("ОШИБКА: Нет токена бота (TOKEN)!")
    exit(1)
if not DATABASE_URL:
    print("ОШИБКА: Нет строки подключения к БД (DATABASE_URL)!")
    exit(1)

logging.basicConfig(level=logging.INFO)

# Создаём бота и диспетчер aiogram 3.x
bot = Bot(token=TOKEN)
dp = Dispatcher()

# 1. При запуске создаём (если нет) таблицу для хранения знаний
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id SERIAL PRIMARY KEY,
            question TEXT UNIQUE NOT NULL,
            answer TEXT NOT NULL
        )
    """)
    await conn.close()
    print("✅ Таблица knowledge_base проверена/создана.")

# 2. Функция получить ответ из БД
async def get_answer_db(question: str) -> str | None:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT answer FROM knowledge_base WHERE question = $1", question)
    await conn.close()
    if row:
        return row["answer"]
    return None

# 3. Функция сохранить вопрос/ответ в БД (команда /learn)
async def store_answer_db(question: str, answer: str):
    conn = await asyncpg.connect(DATABASE_URL)
    # ON CONFLICT (question) DO UPDATE - чтобы перезаписать ответ, если вопрос уже есть
    await conn.execute("""
        INSERT INTO knowledge_base(question, answer)
        VALUES ($1, $2)
        ON CONFLICT (question) DO UPDATE SET answer = EXCLUDED.answer
    """, question, answer)
    await conn.close()

# Команда /start - приветствие
@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer("Привет! Я гибридный бот. Умею хранить ответы в БД, и могу отвечать заглушкой вместо GPT.")

# Команда /learn - чтобы бот «учился»
#
# Формат: 
#   /learn вопрос::ответ
#
# Пример:
#   /learn Как настроить свет?::Включите лампу, поставьте CoronaSun
#
@dp.message(Command("learn"))
async def learn_cmd(message: Message):
    # Убираем "/learn " из текста
    text = message.text.removeprefix("/learn").strip()
    if "::" not in text:
        await message.answer("Используй формат: /learn вопрос::ответ")
        return
    
    # Разделяем по "::"
    parts = text.split("::", 1)
    question = parts[0].strip()
    answer   = parts[1].strip()

    # Сохраняем в базу
    await store_answer_db(question, answer)
    await message.answer(f"Запомнил ответ для вопроса:\n\n{question}\n\n> {answer}")

# Обработчик любого другого сообщения
@dp.message()
async def fallback_handler(message: Message):
    user_text = message.text.strip()
    if not user_text:
        return  # Пустое сообщение игнорируем

    # 1. Ищем ответ в базе
    answer_in_db = await get_answer_db(user_text)
    if answer_in_db:
        # Если нашли - отвечаем
        await message.answer(f"Из базы:\n{answer_in_db}")
    else:
        # 2. Иначе выдаём «заглушку GPT», пока нет оплаченного API
        fake_gpt_answer = "(Заглушка) GPT недоступен, оплатите квоту чтобы получить умный ответ."
        await message.answer(fake_gpt_answer)

# Главная функция запуска бота
async def main():
    print(f"✅ Бот запускается с токеном: {TOKEN[:10]}... (скрыто)")
    
    # Инициализируем БД (создаём таблицу, если нет)
    await init_db()
    
    # Запускаем поллинг (без вебхуков)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
