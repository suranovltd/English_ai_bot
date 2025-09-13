# bot.py
# English tutor (text-only) for Kyrgyz speakers.
# UI: кыргызча түшүндүрмө жана меню, мисалдар/тапшырмалар англисче.
# Requires: python-telegram-bot==20.3, openai>=1.30, python-dotenv
# ENV: TELEGRAM_BOT_TOKEN, OPENAI_API_KEY

import os, json, time
from pathlib import Path
from typing import Dict, Any, Tuple, List

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

# -------------------- Конфигурация жана файлдар --------------------
LEVELS: List[str] = [
    "Beginner", "Elementary", "Pre-Intermediate",
    "Intermediate", "Upper-Intermediate", "Advanced"
]
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
USERS_DB = DATA_DIR / "users.json"

# Тутордун стили: кыргызча мета-нускама, англисче мазмун
SYSTEM_STYLE = (
    "Сен 'Chatty' аттуу жылуу, достук мүнөздөгү англис тили мугалимисиз.\n"
    "Баардык түшүндүрмөнү жана нускаманы КЫРГЫЗ ТИЛИНДЕ бер.\n"
    "Диалогдор, мисалдар, сөз айкаштары жана тапшырмалардын текстин АНГЛИС ТИЛИНДЕ жаз.\n"
    "Кыска, түшүнүктүү, практикалык бол. Робот сымал сүйлөбө — жандуу сүйлөө колдон.\n"
    "Каталарды назик оңдоп, 1–2 так мисал бер. Ар кадамда 1–2 гана тапшырма.\n"
    "Тема алмаштырбайбыз: максат — англис тилин үйрөтүү. Башка темаларга жооп бербе."
)

# -------------------- Жөнөкөй JSON сактагыч --------------------
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

DB = load_db()  # { user_id: {level, goals, streak, last_lesson_ts, pending_task, history} }

def userc(user_id: int) -> Dict[str, Any]:
    sid = str(user_id)
    if sid not in DB:
        DB[sid] = {
            "level": None,       # "Beginner" ж.б.
            "goals": [],         # ["speaking", "grammar"] ж.б.
            "streak": 0,         # канча тапшырма ийгиликтүү текшерилди
            "last_lesson_ts": 0, # акыркы /lesson убактысы
            "pending_task": None, # {"task": ..., "key": ...}
            "history": []        # акыркы 20 билдирүү (контекст үчүн)
        }
    return DB[sid]

# -------------------- OpenAI --------------------
from openai import OpenAI
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

async def gpt(messages, model="gpt-4o-mini", max_tokens=500) -> str:
    """Жооп текстине гана муктажбыз."""
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.7,
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content.strip()

def tutor_messages(level: str, goals: list, history: list, user_prompt: str, mode_hint: str = ""):
    """Тутор үчүн контекст түзүү."""
    level_str = level or "not set"
    goals_str = ", ".join(goals) if goals else "none"
    sys = (
        f"{SYSTEM_STYLE}\n"
        f"Студенттин деңгээли: {level_str}.\n"
        f"Студенттин максаттары: {goals_str}.\n"
        f"{mode_hint}"
    )
    msgs = [{"role": "system", "content": sys}]
    for role, text in history[-12:]:
        msgs.append({"role": role, "content": text})
    msgs.append({"role": "user", "content": user_prompt})
    return msgs

# -------------------- Клавиатура/Меню --------------------
def level_keyboard() -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, lvl in enumerate(LEVELS, 1):
        row.append(InlineKeyboardButton(lvl, callback_data=f"level|{lvl}"))
        if i % 2 == 0:
            rows.append(row); row = []
    if row: rows.append(row)
    return InlineKeyboardMarkup(rows)

def yesno_keyboard(cb_yes: str, cb_no: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Ооба", callback_data=cb_yes),
         InlineKeyboardButton("Жок", callback_data=cb_no)]
    ])

def menu_text(u: Dict[str, Any]) -> str:
    lvl = u.get("level") or "— коюла элек —"
    goals = ", ".join(u.get("goals", [])) or "жок"
    streak = int(u.get("streak", 0))
    return (
        "📋 *Меню*\n"
        f"• Деңгээлиңиз: *{lvl}*\n"
        f"• Максаттар: *{goals}*\n"
        f"• Прогресс (тапшырма саны): *{streak}*\n\n"
        "Командалар:\n"
        "• /setlevel — деңгээл тандоо\n"
        "• /goals — максаттарды коюу (мис: speaking, grammar)\n"
        "• /lesson — жаңы кыска сабак + 1 тапшырма\n"
        "• /repeat — акыркы тапшырманы кайра көрүү\n"
        "• /reset — бардык маалыматты тазалоо\n"
        "• /menu — менюну көрсөтүү\n"
    )

# -------------------- Сабак/Тапшырма генерациясы --------------------
async def build_intro_lesson(level: str) -> str:
    """Кыска жылуу кириш сөз + англисче материал."""
    prompt = (
        "Бардык түшүндүрмө/мета-нускама КЫРГЫЗ ТИЛИНДЕ болсун. "
        "Сабактын мазмуну (диалог, мисалдар, тапшырма тексттери) АНГЛИС ТИЛИНДЕ.\n"
        f"Create a short warm-up for a {level} learner:\n"
        "- a 3–4 line mini-dialogue to read and imitate\n"
        "- 3 focused items (grammar/vocab/pronunciation) with 1-line tips\n"
        "- keep it friendly and concise"
    )
    return await gpt(
        [{"role": "system", "content": SYSTEM_STYLE}, {"role": "user", "content": prompt}],
        max_tokens=450
    )

async def build_task(level: str, goals: list) -> Tuple[str, str]:
    """
    Бир эле тапшырма түзөт. Кайтарат: (тапшырма текст/инструкция англисче, текшерүү үчүн кыска ачкыч).
    """
    goals_text = ", ".join(goals) if goals else "general English"
    prompt = (
        "Мета-нускама КЫРГЫЗ ТИЛИНДЕ, бирок тапшырма текстин англисче бер.\n"
        f"Design ONE short exercise for a {level} learner focused on {goals_text}.\n"
        "Output in TWO PARTS exactly:\n"
        "---TASK---\n"
        "<one concise instruction in ENGLISH; student's answer fits in 1–3 lines>\n"
        "---KEY---\n"
        "<ideal answer or checklist for the tutor>"
    )
    out = await gpt(
        [{"role": "system", "content": SYSTEM_STYLE}, {"role": "user", "content": prompt}],
        max_tokens=500
    )
    task, key = "", ""
    if "---TASK---" in out and "---KEY---" in out:
        _, rest = out.split("---TASK---", 1)
        task_part, key_part = rest.split("---KEY---", 1)
        task = task_part.strip()
        key = key_part.strip()
    else:
        task = out.strip()
        key = "No formal key; judge clarity, grammar, relevance."
    return task, key

async def check_answer(level: str, task: str, key: str, answer: str) -> str:
    """Кыргызча кыска пикир."""
    prompt = (
        "Баалоону КЫРГЫЗ ТИЛИНДЕ жаз. Студенттин жообу англисче.\n"
        f"Student level: {level}\n\n"
        f"Task (EN):\n{task}\n\n"
        f"Answer key (EN):\n{key}\n\n"
        f"Student answer (EN):\n{answer}\n\n"
        "Кыска пикир (5 сапка чейин):\n"
        "- тууралыгы (✅/⚠️/❌) жана 1 себеби\n"
        "- 1–2 майда оңдоо (мисал менен)\n"
        "- кийинки кичине тапшырма боюнча сунуш"
    )
    return await gpt(
        [{"role": "system", "content": SYSTEM_STYLE}, {"role": "user", "content": prompt}],
        max_tokens=350
    )

# -------------------- Командалар --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    if not u["level"]:
        await update.message.reply_text(
            "Салам! Алгач деңгээлиңизди тандап алалы:", reply_markup=level_keyboard()
        )
    else:
        await update.message.reply_text(
            "Кайра кош келиңиз! Төмөнкү менюдан тандаңыз:\n\n" + menu_text(u),
            parse_mode="Markdown"
        )

async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    await update.message.reply_text(menu_text(u), parse_mode="Markdown")

async def setlevel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Деңгээлиңизди тандаңыз:", reply_markup=level_keyboard())

async def on_level_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, lvl = q.data.split("|", 1)
    u = userc(q.from_user.id)
    u["level"] = lvl
    save_db(DB)
    await q.edit_message_text(f"Деңгээлиңиз коюлду: *{lvl}* ✅", parse_mode="Markdown")
    await q.message.reply_text(
        "Максаттарды коёсузбу? (мисалы: speaking, grammar, travel)",
        reply_markup=yesno_keyboard("goals|yes", "goals|no")
    )

async def on_goals_yesno(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, ans = q.data.split("|", 1)
    if ans == "yes":
        await q.edit_message_text("Максаттарыңызды үтүр менен жазыңыз. Мис: speaking, travel, pronunciation")
        context.user_data["awaiting_goals"] = True
    else:
        await q.edit_message_text("Максаттарды кийин /goals аркылуу коюуга болот.\n/lesson менен баштай бериңиз.")
        # меню көрсөт
        u = userc(q.from_user.id)
        await q.message.reply_text(menu_text(u), parse_mode="Markdown")

async def goals_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    userc(update.effective_user.id)  # ensure
    await update.message.reply_text("Максаттарыңызды үтүр менен жазыңыз. Мис: speaking, grammar, business email")
    context.user_data["awaiting_goals"] = True

async def lesson_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    if not u["level"]:
        await update.message.reply_text("Адегенде деңгээл коёбуз: /setlevel")
        return
    now = time.time()
    if now - u["last_lesson_ts"] < 10:
        await update.message.reply_text("Бир аз күтө туруңуз… мурдагы өтүнүч иштелүүдө.")
        return

    await update.message.reply_text("Кыска кириш сабак даярдалып жатат…")
    intro = await build_intro_lesson(u["level"])
    await update.message.reply_text(intro)

    task, key = await build_task(u["level"], u["goals"])
    u["pending_task"] = {"task": task, "key": key}
    u["last_lesson_ts"] = now
    save_db(DB)

    await update.message.reply_text(
        f"*Сиздин тапшырмаңыз (EN):*\n{task}\n\nЖообуңузду ушул чатка жазыңыз (бир билдирүү).",
        parse_mode="Markdown"
    )
    # меню
    await update.message.reply_text(menu_text(u), parse_mode="Markdown")

async def repeat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    if u.get("pending_task"):
        await update.message.reply_text(
            f"*Акыркы тапшырма (EN):*\n{u['pending_task']['task']}",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("Акыркы тапшырма табылган жок. /lesson деп жаңы сабак алыңыз.")
    await update.message.reply_text(menu_text(u), parse_mode="Markdown")

async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    DB[str(update.effective_user.id)] = {
        "level": None, "goals": [], "streak": 0,
        "last_lesson_ts": 0, "pending_task": None, "history": []
    }
    save_db(DB)
    await update.message.reply_text("Маалыматыңыз тазаланды. /start деп кайра баштаңыз.")
    await update.message.reply_text(menu_text(userc(update.effective_user.id)), parse_mode="Markdown")

# -------------------- Текст билдирүүлөр --------------------
ALLOWED_WORDS = {"hello", "hi", "ok", "thanks", "thank you"}  # майда реакцияга уруксат

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    u = userc(uid)
    txt = (update.message.text or "").strip()

    # Максаттарды кабыл алуу
    if context.user_data.get("awaiting_goals"):
        goals = [g.strip() for g in txt.split(",") if g.strip()]
        u["goals"] = goals
        context.user_data["awaiting_goals"] = False
        save_db(DB)
        await update.message.reply_text(
            f"Максаттар сакталды: {', '.join(goals) if goals else 'жок'}. Эми /lesson деп баштасаңыз болот."
        )
        await update.message.reply_text(menu_text(u), parse_mode="Markdown")
        return

    # Тапшырмага жооп келдиби?
    if u.get("pending_task"):
        task = u["pending_task"]["task"]
        key = u["pending_task"]["key"]
        await update.message.reply_text("Жообуңуз текшерилип жатат…")
        fb = await check_answer(u["level"], task, key, txt)
        u["pending_task"] = None
        u["streak"] = int(u.get("streak", 0)) + 1
        save_db(DB)
        await update.message.reply_text(fb)
        await update.message.reply_text(menu_text(u), parse_mode="Markdown")
        return

    # Эркин текст: гана окуу тууралуу суроолорго түшүндүрмө (башка темаларга барбайбыз)
    if any(cmd in txt.lower() for cmd in ["/", "setlevel", "lesson", "goals", "menu", "reset", "repeat"]) \
       or txt.lower() in ALLOWED_WORDS:
        # жөн гана меню эсиңизге салайын:
        await update.message.reply_text(menu_text(u), parse_mode="Markdown")
        return

    # Болбосо — кыска эскертме
    await update.message.reply_text(
        "Бул бот англис тилин үйрөтөт. Командаларды колдонуңуз: /menu\n"
        "Жаңы сабак үчүн: /lesson"
    )
    await update.message.reply_text(menu_text(u), parse_mode="Markdown")

# -------------------- main --------------------
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or not OPENAI_API_KEY:
        print("❌ .env ичинде TELEGRAM_BOT_TOKEN же OPENAI_API_KEY жок")
        return

    app = ApplicationBuilder().token(token).build()

    # Командалар
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("setlevel", setlevel))
    app.add_handler(CommandHandler("goals", goals_cmd))
    app.add_handler(CommandHandler("lesson", lesson_cmd))
    app.add_handler(CommandHandler("repeat", repeat_cmd))
    app.add_handler(CommandHandler("reset", reset_cmd))

    # Callback'тар
    app.add_handler(CallbackQueryHandler(on_level_pick, pattern=r"^level\|"))
    app.add_handler(CallbackQueryHandler(on_goals_yesno, pattern=r"^goals\|"))

    # Текст
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("✅ Tutor bot is running. Press Ctrl+C to stop.")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
