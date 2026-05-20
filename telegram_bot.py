"""
Meta Ads Intelligence Pipeline — Telegram Bot
Step-by-step command flow with inline buttons.
"""

import asyncio
import sys
from pathlib import Path

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ConversationHandler, ContextTypes, filters,
)

# ── Config ───────────────────────────────────────────────────────────────────
def load_env():
    env = {}
    p = Path(__file__).parent / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ENV        = load_env()
TOKEN      = ENV.get("TELEGRAM_TOKEN", "")
CHAT_ID    = ENV.get("TELEGRAM_CHAT_ID", "")
SCRIPT_DIR = Path(__file__).parent

# Conversation states
(S_SEARCH_BY, S_APP, S_FILTER, S_COUNTRY, S_LIMIT,
 S_SYNC_APP, S_BRIEF_APP) = range(7)


def is_owner(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CHAT_ID)


def kb(buttons: list) -> InlineKeyboardMarkup:
    """Build inline keyboard from list of (label, callback_data) pairs."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d)] for t, d in buttons])


def kb_row(buttons: list) -> InlineKeyboardMarkup:
    """Build inline keyboard with all buttons in one row."""
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in buttons]])


# ── Run subprocess ────────────────────────────────────────────────────────────
async def run_script(label: str, args: list, update: Update):
    await update.effective_message.reply_text(f"▶ *{label}*", parse_mode="Markdown")

    cmd = [sys.executable, str(SCRIPT_DIR / args[0])] + args[1:]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    buffer = ""
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip()
        if not line:
            continue
        buffer += line + "\n"
        if len(buffer) >= 3500:
            await update.effective_message.reply_text(f"```\n{buffer[:3500]}```", parse_mode="Markdown")
            buffer = buffer[3500:]

    await proc.wait()

    if buffer.strip():
        await update.effective_message.reply_text(f"```\n{buffer}```", parse_mode="Markdown")

    result = "✓ *Done*" if proc.returncode == 0 else f"✗ Exit code {proc.returncode}"
    await update.effective_message.reply_text(result, parse_mode="Markdown")


# ══ /scrape flow ═════════════════════════════════════════════════════════════

async def scrape_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return ConversationHandler.END
    ctx.user_data.clear()
    await update.message.reply_text(
        "🔍 *New Scrape*\n\nSearch by:",
        parse_mode="Markdown",
        reply_markup=kb([("📄 Competitor page name", "page"), ("🔑 Keyword in ad copy", "keyword")])
    )
    return S_SEARCH_BY

async def scrape_search_by(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["search_by"] = q.data
    label = "competitor page name" if q.data == "page" else "keyword"
    await q.edit_message_text(f"✅ Search by: *{q.data}*\n\nEnter {label}:", parse_mode="Markdown")
    return S_APP

async def scrape_app(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["app"] = update.message.text.strip()
    await update.message.reply_text(
        f"✅ App/Keyword: *{ctx.user_data['app']}*\n\nSelect creative format:",
        parse_mode="Markdown",
        reply_markup=kb([("🖼 Static (images only)", "static"),
                         ("🎬 Video only",           "video"),
                         ("📦 All formats",          "combined")])
    )
    return S_FILTER

async def scrape_filter(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["filter"] = q.data
    await q.edit_message_text(
        f"✅ Format: *{q.data}*\n\nSelect country:",
        parse_mode="Markdown",
        reply_markup=kb_row([("🇺🇸 US", "US"), ("🇬🇧 UK", "GB"),
                             ("🇺🇦 UA", "UA"), ("🌍 All", "ALL")])
    )
    return S_COUNTRY

async def scrape_country(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    ctx.user_data["country"] = q.data
    await q.edit_message_text(
        f"✅ Country: *{q.data}*\n\nHow many ads? (enter a number, e.g. 5):",
        parse_mode="Markdown"
    )
    return S_LIMIT

async def scrape_limit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ Enter a number (e.g. 5):")
        return S_LIMIT

    ctx.user_data["limit"] = text
    d = ctx.user_data
    summary = (
        f"*Ready to scrape:*\n"
        f"• App/Keyword: `{d['app']}`\n"
        f"• Search by: `{d['search_by']}`\n"
        f"• Format: `{d['filter']}`\n"
        f"• Country: `{d['country']}`\n"
        f"• Limit: `{d['limit']}`"
    )
    await update.message.reply_text(
        summary,
        parse_mode="Markdown",
        reply_markup=kb_row([("✅ Run", "run"), ("❌ Cancel", "cancel")])
    )
    return S_LIMIT

async def scrape_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "cancel":
        await q.edit_message_text("❌ Cancelled.")
        return ConversationHandler.END

    d = ctx.user_data
    await q.edit_message_text("⏳ Starting...")
    args = ["meta_ads_scraper.py",
            "--country",   d["country"],
            "--limit",     d["limit"],
            "--rank-by",   "combined",
            "--filter",    d["filter"],
            "--search-by", d["search_by"],
            d["app"]]
    await run_script(f"Scraping {d['app']}", args, update)
    return ConversationHandler.END


# ══ /sync flow ════════════════════════════════════════════════════════════════

async def sync_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return ConversationHandler.END
    await update.message.reply_text(
        "🔄 *Sync to Notion*\n\nSync which app?",
        parse_mode="Markdown",
        reply_markup=kb([("📋 All apps", "all"), ("✏️ Enter app name", "specific")])
    )
    return S_SYNC_APP

async def sync_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "all":
        await q.edit_message_text("⏳ Syncing all apps...")
        await run_script("Sync All → Notion", ["notion_publisher.py"], update)
        return ConversationHandler.END
    await q.edit_message_text("Enter app name:")
    return S_SYNC_APP

async def sync_app(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    app = update.message.text.strip()
    await run_script(f"Sync {app} → Notion", ["notion_publisher.py", app], update)
    return ConversationHandler.END


# ══ /brief flow ═══════════════════════════════════════════════════════════════

async def brief_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return ConversationHandler.END
    await update.message.reply_text(
        "✦ *Generate Creative Brief*\n\nFor which competitors?",
        parse_mode="Markdown",
        reply_markup=kb([("🌐 All competitors (mix 3)", "all"), ("✏️ Enter specific apps", "specific")])
    )
    return S_BRIEF_APP

async def brief_choice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "all":
        await q.edit_message_text("⏳ Generating brief...")
        await run_script("Creative Brief — All", ["creative_generator.py", "--mix", "3"], update)
        return ConversationHandler.END
    await q.edit_message_text("Enter app names separated by spaces (e.g. Duolingo Relatio):")
    return S_BRIEF_APP

async def brief_apps(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    apps = update.message.text.strip().split()
    await run_script(f"Creative Brief — {' '.join(apps)}",
                     ["creative_generator.py"] + apps, update)
    return ConversationHandler.END


# ══ Simple commands ══════════════════════════════════════════════════════════

async def cmd_rename(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    await run_script("Rename All Notion Pages", ["notion_publisher.py", "--rename"], update)

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return
    await update.message.reply_text(
        "*Meta Ads Intelligence Pipeline*\n\n"
        "/scrape — step-by-step scraper setup\n"
        "/sync — sync to Notion (all or one app)\n"
        "/brief — generate AI creative brief\n"
        "/rename — rename all Notion pages\n"
        "/cancel — cancel current flow\n"
        "/help — show this message",
        parse_mode="Markdown"
    )

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update): return ConversationHandler.END
    await update.message.reply_text("❌ Cancelled.")
    return ConversationHandler.END


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not TOKEN or not CHAT_ID:
        print("ERROR: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set in .env")
        sys.exit(1)

    app = Application.builder().token(TOKEN).build()

    scrape_conv = ConversationHandler(
        entry_points=[CommandHandler("scrape", scrape_start)],
        states={
            S_SEARCH_BY: [CallbackQueryHandler(scrape_search_by)],
            S_APP:       [MessageHandler(filters.TEXT & ~filters.COMMAND, scrape_app)],
            S_FILTER:    [CallbackQueryHandler(scrape_filter)],
            S_COUNTRY:   [CallbackQueryHandler(scrape_country)],
            S_LIMIT:     [MessageHandler(filters.TEXT & ~filters.COMMAND, scrape_limit),
                          CallbackQueryHandler(scrape_confirm)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    sync_conv = ConversationHandler(
        entry_points=[CommandHandler("sync", sync_start)],
        states={
            S_SYNC_APP: [CallbackQueryHandler(sync_choice),
                         MessageHandler(filters.TEXT & ~filters.COMMAND, sync_app)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    brief_conv = ConversationHandler(
        entry_points=[CommandHandler("brief", brief_start)],
        states={
            S_BRIEF_APP: [CallbackQueryHandler(brief_choice),
                          MessageHandler(filters.TEXT & ~filters.COMMAND, brief_apps)],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
    )

    app.add_handler(scrape_conv)
    app.add_handler(sync_conv)
    app.add_handler(brief_conv)
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("start",  cmd_help))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("cancel", cmd_cancel))

    print("Bot is running. Send /help in Telegram.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
