import os
import asyncio
import logging
import asyncpg

from aiogram import Bot, Dispatcher
from aiogram.types import (
    Message, 
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)
from aiogram.filters import Command, Text
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State

# Если у тебя есть .env - подключим dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    print("ОШИБКА: Нет токена бота!")
    exit(1)
if not DATABASE_URL:
    print("ОШИБКА: Нет строки подключения к PostgreSQL!")
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

SUPERADMIN_ID = 400849565  # Твой Telegram ID

# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С БД ============

async def init_db():
    """
    Автоматическое создание таблиц, если их нет.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_admins (
            user_id BIGINT PRIMARY KEY,
            role TEXT NOT NULL DEFAULT 'admin'
        );

        CREATE TABLE IF NOT EXISTS knowledge_base (
            id SERIAL PRIMARY KEY,
            question TEXT UNIQUE NOT NULL,
            question_tsv tsvector,
            answer TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS question_tsv_idx ON knowledge_base USING GIN (question_tsv);

        CREATE TABLE IF NOT EXISTS user_queries (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            query TEXT NOT NULL,
            response TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Добавляем супер-админа, если его нет
    await conn.execute(
        "INSERT INTO bot_admins (user_id, role) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
        SUPERADMIN_ID, 'superadmin'
    )
    await conn.close()

# ============ МЕНЮ ============

def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
        [KeyboardButton("Спросить")],
        [KeyboardButton("Учить")],
        [KeyboardButton("Помощь")],
        [KeyboardButton("Администрирование")]
    ])
    return kb

# ============ ОБРАБОТЧИК /start ============

@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "Привет! Я бот с продвинутым поиском и обучением.\n"
        "Выбирай действие на клавиатуре снизу или пиши вопросы в чат!",
        reply_markup=main_menu()
    )

# ============ ЗАПУСК БОТА ============

async def main():
    print("Запуск бота...")
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
