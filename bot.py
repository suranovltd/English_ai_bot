import os, logging, tempfile
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from openai import OpenAI
from gtts import gTTS

load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

logging.basicConfig(level=logging.INFO)
client = OpenAI(api_key=OPENAI_API_KEY)

async def start(update: Update, context):
    await update.message.reply_text("Привет! Пиши текст — отвечу текстом и голосом.")

async def handle_message(update: Update, context):
    user_text = update.message.text
    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": user_text}]
    )
    bot_reply = completion.choices[0].message.content

    # текст
    await update.message.reply_text(bot_reply)

    # голос (как аудио MP3)
    tts = gTTS(text=bot_reply, lang='ru')
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        tts.save(tmp.name)
        await update.message.reply_audio(audio=open(tmp.name, "rb"), title="Ответ бота")

app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

print("Бот запущен…")
app.run_polling()
