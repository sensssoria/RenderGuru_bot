import os
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, JSON, func, select
from sentence_transformers import SentenceTransformer
import openai

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
API_TOKEN = os.getenv("API_TOKEN")
if not API_TOKEN:
    raise ValueError("No API_TOKEN provided in environment")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("No DATABASE_URL provided in environment")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Настройка базы данных
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# Модели базы данных
class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    id = Column(Integer, primary_key=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    created_by = Column(Integer)

class BotAdmin(Base):
    __tablename__ = "bot_admins"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False)
    username = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())

class BotSettings(Base):
    __tablename__ = "bot_settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(255), unique=True, nullable=False)
    value = Column(JSON)
    updated_at = Column(DateTime, onupdate=func.now())

class UserQuery(Base):
    __tablename__ = "user_queries"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    query = Column(Text, nullable=False)
    response = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    success = Column(Boolean, default=True)

# Состояния для FSM
class UserState:
    def __init__(self):
        self.states: Dict[int, Dict[str, Any]] = {}

    def get_state(self, user_id: int) -> Optional[str]:
        return self.states.get(user_id, {}).get('state')

    def set_state(self, user_id: int, state: str, **kwargs):
        self.states[user_id] = {'state': state, **kwargs}

    def clear_state(self, user_id: int):
        if user_id in self.states:
            del self.states[user_id]

user_state = UserState()

# NLP модель
nlp_model = SentenceTransformer('all-MiniLM-L6-v2')

# Функции для работы с базой данных
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            await session.close()

async def ensure_tables():
    """Проверка и создание таблиц если их нет"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def is_admin(user_id: int) -> bool:
    """Проверка является ли пользователь администратором"""
    async for session in get_db():
        result = await session.execute(
            select(BotAdmin).where(
                BotAdmin.user_id == user_id,
                BotAdmin.is_active == True
            )
        )
        return bool(result.scalar_one_or_none())

# Клавиатуры
def get_main_keyboard(is_admin: bool = False):
    keyboard = [
        [
            InlineKeyboardButton(text="❓ Спросить", callback_data="ask"),
            InlineKeyboardButton(text="📚 Учить", callback_data="learn")
        ],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ]
    if is_admin:
        keyboard.append([
            InlineKeyboardButton(text="⚙️ Администрирование", callback_data="admin")
        ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton(text="➕ Добавить админа", callback_data="add_admin"),
            InlineKeyboardButton(text="➖ Удалить админа", callback_data="remove_admin")
        ],
        [
            InlineKeyboardButton(text="🔄 Настройки бота", callback_data="bot_settings")
        ],
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="stats"),
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# Обработчики команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    admin_status = await is_admin(user_id)
    await message.answer(
        "👋 Привет! Я RenderGuru - ваш помощник по 3D-визуализации.\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard(is_admin=admin_status)
    )

@dp.callback_query(lambda c: c.data == "ask")
async def process_ask(callback_query: types.CallbackQuery):
    user_state.set_state(callback_query.from_user.id, "waiting_for_question")
    await callback_query.message.edit_text(
        "Задайте ваш вопрос о 3D-визуализации:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
        ])
    )

@dp.message(lambda message: user_state.get_state(message.from_user.id) == "waiting_for_question")
async def handle_question(message: types.Message):
    question = message.text.strip()
    user_id = message.from_user.id
    
    try:
        async for session in get_db():
            # Поиск похожих вопросов
            similar_questions = await session.execute(
                """
                SELECT question, answer, similarity(question, :query) as sim
                FROM knowledge_base
                WHERE similarity(question, :query) > 0.3
                ORDER BY sim DESC
                LIMIT 1
                """,
                {"query": question}
            )
            result = similar_questions.first()

            if result:
                answer = result.answer
            else:
                # Если ответ не найден, используем OpenAI
                response = await openai.ChatCompletion.acreate(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "Вы - эксперт по 3D-визуализации"},
                        {"role": "user", "content": question}
                    ]
                )
                answer = response.choices[0].message.content

                # Сохраняем новый вопрос и ответ
                new_knowledge = KnowledgeBase(
                    question=question,
                    answer=answer,
                    created_by=user_id
                )
                session.add(new_knowledge)
                await session.commit()

            # Логируем запрос
            query_log = UserQuery(
                user_id=user_id,
                query=question,
                response=answer,
                success=True
            )
            session.add(query_log)
            await session.commit()

            # Отправляем ответ
            await message.answer(
                answer,
                reply_markup=get_main_keyboard(is_admin=await is_admin(user_id))
            )
            user_state.clear_state(user_id)

    except Exception as e:
        logger.error(f"Error processing question: {e}")
        await message.answer(
            "Произошла ошибка при обработке вопроса. Попробуйте позже.",
            reply_markup=get_main_keyboard(is_admin=await is_admin(user_id))
        )
        user_state.clear_state(user_id)

@dp.callback_query(lambda c: c.data == "admin")
async def process_admin(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    if await is_admin(user_id):
        await callback_query.message.edit_text(
            "Панель администратора:",
            reply_markup=get_admin_keyboard()
        )
    else:
        await callback_query.answer("У вас нет прав администратора")

@dp.callback_query(lambda c: c.data == "learn")
async def process_learn(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_state.set_state(user_id, "waiting_for_learn_question")
    await callback_query.message.edit_text(
        "Введите вопрос, которому нужно обучить бота:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
        ])
    )

@dp.message(lambda message: user_state.get_state(message.from_user.id) == "waiting_for_learn_question")
async def handle_learn_question(message: types.Message):
    user_id = message.from_user.id
    user_state.set_state(user_id, "waiting_for_learn_answer", question=message.text)
    await message.answer("Теперь введите ответ на этот вопрос:")

@dp.message(lambda message: user_state.get_state(message.from_user.id) == "waiting_for_learn_answer")
async def handle_learn_answer(message: types.Message):
    user_id = message.from_user.id
    state_data = user_state.states[user_id]
    question = state_data.get('question')
    
    try:
        async for session in get_db():
            new_knowledge = KnowledgeBase(
                question=question,
                answer=message.text,
                created_by=user_id
            )
            session.add(new_knowledge)
            await session.commit()

        await message.answer(
            "✅ Спасибо! Я запомнил новый вопрос и ответ.",
            reply_markup=get_main_keyboard(is_admin=await is_admin(user_id))
        )
    except Exception as e:
        logger.error(f"Error saving knowledge: {e}")
        await message.answer(
            "Произошла ошибка при сохранении. Попробуйте позже.",
            reply_markup=get_main_keyboard(is_admin=await is_admin(user_id))
        )
    
    user_state.clear_state(user_id)

@dp.callback_query(lambda c: c.data == "back_to_main")
async def process_back_to_main(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    user_state.clear_state(user_id)
    await callback_query.message.edit_text(
        "Выберите действие:",
        reply_markup=get_main_keyboard(is_admin=await is_admin(user_id))
    )

# Запуск бота
async def main():
    logger.info("Starting bot...")
    try:
        await ensure_tables()
        logger.info("Database tables checked/created")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
