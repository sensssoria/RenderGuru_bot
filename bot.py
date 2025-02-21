import os 
import logging
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.exceptions import TelegramNetworkError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, Text, DateTime, func, select
from redis import asyncio as aioredis

# ✅ Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Переменные окружения
API_TOKEN = os.getenv("API_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))  # Добавлена переменная для суперадмина

if not all([API_TOKEN, DATABASE_URL, REDIS_URL, OWNER_ID]):
    raise ValueError("❌ Ошибка: Не заданы все обязательные переменные окружения.")

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

# ✅ Проверка на админа
async def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True  # ✅ Супер-админ всегда админ!

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admins).where(Admins.user_id == user_id))
        return bool(result.scalar_one_or_none())

# ✅ /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer("👋 Привет! Я RenderGuru Bot.", reply_markup=main_menu)

# ✅ Обработчик кнопок
@dp.message()
async def handle_buttons(message: Message):
    text = message.text.lower().strip()
    
    if text == "спросить":
        await message.answer("🔍 Введите вопрос, и я попробую найти ответ!")
    elif text == "учить":
        await message.answer("✏ Введите вопрос, который хотите добавить:")
    elif text == "помощь":
        await message.answer("ℹ Доступные команды:\n/start – Запуск бота\n/list_admins – Список админов\n/learning – Обучение бота")
    elif text == "администрирование":
        if await is_admin(message.from_user.id):
            await message.answer("⚙ Добро пожаловать в админ-панель!\nДоступные команды:\n/add_admin\n/remove_admin\n/list_admins")
        else:
            await message.answer("❌ У вас нет прав доступа к администрированию.")
    else:
        await message.answer("❓ Я не понимаю этот запрос. Попробуйте выбрать команду из меню.")

# ✅ /list_admins
@dp.message(Command("list_admins"))
async def list_admins(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав!")
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admins))
        admins = result.scalars().all()
        admin_list = "\n".join([f"👤 {admin.user_id}" for admin in admins]) if admins else "👤 Администраторов пока нет."
        await message.answer(f"📜 Список администраторов:\n{admin_list}")

# ✅ Подключение обработчиков
def register_handlers():
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(list_admins, Command("list_admins"))
    dp.message.register(handle_buttons)

register_handlers()

# ✅ Запуск бота
async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    try:
        logger.info("🚀 Запуск бота...")
        await dp.start_polling(bot)
    except TelegramNetworkError as e:
        logger.error(f"❌ Ошибка сети Telegram: {e}. Переподключение через 5 секунд...")
        await asyncio.sleep(5)
    finally:
        logger.info("🛑 Остановка бота. Закрытие сессии...")
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен вручную.")
