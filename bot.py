import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import json
import logging
from pathlib import Path

# Настраиваем логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Получаем токен из переменной окружения
TOKEN = os.getenv('TOKEN')

# Временная проверка загрузки токена
if not TOKEN:
    logger.error("Токен не загружен! Проверь переменные окружения.")
    exit(1)
else:
    print(f"Токен загружен: {TOKEN[:5]}***")

# Загружаем базу знаний из JSON файла
def load_knowledge_base():
    kb_path = Path('knowledge_base.json')
    if kb_path.exists():
        with open(kb_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "questions": {},
        "topics": {
            "3ds_max": ["моделирование", "рендеринг", "материалы"],
            "corona": ["освещение", "материалы", "настройки"],
            "vray": ["освещение", "материалы", "настройки"]
        }
    }

# Сохраняем базу знаний
def save_knowledge_base(knowledge_base):
    with open('knowledge_base.json', 'w', encoding='utf-8') as f:
        json.dump(knowledge_base, f, ensure_ascii=False, indent=2)

# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я RenderGuru - твой помощник в мире 3D визуализации! 🎨\n"
        "Я могу помочь с вопросами по:\n"
        "- 3Ds Max\n"
        "- Corona Renderer\n"
        "- V-Ray\n"
        "- Текстурированию\n"
        "- Постобработке\n\n"
        "Просто задай свой вопрос или используй /help для списка команд!"
    )

# Обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
Доступные команды:
/start - Начать работу со мной
/help - Показать это сообщение
/learn тема "вопрос" "ответ" - Научить меня новому
/topics - Показать список тем

Примеры вопросов:
- Как настроить освещение в Corona?
- Какие материалы лучше использовать для стекла?
- Как оптимизировать рендер?
    """
    await update.message.reply_text(help_text)

# Обработчик команды /learn
async def learn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text(
            "Использование: /learn тема \"вопрос\" \"ответ\"\n"
            "Например: /learn corona \"Как настроить освещение?\" \"Для базового освещения используйте...\""
        )
        return
    
    knowledge_base = load_knowledge_base()
    
    topic = context.args[0].lower()
    question = ' '.join(context.args[1:-1]).lower()
    answer = context.args[-1]
    
    if question not in knowledge_base["questions"]:
        knowledge_base["questions"][question] = {
            "answer": answer,
            "topic": topic,
            "rating": 0,
            "used_count": 0
        }
        save_knowledge_base(knowledge_base)
        await update.message.reply_text(f"Спасибо! Я запомнил информацию о '{question}'")
    else:
        await update.message.reply_text("Я уже знаю ответ на этот вопрос!")

# Обработчик обычных сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text.lower()
    knowledge_base = load_knowledge_base()
    
    best_match = None
    best_ratio = 0
    
    for question in knowledge_base["questions"]:
        if any(word in question for word in user_message.split()):
            ratio = len(set(question.split()) & set(user_message.split())) / len(set(question.split()))
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = question
    
    if best_match and best_ratio > 0.3:
        answer = knowledge_base["questions"][best_match]["answer"]
        knowledge_base["questions"][best_match]["used_count"] += 1
        save_knowledge_base(knowledge_base)
        await update.message.reply_text(answer)
    else:
        await update.message.reply_text(
            "Извини, я пока не знаю ответа на этот вопрос. 😔\n"
            "Но ты можешь научить меня, используя команду /learn!\n"
            "Или попробуй переформулировать вопрос."
        )

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("learn", learn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("Запуск бота...")
    app.run_polling()

if __name__ == "__main__":
    main()
