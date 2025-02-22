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
import openai

# ✅ Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Переменные окружения
API_TOKEN = os.getenv("API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

if not all([API_TOKEN, DATABASE_URL, REDIS_URL, OWNER_ID]):
    raise ValueError("❌ Ошибка: Не заданы все необходимые переменные окружения.")

# ✅ Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# ✅ Redis
redis_client = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)

# ✅ Главное меню
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Спросить"), KeyboardButton(text="Учить")],
        [KeyboardButton(text="Помощь"), KeyboardButton(text="Администрирование")],
    ],
    resize_keyboard=True
)

# ✅ База данных
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# ✅ Таблица администраторов
class Admins(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, nullable=False)
    added_at = Column(DateTime, server_default=func.now())

# ✅ Таблица базы знаний
class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

# ✅ Проверка на админа
async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admins).where(Admins.user_id == user_id))
        return bool(result.scalar_one_or_none())

# ✅ /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    logger.info(f"Команда /start от пользователя: {message.from_user.id}")
    await message.answer("👋 Привет! Я RenderGuru Bot.", reply_markup=main_menu)

# ✅ Обработчик кнопок и команд
@dp.message()
async def handle_buttons(message: Message):
    text = message.text.lower().strip()
    logger.info(f"Обработка сообщения: {text}")
    if text == "спросить":
        await message.answer("🔍 Введите ваш вопрос, и я попробую найти ответ!")
    elif text == "учить":
        await message.answer("✏ Введите вопрос, который хотите добавить:")
    elif text == "помощь":
        await message.answer("ℹ Доступные команды:\n/start – Запуск бота\n/list_admins – Список админов\n/learning – Обучение бота")
    elif text == "администрирование":
        if await is_admin(message.from_user.id):
            await message.answer("⚙ Добро пожаловать в админ-панель!\nДоступные команды:\n/add_admin\n/remove_admin\n/list_admins")
        else:
            await message.answer("❌ У вас нет прав доступа к администрированию.")
    elif text.startswith("/"):
        logger.info(f"Обработка команды: {text}")
        await message.answer(f"❓ Команда '{text}' не распознана. Попробуйте другую.")
    else:
        logger.info(f"Неизвестная команда: {text}")
        await message.answer("❓ Я не понимаю этот запрос. Попробуйте выбрать команду из меню.")

# ✅ Подключение обработчиков
def register_handlers():
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(handle_buttons)

register_handlers()

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
