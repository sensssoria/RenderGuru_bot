import os
import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, Text, DateTime, func, select
from redis import asyncio as aioredis

# ✅ Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Загрузка переменных окружения
API_TOKEN = os.getenv("API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

if not all([API_TOKEN, DATABASE_URL, REDIS_URL]):
    raise ValueError("❌ Ошибка: Не заданы переменные окружения API_TOKEN, DATABASE_URL или REDIS_URL.")

# ✅ Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# ✅ Инициализация Redis для FSM
redis_client = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

# ✅ Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Спросить"), KeyboardButton(text="Учить")],
        [KeyboardButton(text="Помощь"), KeyboardButton(text="Администрирование")],
    ],
    resize_keyboard=True
)

# ✅ Подключение к БД
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# ✅ Модель таблицы администраторов
class Admins(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, nullable=False)
    added_at = Column(DateTime, server_default=func.now())

# ✅ Проверка, является ли пользователь админом
async def is_admin(user_id: int) -> bool:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admins).where(Admins.user_id == user_id))
        return bool(result.scalar_one_or_none())

# ✅ Команда /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("👋 Привет! Я RenderGuru Bot.", reply_markup=main_menu)

# ✅ Команда /list_admins
@dp.message(Command("list_admins"))
async def list_admins(message: Message):
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

# ✅ Команда /add_admin
@dp.message(Command("add_admin"))
async def add_admin_cmd(message: Message):
    if not await is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет прав!")

    user_id = message.reply_to_message.from_user.id if message.reply_to_message else None
    if not user_id:
        return await message.answer("Ответьте на сообщение пользователя, чтобы сделать его админом.")

    async with AsyncSessionLocal() as session:
        session.add(Admins(user_id=user_id))
        await session.commit()

    await message.answer(f"✅ Пользователь {user_id} теперь администратор.")

# ✅ Команда /remove_admin
@dp.message(Command("remove_admin"))
async def remove_admin_cmd(message: Message):
    if not await is_admin(message.from_user.id):
        return await message.answer("❌ У вас нет прав!")

    user_id = message.reply_to_message.from_user.id if message.reply_to_message else None
    if not user_id:
        return await message.answer("Ответьте на сообщение пользователя, чтобы удалить его из администраторов.")

    async with AsyncSessionLocal() as session:
        await session.execute(select(Admins).where(Admins.user_id == user_id).delete())
        await session.commit()

    await message.answer(f"❌ Пользователь {user_id} удалён из администраторов.")

# ✅ Команда /learning для добавления знаний
@dp.message(Command("learning"))
async def cmd_learning(message: Message):
    await message.answer("✏ Введите вопрос, который хотите добавить:")

@dp.message(lambda message: message.reply_to_message and message.reply_to_message.text.startswith("✏ Введите вопрос"))
async def process_question(message: Message):
    await message.answer("💬 Теперь введите ответ на этот вопрос:")

@dp.message(lambda message: message.reply_to_message and message.reply_to_message.text.startswith("💬 Теперь введите ответ"))
async def process_answer(message: Message):
    question = message.reply_to_message.reply_to_message.text
    answer = message.text

    async with AsyncSessionLocal() as session:
        session.add(KnowledgeBase(question=question, answer=answer, created_by=message.from_user.id))
        await session.commit()

    await message.answer("✅ Вопрос и ответ сохранены!")

# ✅ Подключение к базе знаний
class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

# ✅ Запуск бота
async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    try:
        logger.info("🚀 Запуск бота...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске бота: {e}")
    finally:
        logger.info("🛑 Остановка бота. Закрытие сессии...")
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен вручную.")
