import asyncio

from loguru import logger
from telethon import TelegramClient
from telethon.tl.custom import Message

from . import phrase, settings

logger.info(f"Загружен модуль {__name__}!")


class AutoChatManager:
    def __init__(self, client: TelegramClient, settings: "settings.UBSettings"):
        self.client = client
        self.settings = settings
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._worker())

    async def stop(self):
        self._running = False
        if self._task:
            await self._task
            self._task = None

    async def _worker(self):
        while self._running:
            chat_ids = await self.settings.get("autochat.chats", [])
            ad_chat = await self.settings.get("autochat.ad_chat")
            ad_id = await self.settings.get("autochat.ad_id")
            delay = await self.settings.get("autochat.delay", 1000)

            if not (chat_ids and ad_chat and ad_id):
                await asyncio.sleep(60)
                continue

            for chat_id in chat_ids:
                if not self._running:
                    return
                try:
                    await self.client.forward_messages(chat_id, int(ad_id), ad_chat)
                except Exception:
                    pass
                await asyncio.sleep(1)

            await asyncio.sleep(delay)

    async def toggle(self, event: Message):
        enabled = not await self.settings.get("autochat.enabled", False)
        await self.settings.set("autochat.enabled", enabled)
        if enabled:
            await self.start()
            await event.edit(phrase.autochat.on)
        else:
            await self.stop()
            await event.edit(phrase.autochat.off)

    async def add_chat(self, event: Message):
        try:
            chat_id = int(event.pattern_match.group(1))
        except (ValueError, TypeError):
            return await event.edit(phrase.autochat.invalid_id)
        chats: list = await self.settings.get("autochat.chats", [])
        if chat_id not in chats:
            chats.append(chat_id)
            await self.settings.set("autochat.chats", chats)
        await event.edit(phrase.autochat.added.format(chat_id))

    async def remove_chat(self, event: Message):
        try:
            chat_id = int(event.pattern_match.group(1))
        except (ValueError, TypeError):
            return await event.edit(phrase.autochat.invalid_id)
        chats: list = await self.settings.get("autochat.chats", [])
        if chat_id in chats:
            chats.remove(chat_id)
            await self.settings.set("autochat.chats", chats)
        await event.edit(phrase.autochat.removed.format(chat_id))

    async def set_delay(self, event: Message):
        try:
            delay = int(event.pattern_match.group(1))
            if delay < 10:
                return await event.edit(phrase.autochat.too_fast)
        except (ValueError, TypeError):
            return await event.edit(phrase.autochat.invalid_time)
        await self.settings.set("autochat.delay", delay)
        await event.edit(phrase.autochat.time_set.format(delay))
