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
# Для FSM нам нужен storage
dp = Dispatcher(storage=MemoryStorage())


# ============ БАЗОВАЯ ИНИЦИАЛИЗАЦИЯ БД (опционально) ============
async def init_db():
    """
    Если нужно, можно прописать тут CREATE TABLE ... 
    но предполагается, что таблицы уже созданы вручную через SQL.
    """
    conn = await asyncpg.connect(DATABASE_URL)
    # Можешь повторить create table, если хочешь
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


# ============ ФУНКЦИИ ДЛЯ РАБОТЫ С knowledge_base (FTS) ============

async def fts_insert_or_update(question: str, answer: str):
    """
    Записываем/обновляем в таблицу knowledge_base
    question_tsv = to_tsvector('simple', question)
    """
    query = """
    INSERT INTO knowledge_base (question, question_tsv, answer)
    VALUES ($1, to_tsvector('simple', $1), $2)
    ON CONFLICT (question) DO UPDATE
        SET answer = EXCLUDED.answer,
            question_tsv = to_tsvector('simple', EXCLUDED.question)
    """
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute(query, question, answer)
    await conn.close()

async def question_exists(question: str) -> bool:
    conn = await asyncpg.connect(DATABASE_URL)
    row = await conn.fetchrow("SELECT 1 FROM knowledge_base WHERE question=$1", question)
    await conn.close()
    return bool(row)

async def fts_find_candidates(user_query: str, limit=5):
    """
    Ищем похожие вопросы через FTS
    Возвращаем [(question, answer, rank), ...]
    """
    tokens = []
    for w in user_query.lower().split():
        w = w.strip("?!.,;:\"'")
        if w:
            tokens.append(w)
    if not tokens:
        return []

    tsquery_str = " & ".join(tokens)

    conn = await asyncpg.connect(DATABASE_URL)
    rows = await conn.fetch(f"""
        SELECT question, answer,
               ts_rank_cd(question_tsv, to_tsquery('simple', $1)) as rank
        FROM knowledge_base
        WHERE question_tsv @@ to_tsquery('simple', $1)
        ORDER BY rank DESC
        LIMIT {limit}
    """, tsquery_str)
    await conn.close()

    results = []
    for r in rows:
        results.append((r["question"], r["answer"], float(r["rank"])))
    return results


# ============ FSM ДЛЯ МНОГОШАГОВОГО ОБУЧЕНИЯ ============

class LearnStates(StatesGroup):
    WAITING_QUESTION = State()
    CONFIRM_OVERWRITE = State()
    WAITING_ANSWER = State()


# ============ REPLY-КЛАВИАТУРА (НИЖНЕЕ МЕНЮ) ============

def main_menu():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("Спросить"))
    kb.add(KeyboardButton("Учить"))
    kb.add(KeyboardButton("Помощь"))
    kb.add(KeyboardButton("Администрирование"))  # для add_admin, remove_admin, public_learn
    return kb


# ============ ОБРАБОТЧИК /start ============

@dp.message(Command("start"))
async def start_cmd(message: Message):
    await message.answer(
        "Привет! Я бот с продвинутым поиском и обучением.\n"
        "Выбирай действие на клавиатуре снизу или пиши вопросы в чат!",
        reply_markup=main_menu()
    )


# ============ ОБРАБОТКА КНОПОК 'Спросить', 'Учить', 'Помощь', 'Администрирование' ============

@dp.message(Text("Помощь"))
async def help_cmd(message: Message):
    txt = (
        "Доступные функции:\n"
        " - Просто напиши вопрос, я найду ответ в БД (FTS)\n"
        " - Кнопка 'Учить' (только для админа, если public_learn=off)\n"
        " - Кнопка 'Администрирование' (управление админами, настройками)\n"
        " - /add_admin <id>  — Добавить админа\n"
        " - /remove_admin <id> — Удалить админа\n"
        " - /set_public_learn on/off — открыть/закрыть обучение всем\n"
    )
    await message.answer(txt)

@dp.message(Text("Спросить"))
async def ask_cmd(message: Message):
    await message.answer("Задавай вопрос! Я попробую найти ответ в базе.")

@dp.message(Text("Учить"))
async def teach_cmd(message: Message, state: FSMContext):
    # Смотрим, включён ли public_learn
    public_learn = await is_public_learn_enabled()
    user_id = message.from_user.id

    if public_learn:
        # Все могут учить
        pass
    else:
        # Только админ
        if not await is_admin(user_id):
            await message.answer("У вас нет прав для обучения бота.")
            return

    # Начинаем FSM: ждём вопрос
    await message.answer("Ок, введи вопрос, который хочешь добавить/изменить.")
    await state.set_state(LearnStates.WAITING_QUESTION)

@dp.message(Text("Администрирование"))
async def admin_menu(message: Message):
    """
    Покажем кнопки для управления (добавить/удалить админа, публичное обучение и т.д.)
    Но проверим, что это супер-админ
    """
    if not await is_superadmin(message.from_user.id):
        await message.answer("Вы не супер-админ.")
        return

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("Добавить админа (команда)", callback_data="info_addadmin"))
    kb.add(InlineKeyboardButton("Удалить админа (команда)", callback_data="info_removeadmin"))
    kb.add(InlineKeyboardButton("Управление public_learn", callback_data="info_publiclearn"))

    await message.answer("Администрирование:", reply_markup=kb)


# ============ FSM: обработка шагов обучения ============

@dp.message(LearnStates.WAITING_QUESTION)
async def fsm_question(message: Message, state: FSMContext):
    question = message.text.strip()
    await state.update_data(question=question)

    # Проверка, есть ли уже такой вопрос
    exists = await question_exists(question)
    if exists:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("Да, перезаписать", callback_data="overwrite_yes"))
        kb.add(InlineKeyboardButton("Нет, отмена", callback_data="overwrite_no"))

        await message.answer(
            f"Такой вопрос уже есть в базе:\n'{question}'\nПерезаписать?",
            reply_markup=kb
        )
        await state.set_state(LearnStates.CONFIRM_OVERWRITE)
    else:
        await message.answer("Введи ответ на этот вопрос:")
        await state.set_state(LearnStates.WAITING_ANSWER)

@dp.callback_query(LearnStates.CONFIRM_OVERWRITE)
async def fsm_confirm_overwrite(call: CallbackQuery, state: FSMContext):
    if call.data == "overwrite_yes":
        await call.message.answer("Ок, введи новый ответ:")
        await state.set_state(LearnStates.WAITING_ANSWER)
    else:
        # overwrite_no
        await call.message.answer("Отмена сохранения.")
        await state.clear()
    await call.answer()

@dp.message(LearnStates.WAITING_ANSWER)
async def fsm_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    question = data["question"]
    answer = message.text.strip()

    await fts_insert_or_update(question, answer)
    await message.answer(f"Сохранено!\nВопрос: {question}\nОтвет: {answer}")
    await state.clear()


# ============ ОБРАБОТКА КОМАНД add_admin, remove_admin, set_public_learn ============

@dp.message(Command("add_admin"))
async def cmd_add_admin(message: Message):
    # Проверяем, что вызывающий - супер-админ
    if not await is_superadmin(message.from_user.id):
        await message.answer("Вы не супер-админ.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /add_admin <user_id>")
        return
    try:
        new_admin_id = int(parts[1])
    except ValueError:
        await message.answer("user_id должно быть числом!")
        return
    
    await add_admin(new_admin_id, "admin")
    await message.answer(f"Пользователь {new_admin_id} теперь админ!")

@dp.message(Command("remove_admin"))
async def cmd_remove_admin(message: Message):
    # Проверяем, что вызывающий - супер-админ
    if not await is_superadmin(message.from_user.id):
        await message.answer("Вы не супер-админ.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /remove_admin <user_id>")
        return
    try:
        rm_id = int(parts[1])
    except ValueError:
        await message.answer("user_id должно быть числом!")
        return
    
    await remove_admin(rm_id)
    await message.answer(f"Пользователь {rm_id} удалён из админов (если был там).")

@dp.message(Command("set_public_learn"))
async def cmd_set_public_learn(message: Message):
    # Только супер-админ
    if not await is_superadmin(message.from_user.id):
        await message.answer("Вы не супер-админ.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /set_public_learn on|off")
        return
    
    mode = parts[1].lower()
    if mode not in ["on", "off"]:
        await message.answer("Используй on или off.")
        return
    
    new_val = (mode == "on")
    await set_public_learn(new_val)
    await message.answer(f"public_learn = {mode.upper()}")


# ============ ОБРАБОТКА CALLBACK (из меню админки) ============

@dp.callback_query()
async def callback_handler(call: CallbackQuery):
    data = call.data
    if data == "info_addadmin":
        await call.message.answer("Используй команду:\n/add_admin <user_id>")
        await call.answer()
    elif data == "info_removeadmin":
        await call.message.answer("Используй команду:\n/remove_admin <user_id>")
        await call.answer()
    elif data == "info_publiclearn":
        await call.message.answer(
            "Используй команду:\n"
            "/set_public_learn on  - открыть всем\n"
            "/set_public_learn off - только админы"
        )
        await call.answer()

    elif data.startswith("choose_answer::"):
        # Когда пользователь выбирает один из вариантов ответа
        answer = data.split("::", 1)[1]
        await call.message.answer(f"Вот ответ:\n{answer}")
        await call.message.edit_reply_markup()  # убираем кнопки
        await call.answer()
    else:
        await call.answer("Неизвестная команда кнопки")


# ============ ХЕНДЛЕР ВСЕХ ПРОЧИХ СООБЩЕНИЙ (ПОИСК) ============

@dp.message()
async def text_query(message: Message):
    user_text = message.text.strip()
    if not user_text:
        return

    # Ищем в БД
    results = await fts_find_candidates(user_text)
    if not results:
        # Заглушка GPT
        await message.answer("(Заглушка) Ничего не найдено или GPT недоступен...")
    else:
        if len(results) == 1:
            q, a, rank = results[0]
            await message.answer(f"Из базы (rank={rank:.2f}):\n{a}")
        else:
            # Несколько совпадений - inline-кнопки
            kb_builder = InlineKeyboardBuilder()
            for q, a, rank in results:
                kb_builder.button(
                    text=f"{q} (rank={rank:.2f})",
                    callback_data=f"choose_answer::{a}"
                )
                kb_builder.adjust(1)
            await message.answer(
                "Найдено несколько возможных ответов. Выбери подходящий:",
                reply_markup=kb_builder.as_markup()
            )


# ============ ЗАПУСК БОТА ============

async def main():
    print("Запуск бота...")
    await init_db()  # вдруг нужно
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
