# bot.py — Kyrgyz→English tutor, text-only, minimal traffic.
# Меню всегда видно. Команды:
# /lesson — следующий урок
# /repeat — повтор текущего
# /review_prev — повтор предыдущего (без отката прогресса)
# /review_next — просмотр следующего (без сдвига прогресса)
# /jump_to N — перейти к уроку №N (в пределах текущего уровня, без запуска; затем /lesson)
# /progress, /setlevel, /reset
# Requires: python-telegram-bot==20.3

import os, json
from pathlib import Path
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

LEVELS = ["Beginner","Elementary","Pre-Intermediate","Intermediate","Upper-Intermediate","Advanced"]
DATA_DIR = Path("data"); DATA_DIR.mkdir(exist_ok=True)
USERS_DB = DATA_DIR / "users.json"
OK_EMOJI, WARN_EMOJI = "✅", "⚠️"

# ---- Мини-курс ----
CURRICULUM: Dict[str, List[Dict[str, Any]]] = {
    "Beginner": [
        {"title":"Greetings & Simple Introductions",
         "expl":"Basic greetings and self-intro. (Саламдашуу жана өзүң жөнүндө кыскача маалымат)",
         "examples":["Hello! My name is Aida.","I am from Bishkek.","Nice to meet you!"],
         "task":"Write a 2-line self-introduction: greet + your name; city or country.",
         "answer_keywords":["my name","i am from","hello","hi"]},
        {"title":"To be (am/is/are) — basics",
            "expl":"Use am/is/are with I/you/he/she/they. (am/is/are — жөнөкөй колдонуу)",
            "examples":["I am a student.","She is a teacher.","They are friends."],
            "task":"Make 2 sentences with am/is/are about you or family.",
            "answer_keywords":[" i am "," is "," are "]},
        {"title":"Everyday objects & a/an",
            "expl":"Use a/an before singular nouns. (a/an — артикль, бирдик санда)",
            "examples":["This is a book.","I have an apple."],
            "task":"Write 2 sentences using a/an with objects around you.",
            "answer_keywords":[" a "," an "]},
    ],
    "Elementary": [
        {"title":"Present Simple (habits)",
         "expl":"Use Present Simple for routines. (Күндөлүк аракеттерге Present Simple)",
         "examples":["I wake up at 7.","She works in a bank."],
         "task":"Write 2 sentences about your daily routine (Present Simple).",
         "answer_keywords":[" i "," she "," he "," every "," usually "," often "]},
        {"title":"There is/There are",
         "expl":"There is/are to talk about existence. (бир нерсенин бар экенин айтуу)",
         "examples":["There is a park near my house.","There are two chairs in the room."],
         "task":"Make 2 sentences: one with 'There is', one with 'There are'.",
         "answer_keywords":["there is","there are"]},
        {"title":"Can (ability)",
         "expl":"Can to express ability. (жөндөмдү айтуу)",
         "examples":["I can swim.","She can speak English."],
         "task":"Write 2 sentences with 'can' about skills.",
         "answer_keywords":[" can "]},
    ],
    "Pre-Intermediate": [
        {"title":"Past Simple (regular/irregular)",
         "expl":"Finished past actions. (Өткөн чак)",
         "examples":["I visited Osh last year.","She went to the market."],
         "task":"Write 2 sentences in Past Simple (one regular, one irregular verb).",
         "answer_keywords":["ed "," went"," did "," saw"," visited"," played"]},
        {"title":"Comparatives",
         "expl":"Use -er/more for comparisons. (салыштыруу формалары)",
         "examples":["Bishkek is bigger than Naryn.","This book is more interesting."],
         "task":"Write 2 comparative sentences.",
         "answer_keywords":[" than"," more "," -er"]},
        {"title":"Future (will / going to)",
         "expl":"Future plans/decisions. (Келечек мезгил)",
         "examples":["I will call you tomorrow.","I am going to study English tonight."],
         "task":"Write 2 future sentences (one with will, one with going to).",
         "answer_keywords":[" will "," going to "]},
    ],
    "Intermediate": [
        {"title":"Present Continuous (now/temporary)",
         "expl":"Actions happening now. (Азыркы уланма мезгил)",
         "examples":["I am studying English now.","They are working on a project."],
         "task":"Write 2 Present Continuous sentences about current actions.",
         "answer_keywords":[" am "," is "," are ","ing"]},
        {"title":"Present Perfect (experience)",
         "expl":"Have/has + V3 for life experience. (тажрыйба)",
         "examples":["I have visited Issyk-Kul.","She has finished her homework."],
         "task":"Write 2 Present Perfect sentences (have/has + V3).",
         "answer_keywords":[" have "," has ","ed"," been"," done"," seen"]},
        {"title":"Modal advice (should)",
         "expl":"Use should for advice. (Кеңеш берүү)",
         "examples":["You should practice every day.","He should sleep more."],
         "task":"Give 2 pieces of advice using 'should'.",
         "answer_keywords":[" should "]},
    ],
    "Upper-Intermediate": [
        {"title":"Conditionals (Type 1)",
         "expl":"If + Present, will + base. (Шарттуу сүйлөм 1-тип)",
         "examples":["If you study, you will improve.","If it rains, we will stay home."],
         "task":"Write 2 Type-1 conditional sentences.",
         "answer_keywords":[" if "," will "]},
        {"title":"Passive Voice (present/past)",
         "expl":"Be + V3. (Пассив)",
         "examples":["English is spoken here.","The house was built in 1990."],
         "task":"Write 2 passive sentences (present & past).",
         "answer_keywords":[" is "," are "," was "," were "," by "]},
        {"title":"Linking words",
         "expl":"Use connectors. (байланыштыруучу сөздөр)",
         "examples":["However, I prefer tea.","Because I was tired, I slept early."],
         "task":"Write 2 sentences with linking words (however/because/therefore).",
         "answer_keywords":["however","because","therefore"]},
    ],
    "Advanced": [
        {"title":"Paraphrasing",
         "expl":"Say same idea differently. (сөзмө-сөз эмес баяндоо)",
         "examples":["The movie was very good. → The film was excellent.",
                     "She is busy. → She has a lot on her plate."],
         "task":"Paraphrase: 'Learning regularly leads to progress.'",
         "answer_keywords":["regular","consist","progress","improve","leads","results"]},
        {"title":"Formal vs Informal",
         "expl":"Choose style by context. (расмий/бейрасмий)",
         "examples":["Formal: I would appreciate your reply.","Informal: Text me back!"],
         "task":"Write 1 formal and 1 informal version of the same request.",
         "answer_keywords":["would","appreciate","please","text","hi","hey"]},
        {"title":"Cohesion & coherence",
         "expl":"Topic sentences and references. (логикалык ыраат)",
         "examples":["Firstly, Secondly, Finally…","This/These/Therefore…"],
         "task":"Write 3–4 lines on ‘Why I learn English’, using at least two linking words.",
         "answer_keywords":["first","second","finally","therefore","because","however"]},
    ],
}

# ---- Storage ----
def load_db() -> Dict[str, Any]:
    if USERS_DB.exists():
        try: return json.loads(USERS_DB.read_text(encoding="utf-8"))
        except Exception: return {}
    return {}

def save_db(db: Dict[str, Any]) -> None:
    tmp = USERS_DB.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(USERS_DB)

# user state:
# level, lesson_idx, pending
# review_mode (bool), review_idx (int|None) — для /review_prev и /review_next
DB = load_db()
def userc(uid: int) -> Dict[str, Any]:
    sid = str(uid)
    if sid not in DB:
        DB[sid] = {"level": None, "lesson_idx": 0, "pending": False, "review_mode": False, "review_idx": None}
    return DB[sid]

# ---- Keyboards ----
def level_kb() -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, lvl in enumerate(LEVELS, 1):
        row.append(InlineKeyboardButton(lvl, callback_data=f"level|{lvl}"))
        if i % 2 == 0: rows.append(row); row = []
    if row: rows.append(row)
    return InlineKeyboardMarkup(rows)

def main_menu_kb() -> ReplyKeyboardMarkup:
    rows = [
        ["/lesson", "/repeat"],
        ["/review_prev", "/review_next"],
        ["/progress", "/setlevel"],
        ["/reset"]
    ]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=False)

# ---- Helpers ----
def tiny(s: str) -> str: return s.strip().replace("\n\n","\n")

def check_keywords(answer: str, keywords: List[str]) -> bool:
    a = " " + answer.lower() + " "
    hit = sum(1 for k in keywords if k in a)
    return hit >= 1 if len(keywords) <= 3 else hit >= 2

def next_lesson_or_level(u: Dict[str, Any]) -> str:
    level, idx = u["level"], u["lesson_idx"] + 1
    lessons = CURRICULUM[level]
    if idx < len(lessons):
        u["lesson_idx"] = idx
        return f"{OK_EMOJI} Good! Next lesson in *{level}* is ready. Tap /lesson."
    pos = LEVELS.index(level)
    if pos + 1 < len(LEVELS):
        new_level = LEVELS[pos + 1]
        u["level"], u["lesson_idx"] = new_level, 0
        return f"{OK_EMOJI} Level *{level}* completed! Moved to *{new_level}*. Tap /lesson."
    return f"{OK_EMOJI} You completed *Advanced*! Great job! Use /lesson to review."

# ---- Commands ----
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Салам! Кыргыз мугалим катары англис тилин үйрөтөм.\nChoose your level:",
        reply_markup=level_kb()
    )

async def setlevel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Choose your level:", reply_markup=level_kb())

async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    if not u["level"]:
        await update.message.reply_text("No level yet. Use /start.", reply_markup=main_menu_kb()); return
    level, idx, total = u["level"], u["lesson_idx"], len(CURRICULUM[u["level"]])
    stat = "waiting for your answer" if u["pending"] else "ready"
    if u["review_mode"]:
        stat = f"reviewing lesson {u['review_idx']+1}"
    await update.message.reply_text(
        f"Level: *{level}*\nLesson: {idx+1}/{total}\nStatus: {stat}",
        parse_mode="Markdown", reply_markup=main_menu_kb()
    )

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    DB[str(update.effective_user.id)] = {"level": None, "lesson_idx": 0, "pending": False, "review_mode": False, "review_idx": None}
    save_db(DB)
    await update.message.reply_text("Data reset. Use /start.", reply_markup=main_menu_kb())

async def on_level_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    _, lvl = q.data.split("|", 1)
    u = userc(q.from_user.id)
    u["level"], u["lesson_idx"] = lvl, 0
    u["pending"], u["review_mode"], u["review_idx"] = False, False, None
    save_db(DB)
    await q.edit_message_text(f"Level set: *{lvl}* ✅", parse_mode="Markdown")
    await q.message.reply_text("Tap /lesson to begin your first lesson.", reply_markup=main_menu_kb())

async def lesson(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    if not u["level"]:
        await update.message.reply_text("Please set your level: /setlevel", reply_markup=main_menu_kb()); return
    if u["pending"]:
        await update.message.reply_text("You have a pending task. Send your answer first.", reply_markup=main_menu_kb()); return

    level, idx = u["level"], u["lesson_idx"]
    lessons = CURRICULUM[level]
    if idx >= len(lessons):
        await update.message.reply_text("Level complete. I will move you forward automatically. /progress", reply_markup=main_menu_kb()); return

    L = lessons[idx]
    u["pending"], u["review_mode"], u["review_idx"] = True, False, None
    save_db(DB)
    text = (
        f"*{level} · Lesson {idx+1}: {L['title']}*\n"
        f"{tiny(L['expl'])}\n\n"
        f"_Examples:_\n- " + "\n- ".join(L["examples"]) + "\n\n"
        f"*Task:* {L['task']}\n\n"
        f"Reply here with your answer (one message)."
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

async def repeat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    if not u["level"]:
        await update.message.reply_text("Please set your level: /setlevel", reply_markup=main_menu_kb()); return
    level, idx = u["level"], u["lesson_idx"]
    lessons = CURRICULUM[level]
    if idx >= len(lessons): idx = len(lessons)-1
    L = lessons[idx]
    u["pending"], u["review_mode"], u["review_idx"] = True, False, None
    save_db(DB)
    text = (
        f"*Repeat — {level} · Lesson {idx+1}: {L['title']}*\n"
        f"{tiny(L['expl'])}\n\n"
        f"_Examples:_\n- " + "\n- ".join(L["examples"]) + "\n\n"
        f"*Task:* {L['task']}\n\n"
        f"Reply again with your answer."
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

async def review_prev_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    if not u["level"]:
        await update.message.reply_text("Please set your level: /setlevel", reply_markup=main_menu_kb()); return
    if u["pending"]:
        await update.message.reply_text("Finish the current task first, then /review_prev.", reply_markup=main_menu_kb()); return

    level, idx = u["level"], u["lesson_idx"]
    if idx == 0:
        await update.message.reply_text("No previous lesson at this level. Start /lesson.", reply_markup=main_menu_kb()); return

    review_idx = idx - 1
    L = CURRICULUM[level][review_idx]
    u["pending"], u["review_mode"], u["review_idx"] = True, True, review_idx
    save_db(DB)
    text = (
        f"*Review Previous — {level} · Lesson {review_idx+1}: {L['title']}*\n"
        f"{tiny(L['expl'])}\n\n"
        f"_Examples:_\n- " + "\n- ".join(L["examples"]) + "\n\n"
        f"*Task:* {L['task']}\n\n"
        f"Reply to review this lesson. (Current progress won't change.)"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

async def review_next_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Посмотреть и отработать СЛЕДУЮЩИЙ урок без сдвига прогресса."""
    u = userc(update.effective_user.id)
    if not u["level"]:
        await update.message.reply_text("Please set your level: /setlevel", reply_markup=main_menu_kb()); return
    if u["pending"]:
        await update.message.reply_text("Finish the current task first, then /review_next.", reply_markup=main_menu_kb()); return

    level, idx = u["level"], u["lesson_idx"]
    lessons = CURRICULUM[level]
    if idx + 1 >= len(lessons):
        await update.message.reply_text("No next lesson to review at this level.", reply_markup=main_menu_kb()); return

    review_idx = idx + 1
    L = lessons[review_idx]
    u["pending"], u["review_mode"], u["review_idx"] = True, True, review_idx
    save_db(DB)
    text = (
        f"*Review Next — {level} · Lesson {review_idx+1}: {L['title']}*\n"
        f"{tiny(L['expl'])}\n\n"
        f"_Examples:_\n- " + "\n- ".join(L["examples"]) + "\n\n"
        f"*Task:* {L['task']}\n\n"
        f"Reply to try the next lesson ahead. (Current progress won't change.)"
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=main_menu_kb())

async def jump_to_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перейти к уроку №N в текущем уровне (без автоматического запуска).
       Пользователь потом жмёт /lesson, чтобы начать именно этот урок."""
    u = userc(update.effective_user.id)
    if not u["level"]:
        await update.message.reply_text("Please set your level: /setlevel", reply_markup=main_menu_kb()); return
    if u["pending"]:
        await update.message.reply_text("Finish the current task first, then /jump_to N.", reply_markup=main_menu_kb()); return

    args = context.args or []
    if not args or not args[0].isdigit():
        await update.message.reply_text("Usage: /jump_to N  (e.g., /jump_to 2)", reply_markup=main_menu_kb()); return

    n = int(args[0])
    lessons = CURRICULUM[u["level"]]
    if not (1 <= n <= len(lessons)):
        await update.message.reply_text(f"Valid range: 1..{len(lessons)}", reply_markup=main_menu_kb()); return

    # set pointer; progress не откатываем и не двигаем автоматически
    u["lesson_idx"] = n - 1
    u["review_mode"], u["review_idx"], u["pending"] = False, None, False
    save_db(DB)
    await update.message.reply_text(
        f"Pointer set to lesson {n}. Tap /lesson to start it.",
        reply_markup=main_menu_kb()
    )

# ---- Answers only ----
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = userc(update.effective_user.id)
    txt = (update.message.text or "").strip()

    if not u["pending"]:
        # Учебный режим: без свободного чата
        await update.message.reply_text("Tap /lesson to get the next task. Use menu below.", reply_markup=main_menu_kb())
        return

    level = u["level"]
    lessons = CURRICULUM[level]

    # Проверка: review_mode (prev/next) или обычный текущий
    if u.get("review_mode"):
        ridx = u.get("review_idx", 0)
        L = lessons[max(0, min(ridx, len(lessons)-1))]
        ok = check_keywords(txt, L["answer_keywords"])
        if ok:
            u["pending"], u["review_mode"], u["review_idx"] = False, False, None
            save_db(DB)
            await update.message.reply_text(
                f"{OK_EMOJI} Good review! (Азаматсың!)\nContinue with your current lesson: /lesson",
                reply_markup=main_menu_kb()
            )
        else:
            await update.message.reply_text(
                f"{WARN_EMOJI} Almost there. Use the target pattern from examples and try again.",
                reply_markup=main_menu_kb()
            )
        return

    # Обычная проверка по текущему уроку
    idx = u["lesson_idx"]
    L = lessons[idx]
    ok = check_keywords(txt, L["answer_keywords"])
    if ok:
        u["pending"] = False
        msg = next_lesson_or_level(u)
        save_db(DB)
        await update.message.reply_text(f"{OK_EMOJI} Good! (Азаматсың!)\n{msg}", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text(
            f"{WARN_EMOJI} Almost there. Use the target pattern from examples and try again.",
            reply_markup=main_menu_kb()
        )

# ---- main ----
def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        print("❌ Missing TELEGRAM_BOT_TOKEN"); return
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setlevel", setlevel))
    app.add_handler(CommandHandler("lesson", lesson))
    app.add_handler(CommandHandler("repeat", repeat_cmd))
    app.add_handler(CommandHandler("review_prev", review_prev_cmd))
    app.add_handler(CommandHandler("review_next", review_next_cmd))
    app.add_handler(CommandHandler("jump_to", jump_to_cmd))
    app.add_handler(CommandHandler("progress", progress))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CallbackQueryHandler(on_level_pick, pattern=r"^level\|"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    print("✅ Tutor bot (Kyrgyz→English) is running.")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
