import asyncio
from sys import stderr

import uvloop
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from loguru import logger

logger.remove()
logger.add(
    stderr,
    format="[{time:HH:mm:ss} <level>{level}</level>]:"
    " <green>{file}:{function}</green>"
    " <cyan>></cyan> {message}",
    level="INFO",
    colorize=True,
    backtrace=False,
    diagnose=False,
)


async def main():
    from modules import config
    from modules.handlers import SessionManager, router, set_session_manager

    bot = Bot(
        token=config.cfg.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    sessions = SessionManager(timeout_minutes=config.cfg.bot.session_timeout_minutes)
    set_session_manager(sessions)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    dp.include_router(router)

    logger.info("Бот запущен...")
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем.")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        try:
            import uvloop

            uvloop.run(main())
        except ModuleNotFoundError:
            logger.warning(
                "Uvloop не найден! Установите его для большей производительности",
            )
            asyncio.run(main())
    except KeyboardInterrupt, asyncio.CancelledError:
        logger.warning("Закрываю бота!")
