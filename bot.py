# bot.py — Telegram bot (RU + UZ) с хранением участников в CSV (без SQLite)

import os
import csv
import logging
import threading
from datetime import datetime
from typing import Dict, List, Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------- ЛОГИ ----------
logging.basicConfig(
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- КОНФИГ ----------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")  # "-100..." или "@mychannel"
ADMIN_IDS: List[int] = [
    int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x
]

MODE = os.environ.get("MODE", "auto")   # auto|webhook|polling
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
PORT = int(os.environ.get("PORT", "10000"))

# Путь к CSV с участниками
CSV_PATH = os.environ.get("CSV_PATH", "participants.csv")

# ---------- i18n ----------
LANGS = ("ru", "uz")
I18N = {
    "ru": {
        "start": "Привет! Я фиксирую участие в розыгрышах. "
                 "Нажимай кнопку \"Участвую\" под постами в канале, чтобы попасть в список участников.\n\n"
                 "Команды:\n"
                 "/lang — выбрать язык\n"
                 "/post <ru|uz> <текст> — опубликовать пост в канале\n"
                 "/stats — количество участников\n"
                 "/export — выгрузка CSV",
        "choose_lang": "Выберите язык / Tilni tanlang:",
        "lang_set": "Язык сохранён: Русский 🇷🇺",
        "post_default": "🎉 Розыгрыш! Нажмите \"Участвую\" ниже, чтобы попасть в список.",
        "participate_button": "✅ Участвую | Ishtirok etaman",
        "participation_ok": "Вы учтены ✅ Удачи!",
        "not_admin": "Команда доступна только администраторам.",
        "posted": "Пост отправлен в канал (message_id={mid}).",
        "stats": "Всего участников в базе: <b>{n}</b>",
        "help": "Команды:\n"
                "/start — активировать бота\n"
                "/lang — выбрать язык\n"
                "/post <ru|uz> <текст> — (админ) пост с кнопкой\n"
                "/stats — (админ) количество участников\n"
                "/export — (админ) выгрузка CSV\n"
                "/ping — проверка",
    },
    "uz": {
        "start": "Salom! Kanal postlari ostidagi \"Ishtirok etaman\" tugmasini bosib, ishtirokingiz qayd etiladi.\n\n"
                 "Buyruqlar:\n"
                 "/lang — tilni tanlash\n"
                 "/post <ru|uz> <matn> — kanalda post chiqarish\n"
                 "/stats — ishtirokchilar soni\n"
                 "/export — CSV yuklab olish",
        "choose_lang": "Tilni tanlang / Выберите язык:",
        "lang_set": "Til saqlandi: Oʻzbekcha 🇺🇿",
        "post_default": "🎉 Tanlov! Roʻyxatga tushish uchun pastdagi \"Ishtirok etaman\" tugmasini bosing.",
        "participate_button": "✅ Ishtirok etaman | Участвую",
        "participation_ok": "Ishtirokingiz qayd etildi ✅ Omad!",
        "not_admin": "Bu buyruq faqat administratorlar uchun.",
        "posted": "Post kanalga yuborildi (message_id={mid}).",
        "stats": "Bazadagi ishtirokchilar soni: <b>{n}</b>",
        "help": "Buyruqlar:\n"
                "/start — botni ishga tushirish\n"
                "/lang — tilni tanlash\n"
                "/post <ru|uz> <matn> — (admin) tugmali post\n"
                "/stats — (admin) ishtirokchilar soni\n"
                "/export — (admin) CSV yuklab olish\n"
                "/ping — tekshirish",
    },
}
def t(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in I18N else "ru"
    s = I18N[lang].get(key, I18N["ru"].get(key, key))
    return s.format(**kwargs)

# ---------- ХРАНИЛИЩЕ CSV ----------
CSV_HEADER = ["user_id", "username", "full_name", "first_seen", "last_participated", "source", "lang"]
_store_lock = threading.Lock()

def _ensure_csv():
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADER)

def _load_participants() -> Dict[str, Dict[str, str]]:
    _ensure_csv()
    data: Dict[str, Dict[str, str]] = {}
    with open(CSV_PATH, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            data[row["user_id"]] = row
    return data

def _save_participants(data: Dict[str, Dict[str, str]]):
    tmp = CSV_PATH + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        for row in data.values():
            writer.writerow(row)
    os.replace(tmp, CSV_PATH)

def get_user_lang(user_id: int) -> str:
    with _store_lock:
        data = _load_participants()
        row = data.get(str(user_id))
        if row and row.get("lang") in LANGS:
            return row["lang"]
    return "ru"

def upsert_participant(user_id: int, username: str, full_name: str, source: str, lang: Optional[str] = None) -> None:
    now = datetime.utcnow().isoformat()
    with _store_lock:
        data = _load_participants()
        key = str(user_id)
        row = data.get(key)
        if row:
            row["username"] = username or ""
            row["full_name"] = full_name or ""
            row["last_participated"] = now
            row["source"] = source
            if lang in LANGS:
                row["lang"] = lang
        else:
            data[key] = {
                "user_id": key,
                "username": username or "",
                "full_name": full_name or "",
                "first_seen": now,
                "last_participated": now,
                "source": source,
                "lang": lang if lang in LANGS else "ru",
            }
        _save_participants(data)

def set_user_lang(user_id: int, lang: str) -> None:
    if lang not in LANGS:
        lang = "ru"
    now = datetime.utcnow().isoformat()
    with _store_lock:
        data = _load_participants()
        key = str(user_id)
        row = data.get(key)
        if row:
            row["lang"] = lang
        else:
            data[key] = {
                "user_id": key,
                "username": "",
                "full_name": "",
                "first_seen": now,
                "last_participated": now,
                "source": "lang",
                "lang": lang,
            }
        _save_participants(data)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ---------- HANDLERS ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    lang = get_user_lang(user.id)
    upsert_participant(
        user_id=user.id,
        username=user.username or "",
        full_name=(user.full_name or "").strip(),
        source="/start",
        lang=lang,
    )
    await update.message.reply_text(t(lang, "start"))

async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    lang = get_user_lang(user.id)
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Русский 🇷🇺", callback_data="setlang:ru"),
         InlineKeyboardButton("Oʻzbekcha 🇺🇿", callback_data="setlang:uz")]
    ])
    await update.message.reply_text(t(lang, "choose_lang"), reply_markup=kb)

async def on_setlang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()
    lang_code = q.data.split(":", 1)[1]
    set_user_lang(q.from_user.id, lang_code)
    msg = I18N["ru"]["lang_set"] if lang_code == "ru" else I18N["uz"]["lang_set"]
    try:
        await q.edit_message_text(msg)
    except Exception:
        await q.message.reply_text(msg)

async def post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin cmd: /post <ru|uz> <text>"""
    user = update.effective_user
    if not user or not is_admin(user.id):
        if update.message:
            await update.message.reply_text(t(get_user_lang(user.id) if user else "ru", "not_admin"))
        return

    # Parse language and text
    if context.args and context.args[0].lower() in LANGS:
        lang_for_post = context.args[0].lower()
        text = " ".join(context.args[1:])
    else:
        lang_for_post = "ru"
        text = " ".join(context.args)

    if not text:
        text = t(lang_for_post, "post_default")

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(t(lang_for_post, "participate_button"), callback_data="participate")]]
    )

    sent = await context.bot.send_message(
        chat_id=CHANNEL_ID,
        text=text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    if update.message:
        await update.message.reply_text(t(lang_for_post, "posted", mid=sent.message_id))

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q:
        return
    await q.answer()

    user = q.from_user
    lang = get_user_lang(user.id)
    upsert_participant(
        user_id=user.id,
        username=user.username or "",
        full_name=(user.full_name or "").strip(),
        source="button",
        lang=lang,
    )

    try:
        await context.bot.send_message(chat_id=user.id, text=t(lang, "participation_ok"))
    except Exception:
        pass

    try:
        await q.edit_message_reply_markup(reply_markup=q.message.reply_markup)
    except Exception:
        pass

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        if update.message:
            await update.message.reply_text(t(get_user_lang(user.id) if user else "ru", "not_admin"))
        return

    with _store_lock:
        data = _load_participants()
        total = len(data)
        by_lang: Dict[str, int] = {"ru": 0, "uz": 0}
        for row in data.values():
            l = row.get("lang") or "ru"
            if l not in by_lang:
                by_lang[l] = 0
            by_lang[l] += 1

    details = ", ".join([f"{k}: {v}" for k, v in by_lang.items() if v > 0])
    await update.message.reply_text(
        t(get_user_lang(user.id), "stats", n=total) + (f"\n{details}" if details else ""),
        parse_mode=ParseMode.HTML
    )

async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or not is_admin(user.id):
        if update.message:
            await update.message.reply_text(t(get_user_lang(user.id) if user else "ru", "not_admin"))
        return

    _ensure_csv()
    await update.message.reply_document(InputFile(CSV_PATH), caption="Export")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_lang(user.id) if user else "ru"
    if update.message:
        await update.message.reply_text(t(lang, "help"))

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        await update.message.reply_text("pong")

# ---------- BOOTSTRAP ----------
def build_app() -> Application:
    if not BOT_TOKEN:
        raise RuntimeError("Set BOT_TOKEN env var")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("lang", cmd_lang))
    app.add_handler(CommandHandler("post", post))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("export", export_csv))
    app.add_handler(CommandHandler("ping", ping))

    app.add_handler(CallbackQueryHandler(on_setlang, pattern="^setlang:"))
    app.add_handler(CallbackQueryHandler(button, pattern="^participate$"))

    app.add_handler(MessageHandler(filters.COMMAND, help_cmd))
    return app

def main():
    app = build_app()

    effective_mode = MODE
    if MODE == "auto":
        effective_mode = "webhook" if WEBHOOK_URL else "polling"

    if effective_mode == "webhook":
        url_path = BOT_TOKEN
        webhook_url = WEBHOOK_URL.rstrip("/") + "/" + url_path
        logger.info(f"Starting WEBHOOK on 0.0.0.0:{PORT}, url_path=/{url_path}")
        logger.info(f"Setting webhook to: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=url_path,
            webhook_url=webhook_url,
            allowed_updates=["message", "callback_query"],
        )
    else:
        # Если крутите на Render в polling — нужен открытый порт (health), иначе используйте webhook.
        logger.info("Starting POLLING mode…")
        app.run_polling(allowed_updates=["message", "callback_query"])

if __name__ == "__main__":
    main()
