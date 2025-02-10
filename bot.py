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

# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С БД ============

async def init_db():
    """
    Автоматическое создание таблиц, если их нет.
    """
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

# ============ ПРОВЕРКА ПРАВ АДМИНА ============

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

@dp.message(Text("Спросить"))
async def ask_cmd(message: Message):
    await message.answer("Задавай вопрос! Я попробую найти ответ в базе.")

@dp.message(Text("Учить"))
async def teach_cmd(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        await message.answer("У вас нет прав для обучения бота.")
        return

    await message.answer("Ок, введи вопрос, который хочешь добавить/изменить.")
    await state.set_state(LearnStates.WAITING_QUESTION)

# ============ FSM ДЛЯ ОБУЧЕНИЯ ============

class LearnStates(StatesGroup):
    WAITING_QUESTION = State()
    WAITING_ANSWER = State()

@dp.message(LearnStates.WAITING_QUESTION)
async def fsm_question(message: Message, state: FSMContext):
    question = message.text.strip()
    await state.update_data(question=question)
    await message.answer("Введи ответ на этот вопрос:")
    await state.set_state(LearnStates.WAITING_ANSWER)

@dp.message(LearnStates.WAITING_ANSWER)
async def fsm_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    question = data["question"]
    answer = message.text.strip()

    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        INSERT INTO knowledge_base (question, question_tsv, answer)
        VALUES ($1, to_tsvector('simple', $1), $2)
        ON CONFLICT (question) DO UPDATE
        SET answer = EXCLUDED.answer,
            question_tsv = to_tsvector('simple', EXCLUDED.question)
    """, question, answer)
    await conn.close()

    await message.answer(f"Сохранено!\nВопрос: {question}\nОтвет: {answer}")
    await state.clear()

# ============ ЗАПУСК БОТА ============

async def main():
    print("Запуск бота...")
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
