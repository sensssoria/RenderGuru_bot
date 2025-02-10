import os
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup
from aiogram.filters import Command
import asyncpg
from typing import Optional
from transformers import pipeline

# Настройки бота
API_TOKEN = os.getenv("API_TOKEN", "ВАШ_ТОКЕН_БОТА")
DATABASE_URL = os.getenv("DATABASE_URL", "ВАШ_АДРЕС_БАЗЫ_ДАННЫХ")

# NLP модель для анализа текста
nlp_model = pipeline("feature-extraction", model="sentence-transformers/all-MiniLM-L6-v2")

# Проверка переменных окружения
if API_TOKEN == "ВАШ_ТОКЕН_БОТА" or DATABASE_URL == "ВАШ_АДРЕС_БАЗЫ_ДАННЫХ":
    print("⚠️ Пожалуйста, проверьте настройки: API_TOKEN и DATABASE_URL!")
    print("Для использования переменных окружения настройте их в Railway или локально.")
    exit(1)

# Подключение к базе данных
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS bot_admins (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL UNIQUE,
        role TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS knowledge_base (
        id SERIAL PRIMARY KEY,
        query TEXT NOT NULL,
        response TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        question_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('russian', query)) STORED
    );
    CREATE TABLE IF NOT EXISTS user_queries (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        query TEXT,
        created_at TIMESTAMP DEFAULT NOW()
    );
    """)
    await conn.close()

# Основное меню
def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Спросить"))
    kb.add(KeyboardButton("Учить"))
    kb.add(KeyboardButton("Помощь"))
    kb.add(KeyboardButton("Администрирование"))
    return kb

# Обработчик команды /start
async def start_cmd(message: Message):
    await message.answer(
        "Привет! Я бот с продвинутым поиском и обучением.\n"
        "Выбирай действие на клавиатуре снизу или пиши вопросы в чат!",
        reply_markup=main_menu()
    )

# Обработчик команды /help
async def help_cmd(message: Message):
    await message.answer(
        "Доступные функции:\n"
        "- Просто напиши вопрос, я найду ответ в БД (FTS)\n"
        "- Кнопка 'Учить' (только для админа, если public_learn=off)\n"
        "- Кнопка 'Администрирование' (управление админами, настройками)\n"
        "- /add_admin <id>  — Добавить админа\n"
        "- /remove_admin <id> — Удалить админа\n"
        "- /set_public_learn on/off — открыть/закрыть обучение всем"
    )

# Обработчик кнопки "Спросить"
async def handle_question(message: Message):
    query = message.text.strip().lower()
    conn = await asyncpg.connect(DATABASE_URL)
    result = await conn.fetch("""
    SELECT query, response, ts_rank_cd(question_tsv, plainto_tsquery('russian', $1)) AS rank
    FROM knowledge_base
    WHERE question_tsv @@ plainto_tsquery('russian', $1)
    ORDER BY rank DESC
    LIMIT 1;
    """, query)
    await conn.close()

    if result:
        answer = result[0]["response"]
        await message.answer(answer)
    else:
        await message.answer("(Заглушка) GPT недоступен, попробуйте позже.")

# Обработчик кнопки "Учить"
async def handle_teach(message: Message):
    await message.answer("Ок, введи вопрос, который хочешь добавить/изменить.")
    # Следующая логика обрабатывает процесс обучения

# Обработчик кнопки "Администрирование"
async def handle_admin(message: Message):
    user_id = message.from_user.id
    conn = await asyncpg.connect(DATABASE_URL)
    is_admin = await conn.fetchval("SELECT 1 FROM bot_admins WHERE user_id = $1", user_id)
    await conn.close()

    if is_admin:
        await message.answer(
            "Вы в разделе администрирования.\n"
            "Доступные команды:\n"
            "- /add_admin <id>  — Добавить админа\n"
            "- /remove_admin <id> — Удалить админа\n"
            "- /set_public_learn on/off — открыть/закрыть обучение всем"
        )
    else:
        await message.answer("У вас нет доступа к разделу администрирования.")

# Инициализация и запуск бота
async def main():
    bot = Bot(token=API_TOKEN)
    dp = Dispatcher()

    # Инициализация базы данных
    await init_db()

    # Регистрация обработчиков
    dp.message.register(start_cmd, Command("start"))
    dp.message.register(help_cmd, Command("help"))
    dp.message.register(handle_question, F.text.contains("Спросить"))
    dp.message.register(handle_teach, F.text.contains("Учить"))
    dp.message.register(handle_admin, F.text.contains("Администрирование"))

    # Запуск бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
