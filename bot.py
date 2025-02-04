from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# Токен вашего бота (вставь сюда свой токен)
TOKEN = 'ВАШ_ТОКЕН'

# База знаний (пока простые вопросы и ответы)
knowledge_base = {
    "как настроить освещение": "Для настройки освещения в 3Ds Max используйте Corona Light или V-Ray Light. Подробнее: [ссылка]",
    "как сделать реалистичный рендер": "Используйте правильные материалы, настройте освещение и добавьте постобработку. Подробнее: [ссылка]",
}

# Обработчик команды /start
def start(update: Update, context: CallbackContext):
    update.message.reply_text("Привет! Я RenderGuru_bot, твой помощник по 3D-визуализации. Задай мне вопрос!")

# Обработчик текстовых сообщений
def handle_message(update: Update, context: CallbackContext):
    user_message = update.message.text.lower()
    response = knowledge_base.get(user_message, "Пока я не знаю ответа на этот вопрос. Попробуй задать его иначе!")
    update.message.reply_text(response)

# Основная функция
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Регистрируем обработчики
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    # Запускаем бота
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
