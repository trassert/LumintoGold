from telethon import events
from loguru import logger

logger.info(f"Загружен модуль {__name__}!")


def cmd(
    pattern, *, incoming=False, outgoing=True, **kwargs
) -> events.NewMessage:
    "Wrapper for events.NewMessage"

    return events.NewMessage(
        pattern=pattern, incoming=incoming, outgoing=outgoing, **kwargs
    )
