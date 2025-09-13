# bot.py
# Telegram English Tutor Bot — text-only: уровни, цели, задания, память прогресса
# Требует: python-telegram-bot==20.3, openai>=1.30, python-dotenv  (env: TELEGRAM_BOT_TOKEN, OPENAI_API_KEY)

import os, json, time
from pathlib import Path
from typing import Dict, Any, Tuple, List

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# ---------- Конфиг ----------
LEVELS = ["Beginner","Elementary","Pre-Intermediate","Intermediate","Upper-Intermediate","Advanced"]
DATA_DIR = Path("data"); DATA_DIR.mkdir(exist_ok=True)
USERS_DB = DATA_DIR / "users.json"

SYSTEM_STYLE = (
    "You are 'Chatty', a warm, upbeat, human-sounding English tutor.\n"
    "Speak natural conversational English (no robotic phrasing).\n"
    "Keep instructions clear, bite-sized, and practical.\n"
    "Use short paragraphs, bullets, and tiny examples.\n"
    "Correct gently and give specific, actionable feedback.\n"
    "When giving tasks, include ~1–2 focused items at a time."
)

# ---------- Хранилище ----------
def load_db() -> Dict[str, Any]:
    if USERS_DB.exists():
        try:
            return json.loads(USERS_DB.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_db(db: Dict[str, Any]) -> None:
    tmp = USERS_DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(USERS_DB)

DB = load_db()  # { user_id: {level, goals, streak, last_lesson_ts, pending_task:{task,key}, history:[(role,text),...] } }

def userc(uid: int) -> Dict[str, Any]:
    sid = str(uid)
    if sid not in DB:
        DB[sid] = {"level": None, "goals": [], "streak": 0, "last_lesson_ts": 0, "pending_task": None, "history": []}
    return DB[sid]

# ---------- OpenAI ----------
from openai import OpenAI
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

async def gpt(messages: List[Dict[str,str]], max_tokens: int = 500) -> str:
    r = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0.7,
        max_tokens=max_tokens,
    )
    return r.choices[0].message.content.strip()

def tutor_messages(level: str, goals: list, history: list, user_prompt: str, mode_hint: str = ""):
    sys = (
        f"{SYSTEM_STYLE}\n"
        f"Student level: {level or 'not set'}.\n"
        f"Student goals: {', '.join(goals) if goals else 'none'}.\n"
        f"{mode_hint}"
    )
    msgs = [{"role":"system","content":sys}]
    for role, text in history[-12:]:
        msgs.append({"role":role,"content":text})
    msgs.append({"role":"user","content":user_prompt})
    return msgs

# ---------- Клавиатуры ----------
def level_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, lvl in enumerate(LEVELS, 1):
        row.append(InlineKeyboardButton(lvl, callback_data=f"level|{lvl}"))
        if i % 2 == 0: rows.append(row); row = []
    if row: rows.append(row)
    return InlineKeyboardMarkup(rows)

def yesno_kb(cb_yes: str, cb_no: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data=cb_yes),
                                  InlineKeyboardButton("No",  callback_data=cb_no)]])

# ---------- Построитель уроков ----------
async def build_intro_lesson(level: str) -> str:
    prompt = (
        f"Create a short warm-up for a {level} learner:\n"
        f"- a 3–4 line mini-dialogue to read and imitate\n"
        f"- 3 focused tips (grammar/vocab/pronunciation)\n"
        f"- ONE quick task with a clear instruction the student can answer in 1–2 lines\n"
        f"Friendly and concise."
    )
    return await gpt([{"role":"system","content":SYSTEM_STYLE},{"role":"user","content":prompt}], max_tokens=450)

async def build_task(level: str, goals: list) -> Tuple[str,str]:
    prompt = (
        f"Design ONE short exercise for a {level} learner focused on {', '.join(goals) or 'general English'}.\n"
        f"Output EXACTLY in two parts:\n"
        f"---TASK---\n<concise instruction>\n"
        f"---KEY---\n<brief ideal answer/checklist>"
    )
    out = await gpt([{"role":"system","content":SYSTEM_STYLE},{"role":"user","content":prompt}], max_tokens=500)
    task, key = "", ""
    if "---TASK---" in out and "---KEY---" in out:
        _, rest = out.split("---TASK---", 1)
        task_part, key_part = rest.split("---KEY---", 1)
        task = task_part.strip(); key = key_part.strip()
    else:
        task = out.strip(); key = "Judge by clarity, grammar and relevance."
    return task, key

async def check_answer(level: str, task: str, key: str, answer: str) -> str:
    prompt = (
        f"Student level: {level}\nTask:\n{task}\n\nKey:\n{key}\n\nAnswer:\n{answer}\n\n"
        f"Evaluate briefly (≤5 lines):\n- correctness (✅/⚠️/❌) with one reason\n"
        f"- 1–2 tiny corrections with examples\n- one short follow-up"
    )
    return await gpt([{"role":"system","content":SYSTEM_STYLE},{"role":"user","content":prompt}], max_tokens=350)

# ---------- Команды ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    if not u["level"]:
        await update.message.reply_text("Hi! Let’s set your level. Choose one:", reply_markup=level_kb())
    else:
        await update.message.reply_text(
            f"Welcome back! Your level is *{u['level']}*.\n"
            f"Set goals with /goals, get a lesson with /lesson, or ask me anything.",
            parse_mode="Markdown"
        )

async def setlevel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pick your English level:", reply_markup=level_kb())

async def on_level_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, lvl = q.data.split("|", 1)
    u = userc(q.from_user.id); u["level"] = lvl; save_db(DB)
    await q.edit_message_text(f"Level set to *{lvl}* ✅", parse_mode="Markdown")
    await q.message.reply_text("Do you want to set learning goals?", reply_markup=yesno_kb("goals|yes","goals|no"))

async def on_goals_yesno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, ans = q.data.split("|", 1)
    if ans == "yes":
        context.user_data["awaiting_goals"] = True
        await q.edit_message_text("Send your goals as a comma-separated list (e.g., speaking, travel, pronunciation).")
    else:
        await q.edit_message_text("Okay! You can set goals later with /goals. Get a lesson with /lesson.")

async def goals_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    userc(update.effective_user.id)
    context.user_data["awaiting_goals"] = True
    await update.message.reply_text("Send your goals as a comma-separated list.\nExample: speaking, grammar, business email")

async def lesson_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    if not u["level"]:
        await update.message.reply_text("Please set your level first: /setlevel"); return
    now = time.time()
    if now - u["last_lesson_ts"] < 20:
        await update.message.reply_text("One moment… finishing the previous lesson."); return
    await update.message.reply_text("Preparing a short warm-up…")
    intro = await build_intro_lesson(u["level"]); await update.message.reply_text(intro)
    task, key = await build_task(u["level"], u["goals"])
    u["pending_task"] = {"task": task, "key": key}; u["last_lesson_ts"] = now; save_db(DB)
    await update.message.reply_text(f"*Your task:*\n{task}\n\nReply here with your answer.", parse_mode="Markdown")

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    DB[str(update.effective_user.id)] = {"level": None, "goals": [], "streak": 0, "last_lesson_ts": 0, "pending_task": None, "history": []}
    save_db(DB); await update.message.reply_text("Your data was reset. Run /start to set level again.")

# ---------- Текстовые сообщения ----------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = userc(uid)
    txt = (update.message.text or "").strip()

    # Приём целей
    if context.user_data.get("awaiting_goals"):
        goals = [g.strip() for g in txt.split(",") if g.strip()]
        u["goals"] = goals; context.user_data["awaiting_goals"] = False; save_db(DB)
        await update.message.reply_text(f"Goals saved: {', '.join(goals) if goals else 'none'}. Get a lesson with /lesson.")
        return

    # Проверка ответа на задание
    if u.get("pending_task"):
        task = u["pending_task"]["task"]; key = u["pending_task"]["key"]
        await update.message.reply_text("Checking your answer…")
        fb = await check_answer(u["level"], task, key, txt)
        u["pending_task"] = None; u["streak"] = int(u.get("streak", 0)) + 1; save_db(DB)
        await update.message.reply_text(fb); return

    # Обычный вопрос
    u["history"].append(("user", txt)); u["history"] = u["history"][-20:]
    reply = await gpt(tutor_messages(u["level"], u["goals"], u["history"], txt, "Tutor mode: be brief, add one tiny practice."), max_tokens=400)
    u["history"].append(("assistant", reply)); u["history"] = u["history"][-20:]; save_db(DB)
    await update.message.reply_text(reply)

# ---------- main ----------
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not OPENAI_API_KEY:
        print("❌ Missing TELEGRAM_BOT_TOKEN or OPENAI_API_KEY in .env"); return

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setlevel", setlevel))
    app.add_handler(CommandHandler("goals", goals_cmd))
    app.add_handler(CommandHandler("lesson", lesson_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))
    app.add_handler(CallbackQueryHandler(on_level_pick, pattern=r"^level\|"))
    app.add_handler(CallbackQueryHandler(on_goals_yesno, pattern=r"^goals\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("✅ Tutor bot is running. Press Ctrl+C to stop.")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
