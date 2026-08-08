import logging
import os
import secrets
import sqlite3
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
ANNOUNCEMENT_CHAT_ID = int(os.environ.get("ANNOUNCEMENT_CHAT_ID", "0"))

TZ = ZoneInfo("Africa/Johannesburg")
ENTRY_PRICE = 30
MIN_NUMBER = 1
MAX_NUMBER = 120
DB_PATH = os.environ.get("DB_PATH", "lotto.db")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("daily-lotto")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                draw_date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                username TEXT,
                first_name TEXT,
                number INTEGER NOT NULL,
                selected_at TEXT NOT NULL,
                payment_status TEXT NOT NULL DEFAULT 'pending',
                paid_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS draws (
                draw_date TEXT PRIMARY KEY,
                winning_number INTEGER NOT NULL,
                drawn_at TEXT NOT NULL,
                winner_count INTEGER NOT NULL DEFAULT 0,
                prize_pool INTEGER NOT NULL DEFAULT 0
            )
        """)


def now():
    return datetime.now(TZ)


def today_str():
    return now().date().isoformat()


def next_draw_date():
    """Selections made between midnight and 5 PM belong to today's 8 PM draw."""
    return today_str()


def selection_open():
    return time(0, 0) <= now().time() < time(17, 0)


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯  SELECT YOUR NUMBER  🎯", callback_data="numbers")],
        [
            InlineKeyboardButton("🎟️ MY TICKETS", callback_data="mytickets"),
            InlineKeyboardButton("🏆 DRAW RESULT", callback_data="today"),
        ],
        [
            InlineKeyboardButton("💰 PRIZE INFO", callback_data="prize"),
            InlineKeyboardButton("📖 HOW TO PLAY", callback_data="how"),
        ],
    ])


def number_keyboard():
    rows, row = [], []
    for n in range(MIN_NUMBER, MAX_NUMBER + 1):
        row.append(InlineKeyboardButton(f"🔵 {n}", callback_data=f"pick:{n}"))
        if len(row) == 6:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 BACK TO MENU", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def home_text():
    return (
        "🎰✨ *TELEGRAM DAILY LOTTO* ✨🎰\n\n"
        "🎟️ *R30 per ticket*\n"
        "🔢 Pick your lucky number: *1–120*\n\n"
        "🟢 *SELECTIONS OPEN*\n"
        "🌙 12:00 AM → 🕔 5:00 PM\n"
        "🎲 Draw: 🕗 8:00 PM\n\n"
        "🍀 Good luck and play responsibly! 🍀\n\n"
        "👇 *Choose an option below:*"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        home_text(), parse_mode="Markdown", reply_markup=menu()
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = next_draw_date()
    with db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) c FROM tickets WHERE draw_date=?", (d,)
        ).fetchone()["c"]
        mine = conn.execute(
            "SELECT COUNT(*) c FROM tickets WHERE draw_date=? AND user_id=?",
            (d, update.effective_user.id),
        ).fetchone()["c"]
        paid = conn.execute(
            "SELECT COUNT(*) c FROM tickets WHERE draw_date=? AND payment_status='paid'",
            (d,),
        ).fetchone()["c"]

    await update.effective_message.reply_text(
        f"📊 *TODAY'S LOTTO STATUS*\n\n"
        f"🎟️ Total tickets: *{total}*\n"
        f"🎫 Your tickets: *{mine}*\n"
        f"✅ Paid tickets: *{paid}*\n"
        f"💰 Gross paid entries: *R{paid * ENTRY_PRICE:,}*\n\n"
        f"🟢 Selection window: *12:00 AM–5:00 PM*\n"
        f"🎲 Draw: *8:00 PM*",
        parse_mode="Markdown",
    )


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute(
            "SELECT draw_date, winning_number, winner_count "
            "FROM draws ORDER BY draw_date DESC LIMIT 10"
        ).fetchall()

    if not rows:
        await update.effective_message.reply_text("📜 No completed draws yet.")
        return

    lines = ["📜 *RECENT DRAW RESULTS*"]
    for r in rows:
        lines.append(
            f"📅 {r['draw_date']}  •  🎱 *{r['winning_number']}*  "
            f"•  🏆 {r['winner_count']} winner(s)"
        )
    await update.effective_message.reply_text(
        "\n".join(lines), parse_mode="Markdown"
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    user = q.from_user

    if data == "home":
        await q.edit_message_text(
            home_text(), parse_mode="Markdown", reply_markup=menu()
        )
        return

    if data == "numbers":
        if not selection_open():
            await q.edit_message_text(
                "⛔ *SELECTIONS ARE CLOSED*\n\n"
                "🕔 Numbers can be selected every day from "
                "*12:00 AM until 5:00 PM*.\n\n"
                "🎲 Today's draw is at *8:00 PM*.\n"
                "🌙 Come back after midnight for the next selection window.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🏠 HOME", callback_data="home")]]
                ),
            )
            return

        await q.edit_message_text(
            "🎯✨ *CHOOSE YOUR LUCKY NUMBER* ✨🎯\n\n"
            "🔢 Pick one or more numbers from *1–120*.\n"
            "🎟️ Each ticket costs *R30*.\n\n"
            "🕔 Selection closes at *5:00 PM*.",
            parse_mode="Markdown",
            reply_markup=number_keyboard(),
        )
        return

    if data.startswith("pick:"):
        if not selection_open():
            await q.answer("Selections are closed at 5:00 PM.", show_alert=True)
            return

        number = int(data.split(":", 1)[1])
        d = next_draw_date()
        selected_at = now().isoformat()

        with db() as conn:
            cur = conn.execute(
                """INSERT INTO tickets
                   (draw_date,user_id,username,first_name,number,selected_at)
                   VALUES (?,?,?,?,?,?)""",
                (d, user.id, user.username, user.first_name, number, selected_at),
            )
            ticket_id = cur.lastrowid

        await q.answer(f"🎉 Number {number} selected!", show_alert=True)
        await q.edit_message_text(
            f"🎉 *TICKET CREATED!*\n\n"
            f"🎟️ Ticket: *#{ticket_id}*\n"
            f"🔢 Lucky number: *{number}*\n"
            f"💰 Ticket price: *R{ENTRY_PRICE}*\n"
            f"⏳ Status: *PENDING PAYMENT*\n\n"
            f"🕔 Pay/confirm before *5:00 PM*.\n"
            f"🎲 Draw: *8:00 PM*.\n\n"
            f"🍀 Good luck! 🍀",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎯 PICK ANOTHER NUMBER", callback_data="numbers")],
                [InlineKeyboardButton("🎟️ MY TICKETS", callback_data="mytickets")],
                [InlineKeyboardButton("🏠 MENU", callback_data="home")],
            ]),
        )
        return

    if data == "mytickets":
        d = next_draw_date()
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE draw_date=? AND user_id=? ORDER BY id DESC",
                (d, user.id),
            ).fetchall()

        if not rows:
            text = "🎟️ *NO TICKETS YET*\n\nPick a lucky number to enter today's draw."
        else:
            lines = ["🎟️ *YOUR TICKETS*\n"]
            for r in rows:
                icon = "✅" if r["payment_status"] == "paid" else "⏳"
                lines.append(
                    f"{icon} Ticket *#{r['id']}*  •  🔢 Number *{r['number']}*  "
                    f"•  {r['payment_status'].upper()}"
                )
            text = "\n".join(lines)

        await q.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 HOME", callback_data="home")]]
            ),
        )
        return

    if data == "today":
        d = today_str()
        with db() as conn:
            draw = conn.execute(
                "SELECT * FROM draws WHERE draw_date=?", (d,)
            ).fetchone()
            total = conn.execute(
                "SELECT COUNT(*) c FROM tickets WHERE draw_date=? AND payment_status='paid'",
                (d,),
            ).fetchone()["c"]

        if draw:
            text = (
                "🏆✨ *TODAY'S DRAW RESULT* ✨🏆\n\n"
                f"🎱 Winning number: *{draw['winning_number']}*\n"
                f"🏆 Matching tickets: *{draw['winner_count']}*\n"
                f"🎟️ Paid entries: *{total}*\n\n"
                "📢 Winners should contact the admin through the "
                "official LOTTO ANNOUNCEMENT channel to arrange their prize."
            )
        else:
            text = (
                "🏆 *TODAY'S DRAW*\n\n"
                "🎱 Winning number: *Not drawn yet*\n\n"
                "🕔 Selections: *12:00 AM–5:00 PM*\n"
                "🎲 Draw time: *8:00 PM*\n\n"
                "🤖 The bot randomly selects the winning number."
            )

        await q.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 HOME", callback_data="home")]]
            ),
        )
        return

    if data == "prize":
        await q.edit_message_text(
            "💰✨ *PRIZE POOL* ✨💰\n\n"
            "🎟️ Every ticket is *R30*.\n"
            "👥 The prize pool depends on the number of paid entries.\n"
            "🏆 If multiple paid tickets match the winning number, "
            "the announced prize pool is divided equally between those winners.\n\n"
            "📢 The final prize pool can be announced in the "
            "LOTTO ANNOUNCEMENT channel before the draw.\n\n"
            "⚠️ Prize calculations and payments are handled by the admin.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 HOME", callback_data="home")]]
            ),
        )
        return

    if data == "how":
        await q.edit_message_text(
            "📖✨ *HOW TO PLAY* ✨📖\n\n"
            "1️⃣ Choose a number from *1–120*.\n"
            "2️⃣ Each ticket costs *R30*.\n"
            "3️⃣ Selection/payment closes at *5:00 PM*.\n"
            "4️⃣ The bot randomly draws one winning number at *8:00 PM*.\n"
            "5️⃣ Paid tickets matching that number are winners.\n"
            "6️⃣ If there are multiple winners, the announced prize pool is split equally.\n"
            "7️⃣ Winners contact the admin through the official LOTTO ANNOUNCEMENT channel.\n\n"
            "🍀 Good luck! Play responsibly.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🏠 HOME", callback_data="home")]]
            ),
        )


async def admin_only(update: Update):
    return (
        ADMIN_ID != 0
        and update.effective_user
        and update.effective_user.id == ADMIN_ID
    )


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: /approve TICKET_ID")
        return

    ticket_id = int(context.args[0])
    with db() as conn:
        conn.execute(
            "UPDATE tickets SET payment_status='paid', paid_at=? WHERE id=?",
            (now().isoformat(), ticket_id),
        )
    await update.effective_message.reply_text(
        f"✅ Ticket #{ticket_id} marked as PAID."
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return

    d = next_draw_date()
    with db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) c FROM tickets WHERE draw_date=?", (d,)
        ).fetchone()["c"]
        paid = conn.execute(
            "SELECT COUNT(*) c FROM tickets WHERE draw_date=? AND payment_status='paid'",
            (d,),
        ).fetchone()["c"]
        pending = conn.execute(
            "SELECT COUNT(*) c FROM tickets WHERE draw_date=? AND payment_status='pending'",
            (d,),
        ).fetchone()["c"]

    await update.effective_message.reply_text(
        f"📊 *ADMIN LOTTO STATS*\n\n"
        f"🎟️ Tickets: *{total}*\n"
        f"✅ Paid: *{paid}*\n"
        f"⏳ Pending: *{pending}*\n"
        f"💰 Gross paid entries: *R{paid * ENTRY_PRICE:,}*\n\n"
        f"🕔 Selection deadline: *5:00 PM*\n"
        f"🎲 Draw: *8:00 PM*",
        parse_mode="Markdown",
    )


async def setchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return

    await update.effective_message.reply_text(
        f"📢 This chat's ID is:\n`{update.effective_chat.id}`\n\n"
        "Use this as ANNOUNCEMENT_CHAT_ID in Render.",
        parse_mode="Markdown",
    )


async def draw_job(context: ContextTypes.DEFAULT_TYPE):
    d = today_str()

    with db() as conn:
        if conn.execute(
            "SELECT 1 FROM draws WHERE draw_date=?", (d,)
        ).fetchone():
            return

        paid = conn.execute(
            "SELECT * FROM tickets WHERE draw_date=? AND payment_status='paid' "
            "ORDER BY selected_at ASC",
            (d,),
        ).fetchall()

        if not paid:
            log.info("No paid tickets for %s; no draw recorded.", d)
            return

        winning = secrets.randbelow(MAX_NUMBER) + 1
        winners = [r for r in paid if r["number"] == winning]

        conn.execute(
            """INSERT INTO draws
               (draw_date,winning_number,drawn_at,winner_count,prize_pool)
               VALUES(?,?,?,?,?)""",
            (d, winning, now().isoformat(), len(winners), 0),
        )

    lines = [
        "🎰✨ *DAILY LOTTO — DRAW RESULT* ✨🎰",
        "",
        f"🎱 Winning number: *{winning}*",
        f"🎟️ Paid entries: *{len(paid)}*",
        f"🏆 Matching tickets: *{len(winners)}*",
        "",
    ]

    if winners:
        lines += [
            "🎉 *WINNING TICKETS*",
            "",
        ]
        for r in winners[:50]:
            name = r["first_name"] or r["username"] or "Player"
            lines.append(f"🏆 Ticket #{r['id']} — {name}")

        lines += [
            "",
            "💰 The announced prize pool is divided equally between matching winners.",
            "📢 Winners should contact the admin through the official LOTTO ANNOUNCEMENT channel.",
        ]
    else:
        lines.append("😔 No paid ticket matched today's winning number.")

    message = "\n".join(lines)

    if ANNOUNCEMENT_CHAT_ID:
        await context.bot.send_message(
            chat_id=ANNOUNCEMENT_CHAT_ID,
            text=message,
            parse_mode="Markdown",
        )

    if ADMIN_ID:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=message,
            parse_mode="Markdown",
        )


async def post_init(app):
    if app.job_queue:
        app.job_queue.run_daily(
            draw_job,
            time=time(20, 0, tzinfo=TZ),
            name="daily-draw",
        )

    await app.bot.set_my_commands([
        ("start", "Open the Daily Lotto menu"),
        ("status", "See today's status"),
        ("history", "See recent draw results"),
        ("help", "Show help"),
    ])


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing")

    init_db()

    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("setchat", setchat))
    app.add_handler(CallbackQueryHandler(on_button))

    # Polling is used so you do NOT need to configure a webhook or PUBLIC_URL.
    # This also avoids the webhook package requirement that caused the earlier error.
    log.info("Starting Telegram Daily Lotto bot")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
