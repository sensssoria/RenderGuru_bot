import os
import logging
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, AsyncGenerator, List

import numpy as np
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, BaseFilter
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, Text, DateTime, func, select
from sentence_transformers import SentenceTransformer
import openai
from openai.error import OpenAIError
from cachetools import TTLCache
from pgvector.sqlalchemy import Vector
from redis import asyncio as aioredis

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
API_TOKEN = os.getenv("API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

if not all([API_TOKEN, DATABASE_URL, REDIS_URL]):
    raise ValueError("Missing required environment variables")

# Инициализация Redis для FSM
redis_storage = RedisStorage.from_url(REDIS_URL)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=redis_storage)

# Инициализация баз данных
engine = create_async_engine(DATABASE_URL, echo=True, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Инициализация Redis клиента
redis_client = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

# Определение базы данных
Base = declarative_base()

class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_by = Column(Integer, nullable=False)
    embedding = Column(Vector, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

class Admins(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, nullable=False)
    added_at = Column(DateTime, server_default=func.now())

# Фильтр для ожидания вопросов
class WaitingForQuestionFilter(BaseFilter):
    key = "waiting_for_question"

    def __init__(self, waiting_for_question: str):
        self.waiting_for_question = waiting_for_question

    async def __call__(self, message: types.Message, state: FSMContext) -> bool:
        current_state = await state.get_state()
        return current_state == self.waiting_for_question

# Регистрация фильтра как middleware
dp.message.middleware(WaitingForQuestionFilter(waiting_for_question="waiting_for_question"))

# Функция для получения сессии базы данных
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

# Функции администраторов
async def is_admin(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admins).where(Admins.user_id == user_id))
        return bool(result.scalar_one_or_none())

# Команда /list_admins
@dp.message(Command("list_admins"))
async def list_admins(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав на просмотр списка администраторов!")
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admins))
        admins = result.scalars().all()
        if not admins:
            await message.answer("👤 Список администраторов пуст!")
            return
        admin_list = "\n".join([f"👤 {admin.user_id}" for admin in admins])
        await message.answer(f"📜 Список администраторов:\n{admin_list}")

# Основная функция запуска бота
async def main():
    # Создание таблиц при запуске
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    try:
        # Запуск бота
        logger.info("Starting bot...")
        await dp.startup()
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Error occurred: {e}")
        raise
    finally:
        # Корректное закрытие соединений
        await dp.shutdown()
        await dp.storage.close()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped!")
