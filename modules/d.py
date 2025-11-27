from telethon import events
from loguru import logger

logger.info(f"Загружен модуль {__name__}!")

# Wrapper for events.NewMessage

def cmd(pattern, *, incoming=False, outgoing=True, **kwargs) -> events.NewMessage:
    return events.NewMessage(
        pattern=pattern,
        incoming=incoming,
        outgoing=outgoing,
        **kwargs
    )