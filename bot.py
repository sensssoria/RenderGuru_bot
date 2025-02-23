import os
import logging
import asyncio
import json
import functools
from typing import Optional

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.dispatcher.middlewares.base import BaseMiddleware

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, Text, DateTime, func, select

from redis import asyncio as aioredis
import openai

from pydantic import BaseSettings, ValidationError

# ---------------------------
# Конфигурация через Pydantic
# ---------------------------
class Config(BaseSettings):
    API_TOKEN: str
    DATABASE_URL: str
    REDIS_URL: str
    OWNER_ID: int
    OPENAI_API_KEY: str = ""

    class Config:
        env_file = ".env"

try:
    config = Config()
except ValidationError as e:
    raise ValueError(f"❌ Ошибка валидации переменных окружения: {e}")

# ---------------------------
# Настройка логирования
# ---------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------
# Инициализация бота и диспетчера
# ---------------------------
bot = Bot(token=config.API_TOKEN)
dp = Dispatcher()

# ---------------------------
# Middleware для проактивного логирования
# ---------------------------
class LoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Message, data):
        logger.info(f"Получено сообщение от {event.from_user.id}: {event.text}")
        result = await handler(event, data)
        logger.info(f"Результат обработки: {result}")
        return result

# Регистрируем middleware для всех сообщений
dp.message.middleware.register(LoggingMiddleware())

# ---------------------------
# Механизм повторных попыток для работы с БД
# ---------------------------
def db_retry(max_retries=3, delay=1):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < max_retries:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    logger.error(f"Ошибка БД (попытка {attempts}/{max_retries}): {e}")
                    if attempts < max_retries:
                        await asyncio.sleep(delay)
            raise Exception("Достигнуто максимальное число попыток для операции с БД")
        return wrapper
    return decorator

# ---------------------------
# Класс для управления Redis с резервным копированием
# ---------------------------
class RedisManager:
    def __init__(self):
        self.pool = aioredis.ConnectionPool.from_url(
            config.REDIS_URL,
            max_connections=10,
            encoding="utf-8",
            decode_responses=True
        )
        self.redis = aioredis.Redis(connection_pool=self.pool)

    async def get_session(self, user_id: int) -> dict:
        try:
            data = await self.redis.get(f"session:{user_id}")
            return json.loads(data) if data else {}
        except Exception as e:
            logger.error(f"Ошибка Redis при получении сессии: {e}")
            # Попытка резервного копирования (заготовка)
            await self.backup_session(user_id, {})
            return {}

    async def backup_session(self, user_id: int, session_data: dict):
        backup_file = f"backup_session_{user_id}.json"
        try:
            with open(backup_file, "w") as f:
                json.dump(session_data, f)
            logger.info(f"Сессия пользователя {user_id} сохранена в резервную копию: {backup_file}")
        except Exception as e:
            logger.error(f"Ошибка резервного копирования для пользователя {user_id}: {e}")

redis_manager = RedisManager()

# ---------------------------
# Главное меню (UI)
# ---------------------------
main_menu = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Спросить"), KeyboardButton(text="Учить")],
        [KeyboardButton(text="Помощь"), KeyboardButton(text="Администрирование")],
    ],
    resize_keyboard=True
)

# ---------------------------
# Инициализация базы данных
# ---------------------------
engine = create_async_engine(config.DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()

# Таблица администраторов
class Admins(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, nullable=False)
    added_at = Column(DateTime, server_default=func.now())

# Таблица базы знаний
class KnowledgeBase(Base):
    __tablename__ = "knowledge_base"
    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_by = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    # TODO: Добавить поля для хранения эмбеддингов для NLP-поиска (например, с использованием Sentence Transformers)

# ---------------------------
# FSM: Определение состояний бота
# ---------------------------
class BotStates(StatesGroup):
    waiting_for_question = State()
    waiting_for_answer = State()
    learning_mode = State()
    admin_mode = State()

# Заглушка для обработки тайм-аутов (будет реализована через фоновую задачу)
async def state_timeout_handler():
    pass

# Глобальный словарь для хранения времени установки состояния (user_id: timestamp)
state_timestamps = {}

async def schedule_state(user_id: int):
    state_timestamps[user_id] = asyncio.get_event_loop().time()

async def check_state_timeouts():
    while True:
        current_time = asyncio.get_event_loop().time()
        for user_id, timestamp in list(state_timestamps.items()):
            if current_time - timestamp > 60:  # таймаут 60 секунд
                state = dp.current_state(user=user_id)
                await state.clear()
                logger.info(f"Состояние для пользователя {user_id} сброшено по таймауту")
                del state_timestamps[user_id]
        await asyncio.sleep(10)

# ---------------------------
# Функции для работы с базой данных
# ---------------------------
@db_retry(max_retries=3, delay=1)
async def get_answer_from_db(question: str) -> Optional[str]:
    try:
        async with AsyncSessionLocal() as session:
            async with session.begin():
                # Здесь можно расширить запрос с использованием полнотекстового поиска и/или NLP-поиска
                result = await session.execute(
                    select(KnowledgeBase).where(KnowledgeBase.question.ilike(f"%{question}%"))
                )
                record = result.scalar_one_or_none()
                if record:
                    return record.answer
        return None
    except Exception as e:
        logger.error(f"Ошибка базы данных: {e}")
        raise

# ---------------------------
# Интеграция с OpenAI для генерации ответа
# ---------------------------
async def get_answer_from_openai(question: str) -> Optional[str]:
    try:
        openai.api_key = config.OPENAI_API_KEY
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": question}],
            temperature=0.7,
            max_tokens=150,
        )
        answer = response["choices"][0]["message"]["content"].strip()
        return answer
    except Exception as e:
        logger.error(f"Ошибка OpenAI: {e}")
        return None

# ---------------------------
# Проверка прав администратора
# ---------------------------
async def is_admin(user_id: int) -> bool:
    if user_id == config.OWNER_ID:
        return True
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admins).where(Admins.user_id == user_id))
        return bool(result.scalar_one_or_none())

# ---------------------------
# Обработчики команд и сообщений
# ---------------------------

# Системные команды
async def cmd_start(message: Message):
    logger.info(f"Команда /start от пользователя: {message.from_user.id}")
    await message.answer("👋 Привет! Я RenderGuru Bot.", reply_markup=main_menu)

async def cmd_help(message: Message):
    help_text = (
        "ℹ Доступные команды:\n"
        "/start – Запуск бота\n"
        "/add_admin – Добавление администратора\n"
        "/remove_admin – Удаление администратора\n"
        "/list_admins – Список администраторов\n"
        "/learning – Режим обучения"
    )
    await message.answer(help_text)

# Команды администратора
async def add_admin(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для этой команды.")
        return
    # Здесь добавить логику запроса и добавления нового администратора
    await message.answer("✅ Команда /add_admin принята. (Логика добавления админа пока не реализована)")

async def remove_admin(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для этой команды.")
        return
    # Здесь добавить логику удаления администратора
    await message.answer("✅ Команда /remove_admin принята. (Логика удаления админа пока не реализована)")

async def list_admins(message: Message):
    if not await is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для этой команды.")
        return
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Admins))
        admins = result.scalars().all()
        if admins:
            admins_list = "\n".join(str(admin.user_id) for admin in admins)
            await message.answer(f"👥 Список администраторов:\n{admins_list}")
        else:
            await message.answer("ℹ Администраторы не найдены.")

# Команды обучения
async def handle_learning(message: Message, state: FSMContext):
    await state.set_state(BotStates.learning_mode)
    await schedule_state(message.from_user.id)
    await message.answer("✏ Режим обучения активирован. Введите вопрос, который хотите добавить:")

async def process_learning(message: Message, state: FSMContext):
    data = await state.get_data()
    if "new_question" not in data:
        await state.update_data(new_question=message.text)
        await message.answer("✏ Введите ответ для данного вопроса:")
    else:
        new_question = data.get("new_question")
        new_answer = message.text
        # Здесь добавить логику подтверждения и сохранения нового вопроса и ответа в базу знаний
        await state.clear()
        await message.answer(f"✅ Получен вопрос: '{new_question}' с ответом: '{new_answer}'. (Логика сохранения пока не реализована)")

# Обработка вопросов (при использовании FSM: ожидание вопроса)
async def handle_question(message: Message, state: FSMContext):
    question = message.text
    # Сначала ищем ответ в базе знаний
    answer = await get_answer_from_db(question)
    if answer:
        await message.answer(f"Ответ из базы знаний:\n{answer}")
    else:
        # Если ответ не найден, пытаемся получить его через OpenAI
        answer = await get_answer_from_openai(question)
        if answer:
            await message.answer(f"Ответ сгенерирован OpenAI:\n{answer}")
            # TODO: Добавить логику подтверждения сохранения нового ответа в базу знаний
        else:
            await message.answer("❌ GPT недоступен, попробуйте позже.")
    await state.clear()

# Общий обработчик кнопок и текстовых сообщений
async def handle_buttons(message: Message):
    text = message.text.lower().strip()
    logger.info(f"Обработка сообщения: {text}")
    if text == "спросить":
        state = dp.current_state(user=message.from_user.id)
        await state.set_state(BotStates.waiting_for_question)
        await schedule_state(message.from_user.id)
        await message.answer("🔍 Введите ваш вопрос:")
    elif text == "учить":
        state = dp.current_state(user=message.from_user.id)
        await state.set_state(BotStates.learning_mode)
        await schedule_state(message.from_user.id)
        await message.answer("✏ Введите вопрос, который хотите добавить:")
    elif text == "помощь":
        await cmd_help(message)
    elif text == "администрирование":
        if await is_admin(message.from_user.id):
            await message.answer("⚙ Добро пожаловать в админ-панель!\nДоступные команды:\n/add_admin\n/remove_admin\n/list_admins")
        else:
            await message.answer("❌ У вас нет прав доступа к администрированию.")
    elif text.startswith("/"):
        logger.info(f"Обработка неизвестной команды: {text}")
        await message.answer(f"❓ Команда '{text}' не распознана. Попробуйте другую.")
    else:
        logger.info(f"Неизвестная команда: {text}")
        await message.answer("❓ Я не понимаю этот запрос. Попробуйте выбрать команду из меню.")

# ---------------------------
# Регистрация обработчиков с учетом приоритетов
# ---------------------------
def register_handlers():
    # 1. Системные команды (наивысший приоритет)
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_help, Command("help"))
    
    # 2. Команды администратора (высокий приоритет)
    dp.message.register(add_admin, Command("add_admin"))
    dp.message.register(remove_admin, Command("remove_admin"))
    dp.message.register(list_admins, Command("list_admins"))
    
    # 3. Команды обучения (средний приоритет)
    dp.message.register(handle_learning, Command("learning"))
    dp.message.register(process_learning, state=BotStates.learning_mode)
    
    # 4. Обработка вопросов (нормальный приоритет)
    dp.message.register(handle_question, state=BotStates.waiting_for_question)
    
    # 5. Обработчик кнопок (низкий приоритет)
    dp.message.register(handle_buttons)

register_handlers()

# ---------------------------
# Основная функция запуска бота
# ---------------------------
async def main():
    # Создание таблиц в базе данных
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Запускаем фоновую задачу для проверки таймаутов состояний
    asyncio.create_task(check_state_timeouts())
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
