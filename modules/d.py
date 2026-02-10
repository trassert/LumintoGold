from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types.users import UserFull

logger.info(f"Загружен модуль {__name__}!")


def cmd(pattern, *, incoming=False, outgoing=True, **kwargs) -> events.NewMessage:
    "Wrapper for events.NewMessage"

    return events.NewMessage(
        pattern=rf"(?i)^{pattern}",
        incoming=incoming,
        outgoing=outgoing,
        **kwargs,
    )


async def get_info(client: TelegramClient, str: str, return_str=False) -> int | list:
    if str[-1] == ",":
        str = str[:-1]
    user: UserFull = await client(GetFullUserRequest(str))
    if return_str:
        return [user.full_user.id, str]
    return user.full_user.id
