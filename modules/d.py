from loguru import logger
from telethon import events

logger.info(f"Загружен модуль {__name__}!")


def cmd(pattern, *, incoming=False, outgoing=True, **kwargs) -> events.NewMessage:
    "Wrapper for events.NewMessage"

    return events.NewMessage(
        pattern=rf"(?i)^{pattern}",
        incoming=incoming,
        outgoing=outgoing,
        **kwargs,
    )
