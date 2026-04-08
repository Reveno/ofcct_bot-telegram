import asyncio
import logging

from telegram.ext import ApplicationBuilder

import db
from admin_handlers import broadcast, messages, retakes_mgmt, schedule_mgmt, stats
from config import ADMIN_BOT_TOKEN, BOT_TOKEN
from handlers import (
    faq,
    feedback,
    menu,
    news,
    retakes,
    schedule,
    social,
    subscription,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


async def _error_handler(update, context) -> None:
    err = getattr(context, "error", None)
    logger.exception("Unhandled error: %s", err)
    try:
        if update and getattr(update, "callback_query", None):
            q = update.callback_query
            await q.answer("Сталася помилка. Спробуйте ще раз.", show_alert=True)
        elif update and getattr(update, "effective_chat", None):
            chat_id = update.effective_chat.id
            msg = f"⚠️ Помилка: {type(err).__name__}: {err}" if err else "⚠️ Помилка."
            if len(msg) > 4000:
                msg = msg[:3990] + "…"
            await context.bot.send_message(chat_id=chat_id, text=msg)
    except Exception:
        logger.exception("Failed to report error to chat")


async def main() -> None:
    await db.init_db()
    await db.seed_faq()

    student_app = ApplicationBuilder().token(BOT_TOKEN).build()
    admin_app = ApplicationBuilder().token(ADMIN_BOT_TOKEN).build()

    student_app.add_error_handler(_error_handler)
    admin_app.add_error_handler(_error_handler)

    menu.register(student_app)
    schedule.register(student_app)
    faq.register(student_app)
    feedback.register(student_app, admin_app)
    subscription.register(student_app)
    social.register(student_app)
    retakes.register(student_app)
    news.register(student_app)
    menu.register_main_callback(student_app)
    messages.register(admin_app, student_app)
    broadcast.register(admin_app, student_app)
    schedule_mgmt.register(admin_app)
    retakes_mgmt.register(admin_app)
    stats.register(admin_app)

    await student_app.initialize()
    await admin_app.initialize()
    await student_app.start()
    await admin_app.start()
    await student_app.updater.start_polling(drop_pending_updates=True)
    await admin_app.updater.start_polling(drop_pending_updates=True)

    try:
        stop = asyncio.Event()
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await student_app.updater.stop()
        await admin_app.updater.stop()
        await student_app.stop()
        await admin_app.stop()
        await student_app.shutdown()
        await admin_app.shutdown()
        await db.close_db()


if __name__ == "__main__":
    asyncio.run(main())
