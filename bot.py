import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup
from aiogram.filters import Command
import asyncpg
from typing import Optional
from transformers import pipeline

# Настройки бота
API_TOKEN = "---"
DATABASE_URL = "---"

# NLP модель для анализа текста
nlp_model = pipeline("feature-extraction", model="sentence-transformers/all-mpnet-base-v2")

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Главная клавиатура
def main_menu():
    return ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton("Спросить"),
        KeyboardButton("Учить"),
        KeyboardButton("Помощь"),
        KeyboardButton("Администрирование")
    )

# Подключение к базе данных
async def init_db():
    conn = await asyncpg.connect(DATABASE_URL)

    # Создание таблиц, если их нет
    await conn.execute("""
    CREATE TABLE IF NOT EXISTS bot_admins (
        id SERIAL PRIMARY KEY,
        user_id BIGINT UNIQUE,
        role TEXT
    );
    CREATE TABLE IF NOT EXISTS knowledge_base (
        id SERIAL PRIMARY KEY,
        query TEXT,
        response TEXT,
        question_tsv tsvector
    );
    CREATE TABLE IF NOT EXISTS user_queries (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        query TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS settings (
        id SERIAL PRIMARY KEY,
        public_learn BOOLEAN DEFAULT FALSE
    );
    INSERT INTO settings (id, public_learn) VALUES (1, FALSE) ON CONFLICT (id) DO NOTHING;
    """)

    await conn.close()

# Обработчик команды /start
@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer("Привет! Я бот с продвинутым поиском и обучением.\nВыбирай действие на клавиатуре снизу или пиши вопросы в чат!", reply_markup=main_menu())

# Обработчик кнопки "Спросить"
@dp.message(F.text == "Спросить")
async def ask_question(message: Message):
    await message.answer("Задавай вопрос! Я попробую найти ответ в базе.")

@dp.message()
async def process_question(message: Message):
    user_query = message.text.strip()

    conn = await asyncpg.connect(DATABASE_URL)

    # Используем to_tsquery для поиска по базе
    results = await conn.fetch(
        """
        SELECT query, response, ts_rank_cd(question_tsv, to_tsquery($1)) AS rank
        FROM knowledge_base
        WHERE question_tsv @@ to_tsquery($1)
        ORDER BY rank DESC
        LIMIT 1;
        """,
        user_query.replace(" ", " & ")
    )

    if results:
        best_match = results[0]
        await message.answer(f"Ответ: {best_match['response']}")
    else:
        # NLP анализ запроса как резервный вариант
        user_vector = nlp_model(user_query)[0][0]
        kb_results = await conn.fetch("SELECT id, query, response FROM knowledge_base")

        max_similarity = 0
        best_response = None
        for row in kb_results:
            kb_vector = nlp_model(row['query'])[0][0]
            similarity = sum([a * b for a, b in zip(user_vector, kb_vector)])
            if similarity > max_similarity:
                max_similarity = similarity
                best_response = row['response']

        if best_response:
            await message.answer(f"Ответ: {best_response}")
        else:
            # Сохранение вопроса без ответа
            await conn.execute(
                "INSERT INTO user_queries (user_id, query) VALUES ($1, $2)",
                message.from_user.id, user_query
            )
            await message.answer("К сожалению, я не нашёл ответа. Администратор добавит его позже.")

    await conn.close()

# Обработчик кнопки "Учить"
@dp.message(F.text == "Учить")
async def teach_question(message: Message):
    conn = await asyncpg.connect(DATABASE_URL)

    # Проверяем, является ли пользователь администратором
    is_admin = await conn.fetchval("SELECT COUNT(*) FROM bot_admins WHERE user_id = $1", message.from_user.id)
    if not is_admin:
        await conn.close()
        await message.answer("У вас нет прав на обучение бота.")
        return

    await message.answer("Ок, введи вопрос, который хочешь добавить/изменить.")

    @dp.message()
    async def teach_process_question(message: Message):
        question = message.text.strip()
        await message.answer("Введи ответ на этот вопрос:")

        @dp.message()
        async def teach_process_answer(message: Message):
            answer = message.text.strip()
            await conn.execute(
                """
                INSERT INTO knowledge_base (query, response, question_tsv)
                VALUES ($1, $2, to_tsvector($1))
                ON CONFLICT (query) DO UPDATE SET response = $2, question_tsv = to_tsvector($1);
                """,
                question, answer
            )
            await message.answer(f"Сохранено!\nВопрос: {question}\nОтвет: {answer}")
            await conn.close()

# Обработчик кнопки "Администрирование"
@dp.message(F.text == "Администрирование")
async def admin_panel(message: Message):
    conn = await asyncpg.connect(DATABASE_URL)
    is_admin = await conn.fetchval("SELECT COUNT(*) FROM bot_admins WHERE user_id = $1", message.from_user.id)
    await conn.close()

    if not is_admin:
        await message.answer("У вас нет доступа к этому разделу.")
        return

    admin_kb = ReplyKeyboardMarkup(resize_keyboard=True).add(
        KeyboardButton("Добавить админа"),
        KeyboardButton("Удалить админа"),
        KeyboardButton("Включить публичное обучение"),
        KeyboardButton("Выключить публичное обучение"),
        KeyboardButton("Назад")
    )
    await message.answer("Вы в разделе администрирования. Выберите действие:", reply_markup=admin_kb)

# Запуск бота
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
