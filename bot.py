import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import settings
from handlers import document, start
from middleware.auth import AuthMiddleware
from utils.logger import logger


async def main() -> None:
    logger.info("Starting tender matcher bot...")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    # Register middleware
    dp.message.middleware(AuthMiddleware())

    # Register routers
    dp.include_router(start.router)
    dp.include_router(document.router)

    logger.info("Bot started. Polling...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    asyncio.run(main())
