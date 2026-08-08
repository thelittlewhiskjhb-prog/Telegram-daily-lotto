import logging
import os
import secrets
import sqlite3
from datetime import datetime, time
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
ANNOUNCEMENT_CHAT_ID = int(os.environ.get("ANNOUNCEMENT_CHAT_ID", "0"))

TZ = ZoneInfo("Africa/Johannesburg")
ENTRY_PRICE = 60
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


def today_str():
    return datetime.now(TZ).date().isoformat()


def selection_open():
    return datetime.now(TZ).time() < time(17, 0)


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 SELECT NUMBER", callback_data="numbers")],
        [InlineKeyboardButton("🎟️ MY TICKETS", callback_data="mytickets"),
         InlineKeyboardButton("🏆 TODAY'S DRAW", callback_data="today")],
        [InlineKeyboardButton("📖 HOW IT WORKS", callback_data="how")],
    ])


def number_keyboard():
    rows, row = [], []
    for n in range(MIN_NUMBER, MAX_NUMBER + 1):
        row.append(InlineKeyboardButton(str(n), callback_data=f"pick:{n}"))
        if len(row) == 10:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ BACK", callback_data="home")])
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "🎰 *TELEGRAM DAILY LOTTO*\n\n"
        "🎟️ Entry: *R60 per ticket*\n"
        "🔢 Choose a number from *1–120*\n"
        "🕔 Payment & number selection closes at *5:00 PM*\n"
        "🎲 Daily draw: *8:00 PM*\n\n"
        "Choose an option below.",
        parse_mode="Markdown",
        reply_markup=menu(),
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = today_str()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM tickets WHERE draw_date=?", (d,)).fetchone()["c"]
        mine = conn.execute(
            "SELECT COUNT(*) c FROM tickets WHERE draw_date=? AND user_id=?", (d, update.effective_user.id)
        ).fetchone()["c"]
    await update.effective_message.reply_text(
        f"📊 *Today's status*\n\n🎟️ Total tickets: {total}\n🎫 Your tickets: {mine}\n"
        f"💰 Gross entries: R{total * ENTRY_PRICE:,}\n\n🕔 Deadline: 5:00 PM\n🎲 Draw: 8:00 PM",
        parse_mode="Markdown",
    )


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute(
            "SELECT draw_date, winning_number, winner_count FROM draws ORDER BY draw_date DESC LIMIT 10"
        ).fetchall()
    if not rows:
        await update.effective_message.reply_text("📜 No completed draws yet.")
        return
    lines = ["📜 *Recent Draws*"]
    for r in rows:
        lines.append(f"{r['draw_date']} — 🎱 *{r['winning_number']}* — {r['winner_count']} winner(s)")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    user = q.from_user

    if data == "home":
        await q.edit_message_text(
            "🎰 *Telegram Daily Lotto*\n\nChoose an option:",
            parse_mode="Markdown", reply_markup=menu()
        )
        return

    if data == "numbers":
        if not selection_open():
            await q.edit_message_text(
                "⛔ *Selections are closed for today.*\n\nPayment and number selection close at 5:00 PM every day.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="home")]]),
            )
            return
        await q.edit_message_text(
            "🎯 *CHOOSE YOUR LUCKY NUMBER*\n\nPick any number from *1 to 120*.\n\nEach ticket costs *R60*.",
            parse_mode="Markdown", reply_markup=number_keyboard()
        )
        return

    if data.startswith("pick:"):
        if not selection_open():
            await q.answer("Selections closed at 5:00 PM.", show_alert=True)
            return
        number = int(data.split(":", 1)[1])
        d = today_str()
        selected_at = datetime.now(TZ).isoformat()
        with db() as conn:
            cur = conn.execute(
                """INSERT INTO tickets
                   (draw_date,user_id,username,first_name,number,selected_at)
                   VALUES (?,?,?,?,?,?)""",
                (d, user.id, user.username, user.first_name, number, selected_at),
            )
            ticket_id = cur.lastrowid

        await q.answer(f"Number {number} selected!", show_alert=True)
        await q.edit_message_text(
            f"✅ *NUMBER SELECTED*\n\n"
            f"🎟️ Ticket: *#{ticket_id}*\n"
            f"🔢 Number: *{number}*\n"
            f"💰 Amount due: *R{ENTRY_PRICE}*\n\n"
            f"⚠️ Your ticket remains *PENDING* until payment is confirmed.\n"
            f"🕔 Payment & selection deadline: 5:00 PM.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎯 CHOOSE ANOTHER NUMBER", callback_data="numbers")],
                [InlineKeyboardButton("🏠 MENU", callback_data="home")]
            ]),
        )
        return

    if data == "mytickets":
        d = today_str()
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE draw_date=? AND user_id=? ORDER BY id DESC",
                (d, user.id),
            ).fetchall()
        if not rows:
            text = "🎟️ *You have no tickets for today's draw.*"
        else:
            text = "🎟️ *YOUR TICKETS*\n\n" + "\n".join(
                f"🎟️ Ticket #{r['id']} — Number {r['number']} — {r['payment_status'].upper()}"
                for r in rows
            )
        await q.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="home")]])
        )
        return

    if data == "today":
        d = today_str()
        with db() as conn:
            draw = conn.execute("SELECT * FROM draws WHERE draw_date=?", (d,)).fetchone()
            total = conn.execute(
                "SELECT COUNT(*) c FROM tickets WHERE draw_date=? AND payment_status='paid'", (d,)
            ).fetchone()["c"]
        if draw:
            text = (
                f"🏆 *TODAY'S RESULT*\n\n"
                f"🎱 Winning number: *{draw['winning_number']}*\n"
                f"👥 Winners: *{draw['winner_count']}*\n"
                f"🎟️ Paid entries: *{total}*"
            )
        else:
            text = (
                "🏆 *TODAY'S DRAW*\n\n"
                "🎱 Winning number: *Not drawn yet*\n"
                "🕔 Selections close: 5:00 PM\n"
                "🎲 Draw time: 8:00 PM"
            )
        await q.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="home")]])
        )
        return

    if data == "how":
        await q.edit_message_text(
            "📖 *HOW IT WORKS*\n\n"
            "1️⃣ Choose a number from 1–120.\n"
            "2️⃣ Each ticket is R60.\n"
            "3️⃣ Payment and number selection must be completed by 5:00 PM.\n"
            "4️⃣ At 8:00 PM the bot randomly selects one winning number.\n"
            "5️⃣ Winners are identified from eligible paid tickets.\n"
            "6️⃣ Matching tickets are ranked by their selection time for the published payout structure.\n\n"
            "Payment confirmation is kept separate until a compliant payment integration is connected.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="home")]])
        )


async def admin_only(update: Update):
    return ADMIN_ID != 0 and update.effective_user and update.effective_user.id == ADMIN_ID


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
            (datetime.now(TZ).isoformat(), ticket_id)
        )
    await update.effective_message.reply_text(f"✅ Ticket #{ticket_id} marked PAID.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return
    d = today_str()
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM tickets WHERE draw_date=?", (d,)).fetchone()["c"]
        paid = conn.execute(
            "SELECT COUNT(*) c FROM tickets WHERE draw_date=? AND payment_status='paid'", (d,)
        ).fetchone()["c"]
        pending = conn.execute(
            "SELECT COUNT(*) c FROM tickets WHERE draw_date=? AND payment_status='pending'", (d,)
        ).fetchone()["c"]
    await update.effective_message.reply_text(
        f"📊 {d}\n\n🎟️ Tickets: {total}\n✅ Paid: {paid}\n⏳ Pending: {pending}\n"
        f"💰 Gross paid entries: R{paid * ENTRY_PRICE:,}\n🕔 Deadline: 5:00 PM\n🎲 Draw: 8:00 PM"
    )


async def setchat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        await update.effective_message.reply_text("⛔ Admin only.")
        return
    await update.effective_message.reply_text(
        f"This chat's ID is {update.effective_chat.id}.\n"
        "Use this as ANNOUNCEMENT_CHAT_ID in your hosting environment."
    )


async def draw_job(context: ContextTypes.DEFAULT_TYPE):
    d = today_str()
    with db() as conn:
        if conn.execute("SELECT 1 FROM draws WHERE draw_date=?", (d,)).fetchone():
            return

        paid = conn.execute(
            "SELECT * FROM tickets WHERE draw_date=? AND payment_status='paid' ORDER BY selected_at ASC",
            (d,)
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
            (d, winning, datetime.now(TZ).isoformat(), len(winners), 0)
        )

    lines = [
        "🎰 *TELEGRAM DAILY LOTTO — DRAW RESULT*",
        "",
        f"🎱 Winning number: *{winning}*",
        f"🎟️ Paid entries: *{len(paid)}*",
        f"🏆 Matching tickets: *{len(winners)}*",
    ]

    if winners:
        lines += ["", "🏆 *WINNING TICKETS*"]
        for r in winners[:20]:
            name = r["first_name"] or r["username"] or "Player"
            lines.append(f"• #{r['id']} — {name}")
        if len(winners) > 20:
            lines.append(f"• +{len(winners)-20} more winner(s)")
        lines.append("\n🥇 Payout ranking follows the published payout structure and selection order.")
    else:
        lines.append("\nNo paid ticket matched today's winning number.")

    if ANNOUNCEMENT_CHAT_ID:
        await context.bot.send_message(
            chat_id=ANNOUNCEMENT_CHAT_ID, text="\n".join(lines), parse_mode="Markdown"
        )
    if ADMIN_ID:
        await context.bot.send_message(
            chat_id=ADMIN_ID, text="\n".join(lines), parse_mode="Markdown"
        )


async def post_init(app):
    app.job_queue.run_daily(
        draw_job, time=time(20, 0, tzinfo=TZ), name="daily-draw"
    )
    await app.bot.set_my_commands([
        ("start", "Open the Daily Lotto menu"),
        ("status", "See today's entry status"),
        ("history", "See recent draw results"),
        ("help", "Show help"),
    ])


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is missing")
    init_db()

    app = ApplicationBuilder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("history", history_cmd))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("setchat", setchat))
    app.add_handler(CallbackQueryHandler(on_button))

    log.info("Starting Telegram Daily Lotto bot")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
