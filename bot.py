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
from aiogram.utils.keyboard import InlineKeyboardBuilder

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

# ============ АВТОМАТИЧЕСКОЕ СОЗДАНИЕ ТАБЛИЦ ============
async def init_db():
    """
    Создаёт необходимые таблицы, если их нет.
    """
    queries = [
        """
        CREATE TABLE IF NOT EXISTS bot_admins (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL UNIQUE,
            role TEXT NOT NULL DEFAULT 'admin'
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS knowledge_base (
            id BIGSERIAL PRIMARY KEY,
            question TEXT NOT NULL UNIQUE,
            question_tsv tsvector NOT NULL,
            answer TEXT NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS user_queries (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            query TEXT NOT NULL,
            response TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT now()
        );
        """
    ]

    conn = await asyncpg.connect(DATABASE_URL)
    for query in queries:
        await conn.execute(query)
    await conn.close()

# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С bot_settings (public_learn) ============
async def is_public_learn_enabled() -> bool:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT value FROM bot_settings WHERE key='public_learn'")
    await conn.close()
    if not row:
        return False  # По умолчанию закрыто
    return (row["value"] == "true")

async def set_public_learn(new_value: bool):
    conn = await asyncpg.connect(DATABASE_URL)
    val_str = "true" if new_value else "false"
    await conn.execute("""
        INSERT INTO bot_settings(key, value) VALUES ('public_learn', $1)
        ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
    """, val_str)
    await conn.close()

# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С bot_admins ============
async def is_superadmin(user_id: int) -> bool:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow(
        "SELECT 1 FROM bot_admins WHERE user_id=$1 AND role='superadmin'",
        user_id
    )
    await conn.close()
    return bool(row)

async def is_admin(user_id: int) -> bool:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT 1 FROM bot_admins WHERE user_id=$1", user_id)
    await conn.close()
    return bool(row)

async def add_admin(user_id: int, role: str = "admin"):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        INSERT INTO bot_admins(user_id, role) VALUES ($1, $2)
        ON CONFLICT (user_id) DO NOTHING
    """, user_id, role)
    await conn.close()

async def remove_admin(user_id: int):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("DELETE FROM bot_admins WHERE user_id=$1", user_id)
    await conn.close()

# ============ ОСТАЛЬНЫЕ ФУНКЦИИ, FSM И ЗАПУСК БОТА (без изменений) ============
# Код оставлен без изменений, за исключением уже существующих функций
# инициализации и обработки данных, добавленных ранее.

async def main():
    print("Запуск бота...")
    await init_db()  # Автоматическое создание таблиц
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
