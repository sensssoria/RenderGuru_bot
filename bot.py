import os
import logging
import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, AsyncGenerator
from redis import asyncio as aioredis
import numpy as np

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, JSON, func, select
from sentence_transformers import SentenceTransformer
import openai
from cachetools import TTLCache

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загрузка и валидация переменных окружения
class Config:
    API_TOKEN = os.getenv("API_TOKEN")
    DATABASE_URL = os.getenv("DATABASE_URL")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost")
    RATE_LIMIT = int(os.getenv("RATE_LIMIT", "5"))  # запросов в минуту
    
    @classmethod
    def validate(cls):
        if not cls.API_TOKEN:
            raise ValueError("No API_TOKEN provided in environment")
        if not cls.DATABASE_URL:
            raise ValueError("No DATABASE_URL provided in environment")
        if not cls.OPENAI_API_KEY:
            raise ValueError("No OPENAI_API_KEY provided in environment")

Config.validate()
openai.api_key = Config.OPENAI_API_KEY

# Инициализация Redis
redis = aioredis.from_url(Config.REDIS_URL)

# Инициализация бота и диспетчера
bot = Bot(token=Config.API_TOKEN)
dp = Dispatcher()

# Настройка базы данных
engine = create_async_engine(Config.DATABASE_URL, echo=False, pool_size=5, max_overflow=10)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# Кэш для клавиатур и частых запросов
keyboard_cache = TTLCache(maxsize=100, ttl=3600)  # 1 час
response_cache = TTLCache(maxsize=1000, ttl=1800)  # 30 минут

# Модели базы данных
class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    id = Column(Integer, primary_key=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    created_by = Column(Integer)
    embedding = Column(JSON, nullable=True)  # Для хранения векторных представлений

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

# Улучшенное управление состояниями через Redis
class RedisUserState:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.ttl = 3600  # 1 час

    async def get_state(self, user_id: int) -> Optional[Dict[str, Any]]:
        data = await self.redis.get(f"state:{user_id}")
        return eval(data.decode()) if data else None

    async def set_state(self, user_id: int, state: str, **kwargs):
        data = str({"state": state, **kwargs})
        await self.redis.setex(f"state:{user_id}", self.ttl, data)

    async def clear_state(self, user_id: int):
        await self.redis.delete(f"state:{user_id}")

user_state = RedisUserState(redis)

# Rate limiting
class RateLimiter:
    def __init__(self, redis_client, limit: int = 5, window: int = 60):
        self.redis = redis_client
        self.limit = limit
        self.window = window

    async def can_proceed(self, user_id: int) -> bool:
        key = f"rate_limit:{user_id}"
        requests = await self.redis.incr(key)
        if requests == 1:
            await self.redis.expire(key, self.window)
        return requests <= self.limit

rate_limiter = RateLimiter(redis, Config.RATE_LIMIT)

# NLP модель
nlp_model = SentenceTransformer('all-MiniLM-L6-v2')

# Улучшенная работа с базой данных
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            try:
                yield session
            except Exception as e:
                await session.rollback()
                logger.error(f"Database error: {e}")
                raise

# Проверка доступности OpenAI
async def check_openai_availability() -> bool:
    try:
        await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages=[{"role": "system", "content": "test"}],
            max_tokens=5
        )
        return True
    except Exception as e:
        logger.error(f"OpenAI API check failed: {e}")
        return False

# Валидация входных данных
def validate_text(text: str, max_length: int = 1000) -> bool:
    return bool(text and len(text.strip()) <= max_length)

# Кэширование клавиатур
def get_cached_keyboard(key: str, generator_func, *args, **kwargs) -> InlineKeyboardMarkup:
    if key not in keyboard_cache:
        keyboard_cache[key] = generator_func(*args, **kwargs)
    return keyboard_cache[key]

def get_main_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    cache_key = f"main_keyboard:{is_admin}"
    return get_cached_keyboard(
        cache_key,
        lambda: InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="❓ Спросить", callback_data="ask"),
                InlineKeyboardButton(text="📚 Учить", callback_data="learn")
            ],
            [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")],
            *([[InlineKeyboardButton(text="⚙️ Администрирование", callback_data="admin")]] if is_admin else [])
        ])
    )

def get_admin_keyboard() -> InlineKeyboardMarkup:
    return get_cached_keyboard(
        "admin_keyboard",
        lambda: InlineKeyboardMarkup(inline_keyboard=[
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
        ])
    )

# Улучшенный поиск похожих вопросов
async def find_similar_question(session: AsyncSession, query: str, threshold: float = 0.7) -> Optional[tuple]:
    query_embedding = nlp_model.encode(query)
    
    # Получаем все вопросы из базы
    result = await session.execute(select(KnowledgeBase))
    questions = result.scalars().all()
    
    max_similarity = 0
    best_match = None
    
    for q in questions:
        if not q.embedding:
            q.embedding = nlp_model.encode(q.question).tolist()
            session.add(q)
        
        similarity = np.dot(query_embedding, q.embedding)
        if similarity > max_similarity:
            max_similarity = similarity
            best_match = q
    
    if best_match and max_similarity >= threshold:
        return best_match.question, best_match.answer
    return None

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
    if not await rate_limiter.can_proceed(callback_query.from_user.id):
        await callback_query.answer("Пожалуйста, подождите перед следующим запросом")
        return

    await user_state.set_state(callback_query.from_user.id, "waiting_for_question")
    await callback_query.message.edit_text(
        "Задайте ваш вопрос о 3D-визуализации:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
        ])
    )

@dp.message(lambda message: user_state.get_state(message.from_user.id) == "waiting_for_question")
async def handle_question(message: types.Message):
    if not validate_text(message.text):
        await message.answer("Текст вопроса слишком длинный или пустой")
        return

    question = message.text.strip()
    user_id = message.from_user.id
    
    try:
        async for session in get_db():
            similar = await find_similar_question(session, question)
            
            if similar:
                answer = similar[1]
            else:
                if not await check_openai_availability():
                    await message.answer("Извините, сервис временно недоступен")
                    return
                    
                response = await openai.ChatCompletion.acreate(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "Вы - эксперт по 3D-визуализации"},
                        {"role": "user", "content": question}
                    ]
                )
                answer = response.choices[0].message.content

                new_knowledge = KnowledgeBase(
                    question=question,
                    answer=answer,
                    created_by=user_id,
                    embedding=nlp_model.encode(question).tolist()
                )
                session.add(new_knowledge)
                await session.commit()

            query_log = UserQuery(
                user_id=user_id,
                query=question,
                response=answer,
                success=True
            )
            session.add(query_log)
            await session.commit()

            await message.answer(
                answer,
                reply_markup=get_main_keyboard(is_admin=await is_admin(user_id))
            )
            await user_state.clear_state(user_id)

    except Exception as e:
        logger.error(f"Error processing question: {e}")
        await message.answer(
            "Произошла ошибка при обработке вопроса. Попробуйте позже.",
            reply_markup=get_main_keyboard(is_admin=await is_admin(user_id))
        )
        await user_state.clear_state(user_id)

# [Остальные обработчики команд остаются без изменений]

# Улучшенный запуск бота
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/checked")

async def main():
    logger.info("Starting bot...")
    try:
        # Проверяем доступность всех сервисов
        await setup_database()
        await redis.ping()
        if not await check_openai_availability():
            logger.warning("OpenAI API is not available")
        
        # Запускаем бота
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        raise
    finally:
        await redis.close()
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
