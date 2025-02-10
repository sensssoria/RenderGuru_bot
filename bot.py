import os
import asyncio
import logging
import asyncpg
from dotenv import load_dotenv
from transformers import pipeline
import torch

from aiogram import Bot, Dispatcher
from aiogram.types import (
    Message, 
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.filters.text import Text
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State

# ✅ Загружаем переменные окружения
load_dotenv()

# ✅ Получаем переменные окружения
TOKEN = os.getenv("API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN or not DATABASE_URL:
    raise ValueError("❌ Ошибка: API_TOKEN или DATABASE_URL не установлены в переменных окружения!")

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ✅ NLP-модель для семантического поиска
device = "cuda" if torch.cuda.is_available() else "cpu"
nlp_model = pipeline("feature-extraction", model="sentence-transformers/all-MiniLM-L6-v2", device=0 if device == "cuda" else -1)

# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С БД ============

async def init_db():
    """Создание таблиц, если их нет"""
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

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
    """)
    await conn.close()

async def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь админом"""
    conn = await asyncpg.connect(DATABASE_URL)
    result = await conn.fetchval("SELECT COUNT(*) FROM bot_admins WHERE user_id = $1", user_id)
    await conn.close()
    return result > 0

# ============ МЕНЮ ============

def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Спросить"), KeyboardButton(text="Учить")],
            [KeyboardButton(text="Помощь"), KeyboardButton(text="Администрирование")],
        ],
        resize_keyboard=True
    )

# ============ ОБРАБОТКА КОМАНД ============

@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "Привет! Я бот с продвинутым поиском и обучением.\n"
        "Выбирай действие на клавиатуре снизу или пиши вопросы в чат!",
        reply_markup=main_menu()
    )

@dp.message(Text("Помощь"))
async def help_cmd(message: Message):
    await message.answer(
        "🔹 **Доступные функции:**\n"
        " - Просто напиши вопрос, я найду ответ в БД 📚\n"
        " - Кнопка 'Учить' (только для админа, если public_learn=off) 🧑‍🏫\n"
        " - Кнопка 'Администрирование' (управление админами, настройками) ⚙️\n"
        " - `/add_admin <id>` — Добавить админа 👤\n"
        " - `/remove_admin <id>` — Удалить админа ❌\n"
        " - `/set_public_learn on/off` — открыть/закрыть обучение всем 🔧"
    )

# ============ ОБРАБОТКА КНОПОК ============

@dp.message(Text("Администрирование"))
async def admin_panel(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав доступа к администрированию.")
        return

    await message.answer(
        "🔧 Вы в разделе администрирования.\n"
        "Доступные команды:\n"
        " - `/add_admin <id>` — Добавить админа\n"
        " - `/remove_admin <id>` — Удалить админа\n"
        " - `/set_public_learn on/off` — Настроить обучение"
    )

@dp.message(Command("add_admin"))
async def add_admin(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав на добавление администраторов.")
        return

    try:
        user_id = int(message.text.split()[1])
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("INSERT INTO bot_admins (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
        await conn.close()
        await message.answer(f"✅ Пользователь {user_id} добавлен в администраторы.")
    except Exception:
        await message.answer("⚠️ Используйте: `/add_admin <id>`")

@dp.message(Command("remove_admin"))
async def remove_admin(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав на удаление администраторов.")
        return

    try:
        user_id = int(message.text.split()[1])
        conn = await asyncpg.connect(DATABASE_URL)
        await conn.execute("DELETE FROM bot_admins WHERE user_id = $1", user_id)
        await conn.close()
        await message.answer(f"✅ Пользователь {user_id} удалён из администраторов.")
    except Exception:
        await message.answer("⚠️ Используйте: `/remove_admin <id>`")

# ============ ЗАПУСК БОТА ============

async def main():
    print("Запуск бота...")
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
