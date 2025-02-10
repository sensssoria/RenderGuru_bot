import os
import asyncio
import logging
import asyncpg
from dotenv import load_dotenv
from transformers import pipeline
import torch  # Добавлено для поддержки NLP-модели

from aiogram import Bot, Dispatcher
from aiogram.types import (
    Message, 
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
)
from aiogram.filters import Command
from aiogram.filters.text import Text
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ✅ Загружаем переменные окружения (если .env есть)
load_dotenv()

# ✅ Получаем переменные окружения с резервным значением
TOKEN = os.getenv("API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    print("⚠️ ОШИБКА: Нет API_TOKEN в переменных окружения!")
    exit(1)
if not DATABASE_URL:
    print("⚠️ ОШИБКА: Нет DATABASE_URL в переменных окружения!")
    exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ✅ Инициализируем NLP-модель (Используем Sentence Transformers)
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

# ============ МЕНЮ ============


def main_menu() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Спросить"), KeyboardButton(text="Учить")],
            [KeyboardButton(text="Помощь"), KeyboardButton(text="Администрирование")],
        ],
        resize_keyboard=True
    )
    return kb

# ============ ОБРАБОТЧИК /start ============

@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "Привет! Я бот с продвинутым поиском и обучением.\n"
        "Выбирай действие на клавиатуре снизу или пиши вопросы в чат!",
        reply_markup=main_menu()
    )

# ============ ОБРАБОТКА КНОПОК ============

@dp.message(Text("Помощь"))
async def help_cmd(message: Message):
    await message.answer(
        "Доступные функции:\n"
        " - Просто напиши вопрос, я найду ответ в БД (FTS)\n"
        " - Кнопка 'Учить' (только для админа, если public_learn=off)\n"
        " - Кнопка 'Администрирование' (управление админами, настройками)\n"
        " - /add_admin <id>  — Добавить админа\n"
        " - /remove_admin <id> — Удалить админа\n"
        " - /set_public_learn on/off — открыть/закрыть обучение всем\n"
    )

# ============ ЗАПУСК БОТА ============

async def main():
    print("Запуск бота...")
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
