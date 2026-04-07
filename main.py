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


async def main() -> None:
    await db.init_db()
    await db.seed_faq()

    student_app = ApplicationBuilder().token(BOT_TOKEN).build()
    admin_app = ApplicationBuilder().token(ADMIN_BOT_TOKEN).build()

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
