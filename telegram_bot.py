"""
Meta Ads Intelligence Pipeline — Telegram Bot

Setup:
  1. Add TELEGRAM_TOKEN and TELEGRAM_CHAT_ID to .env
  2. Run: python3 telegram_bot.py

Commands:
  /scrape Duolingo
  /scrape Duolingo US 10
  /scrape Duolingo --filter video --limit 10 --rank-by age
  /scrape --keyword "capsule wardrobe" --limit 5
  /sync Duolingo
  /sync
  /rename
  /brief
  /brief Duolingo Relatio
  /status
  /help
"""

import asyncio
import subprocess
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ── Load .env ────────────────────────────────────────────────────────────────
def load_env():
    env = {}
    p = Path(__file__).parent / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

ENV = load_env()
TOKEN   = ENV.get("TELEGRAM_TOKEN", "")
CHAT_ID = ENV.get("TELEGRAM_CHAT_ID", "")
SCRIPT_DIR = Path(__file__).parent

_running = False


# ── Auth check ───────────────────────────────────────────────────────────────
def is_owner(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CHAT_ID)


# ── Run subprocess + stream to Telegram ──────────────────────────────────────
async def run_script(label: str, args: list, update: Update):
    global _running
    _running = True

    await update.message.reply_text(f"▶ Starting: {label}...")

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
        # Send in chunks of ~3800 chars to stay under Telegram's 4096 limit
        if len(buffer) >= 3800:
            await update.message.reply_text(f"```\n{buffer}```", parse_mode="Markdown")
            buffer = ""

    await proc.wait()

    if buffer.strip():
        await update.message.reply_text(f"```\n{buffer}```", parse_mode="Markdown")

    status = "✓ Done" if proc.returncode == 0 else f"✗ Exit code {proc.returncode}"
    await update.message.reply_text(status)
    _running = False


# ── Command: /help ────────────────────────────────────────────────────────────
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    text = (
        "*Meta Ads Intelligence Pipeline*\n\n"
        "*Scraper*\n"
        "`/scrape Duolingo` — scrape with defaults (US, limit 5, static)\n"
        "`/scrape Duolingo US 10` — custom country + limit\n"
        "`/scrape Duolingo --filter video --limit 10`\n"
        "`/scrape --keyword \"capsule wardrobe\" --limit 5`\n\n"
        "*Notion*\n"
        "`/sync Duolingo` — sync one app to Notion\n"
        "`/sync` — sync all apps to Notion\n"
        "`/rename` — rename all Notion pages\n\n"
        "*Creative Brief*\n"
        "`/brief` — generate brief for all competitors\n"
        "`/brief Duolingo Relatio` — brief for specific apps\n\n"
        "*Other*\n"
        "`/status` — check if a process is running\n"
        "`/help` — show this message"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ── Command: /status ──────────────────────────────────────────────────────────
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    msg = "⏳ A process is currently running." if _running else "✓ Idle — no process running."
    await update.message.reply_text(msg)


# ── Command: /scrape ──────────────────────────────────────────────────────────
async def cmd_scrape(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if _running:
        await update.message.reply_text("⏳ Already running — wait for it to finish.")
        return

    parts = ctx.args  # everything after /scrape

    # Defaults
    apps      = []
    country   = "US"
    limit     = "5"
    rank_by   = "combined"
    filter_   = "static"
    search_by = "page"

    # Parse flags and positional args
    i = 0
    while i < len(parts):
        p = parts[i]
        if p == "--keyword" and i + 1 < len(parts):
            search_by = "keyword"
            apps = [parts[i + 1]]
            i += 2
        elif p == "--country" and i + 1 < len(parts):
            country = parts[i + 1]; i += 2
        elif p == "--limit" and i + 1 < len(parts):
            limit = parts[i + 1]; i += 2
        elif p == "--rank-by" and i + 1 < len(parts):
            rank_by = parts[i + 1]; i += 2
        elif p == "--filter" and i + 1 < len(parts):
            filter_ = parts[i + 1]; i += 2
        elif p == "--search-by" and i + 1 < len(parts):
            search_by = parts[i + 1]; i += 2
        elif not p.startswith("--"):
            # Positional: first = app, second = country, third = limit
            if not apps:
                apps.append(p)
            elif country == "US" and len(p) == 2:
                country = p.upper()
            elif limit == "5" and p.isdigit():
                limit = p
            i += 1
        else:
            i += 1

    if not apps:
        await update.message.reply_text("Usage: `/scrape AppName [country] [limit]`\nExample: `/scrape Duolingo US 5`", parse_mode="Markdown")
        return

    args = ["meta_ads_scraper.py",
            "--country", country,
            "--limit", limit,
            "--rank-by", rank_by,
            "--filter", filter_,
            "--search-by", search_by] + apps

    label = f"Scrape {', '.join(apps)} ({country}, limit {limit}, {filter_})"
    await run_script(label, args, update)


# ── Command: /sync ────────────────────────────────────────────────────────────
async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if _running:
        await update.message.reply_text("⏳ Already running.")
        return
    args = ["notion_publisher.py"] + (ctx.args or [])
    label = f"Sync {' '.join(ctx.args)}" if ctx.args else "Sync All → Notion"
    await run_script(label, args, update)


# ── Command: /rename ─────────────────────────────────────────────────────────
async def cmd_rename(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if _running:
        await update.message.reply_text("⏳ Already running.")
        return
    await run_script("Rename All Notion Pages", ["notion_publisher.py", "--rename"], update)


# ── Command: /brief ───────────────────────────────────────────────────────────
async def cmd_brief(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update):
        return
    if _running:
        await update.message.reply_text("⏳ Already running.")
        return
    args = ["creative_generator.py"] + (ctx.args or ["--mix", "3"])
    label = f"Creative Brief — {' '.join(ctx.args)}" if ctx.args else "Creative Brief — All"
    await run_script(label, args, update)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    if not TOKEN:
        print("ERROR: TELEGRAM_TOKEN not set in .env")
        sys.exit(1)
    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID not set in .env")
        sys.exit(1)

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",  cmd_help))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("scrape", cmd_scrape))
    app.add_handler(CommandHandler("sync",   cmd_sync))
    app.add_handler(CommandHandler("rename", cmd_rename))
    app.add_handler(CommandHandler("brief",  cmd_brief))

    print("Bot is running. Send /help in Telegram.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
