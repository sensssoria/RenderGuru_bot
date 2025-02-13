import os
import logging
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any, AsyncGenerator, List

import numpy as np

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command, BaseFilter  # Заменено: импорт BaseFilter вместо BoundFilter
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

# ---------------------------------------------------------------------
# Настройка логирования
# ---------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Загрузка настроек из переменных окружения
# ---------------------------------------------------------------------
API_TOKEN = os.getenv("API_TOKEN", "YOUR_API_TOKEN_HERE")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/dbname")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ---------------------------------------------------------------------
# Инициализация бота, диспетчера, SQLAlchemy и Redis
# ---------------------------------------------------------------------
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

redis_client = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

# ---------------------------------------------------------------------
# Определение базы данных
# ---------------------------------------------------------------------
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

# ---------------------------------------------------------------------
# Асинхронный фильтр для сообщений, ожидающих вопрос
# ---------------------------------------------------------------------
class WaitingForQuestionFilter(BaseFilter):  # Наследуемся от BaseFilter (aiogram 3.x)
    key = "waiting_for_question"

    def __init__(self, waiting_for_question: str):
        self.waiting_for_question = waiting_for_question

    async def __call__(self, message: types.Message) -> bool:
        state = await user_state.get_state(message.from_user.id)
        return state is not None and state.get("state") == self.waiting_for_question

dp.message.filter(WaitingForQuestionFilter(waiting_for_question="waiting_for_question"))

# ---------------------------------------------------------------------
# Работа с администраторами
# ---------------------------------------------------------------------
async def is_admin(user_id: int) -> bool:
    async for session in get_db():
        result = await session.execute(select(Admins).where(Admins.user_id == user_id))
        return bool(result.scalar_one_or_none())

@dp.message(Command("add_admin"))
async def add_admin(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав на добавление администраторов!")
        return

    try:
        new_admin_id = int(message.text.split()[1])
        async for session in get_db():
            existing_admin = await session.execute(select(Admins).where(Admins.user_id == new_admin_id))
            if existing_admin.scalar_one_or_none():
                await message.answer("✅ Этот пользователь уже администратор!")
                return

            new_admin = Admins(user_id=new_admin_id)
            session.add(new_admin)
            await session.commit()
        await message.answer(f"✅ Пользователь {new_admin_id} добавлен в администраторы!")
    except (IndexError, ValueError):
        await message.answer("❌ Используйте: /add_admin <user_id>")

@dp.message(Command("remove_admin"))
async def remove_admin(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав на удаление администраторов!")
        return

    try:
        remove_admin_id = int(message.text.split()[1])
        async for session in get_db():
            result = await session.execute(select(Admins).where(Admins.user_id == remove_admin_id))
            admin = result.scalar_one_or_none()
            if not admin:
                await message.answer("❌ Этот пользователь не является администратором!")
                return
            await session.delete(admin)
            await session.commit()
        await message.answer(f"✅ Пользователь {remove_admin_id} удалён из администраторов!")
    except (IndexError, ValueError):
        await message.answer("❌ Используйте: /remove_admin <user_id>")

# ---------------------------------------------------------------------
# Функция для получения сессии базы данных
# ---------------------------------------------------------------------
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

# ---------------------------------------------------------------------
# Основная функция для запуска бота
# ---------------------------------------------------------------------
async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        await dp.startup()
        await dp.start_polling(bot)
    finally:
        await dp.shutdown()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
