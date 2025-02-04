from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Токен вашего бота (вставь сюда свой токен)
TOKEN = 'ВАШ_ТОКЕН'

# База знаний (пока простые вопросы и ответы)
knowledge_base = {
    "как настроить освещение": "Для настройки освещения в 3Ds Max используйте Corona Light или V-Ray Light. Подробнее: [ссылка]",
    "как сделать реалистичный рендер": "Используйте правильные материалы, настройте освещение и добавьте постобработку. Подробнее: [ссылка]",
}

# Обработчик команды /start
async def start(update: Update, context: CallbackContext):
    await update.message.reply_text("Привет! Я RenderGuru_bot, твой помощник по 3D-визуализации. Задай мне вопрос!")

# Обработчик текстовых сообщений
async def handle_message(update: Update, context: CallbackContext):
    user_message = update.message.text.lower()
    response = knowledge_base.get(user_message, "Пока я не знаю ответа на этот вопрос. Попробуй задать его иначе!")
    await update.message.reply_text(response)

# Основная функция
def main():
    # Создаём приложение и передаём токен
    application = Application.builder().token(TOKEN).build()

    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
