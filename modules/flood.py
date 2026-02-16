import time

from loguru import logger
from telethon import TelegramClient
from telethon.tl.custom import Message
from telethon.tl.types import (
    DocumentAttributeAnimated,
    DocumentAttributeSticker,
    DocumentAttributeVideo,
    MessageMediaDocument,
)

from . import phrase, settings

logger.info(f"Загружен модуль {__name__}!")


class FloodController:
    def __init__(self, client: "TelegramClient", settings: "settings.UBSettings"):
        self.client = client
        self.settings = settings
        self._flood_state: dict[str, list[float]] = {}
        self._flood_rules: dict[int, dict[str, dict]] = {}

    async def load_rules(self, chat_id: int):
        if chat_id not in self._flood_rules:
            stickers = await self.settings.get(f"flood.stickers.{chat_id}", {})
            gifs = await self.settings.get(f"flood.gifs.{chat_id}", {})
            messages = await self.settings.get(f"flood.messages.{chat_id}", {})
            self._flood_rules[chat_id] = {
                "stickers": stickers,
                "gifs": gifs,
                "messages": messages,
            }

    async def monitor(self, event: Message):
        if event.is_private or not event.sender_id:
            return
        chat_id = event.chat_id
        await self.load_rules(chat_id)
        rules = self._flood_rules[chat_id]
        now = time.time()

        if rules["stickers"] and isinstance(event.media, MessageMediaDocument):
            doc = event.media.document
            if doc and any(isinstance(a, DocumentAttributeSticker) for a in (doc.attributes or [])):
                await self._check_flood(event, chat_id, "stickers", rules["stickers"], now)

        if rules["gifs"] and isinstance(event.media, MessageMediaDocument):
            doc = event.media.document
            if doc:
                is_gif = any(
                    isinstance(a, DocumentAttributeAnimated)
                    or (isinstance(a, DocumentAttributeVideo) and a.supports_streaming)
                    for a in (doc.attributes or [])
                )
                if is_gif:
                    await self._check_flood(event, chat_id, "gifs", rules["gifs"], now)

        if rules["messages"] and event.text and not event.media:
            await self._check_flood(event, chat_id, "messages", rules["messages"], now)

    async def _check_flood(self, event, chat_id: int, flood_type: str, rule: dict, now: float):
        limit = rule.get("limit", 0)
        window = rule.get("window", 0)
        if limit <= 0 or window <= 0:
            return
        key = f"_flood.{flood_type}.{chat_id}.{event.sender_id}"
        timestamps = self._flood_state.get(key, [])
        cutoff = now - window
        timestamps = [ts for ts in timestamps if ts > cutoff]
        timestamps.append(now)
        if len(timestamps) > limit:
            try:
                msg = await self.settings.get("flood.msg")
                if msg:
                    await event.reply(msg)
            except Exception:
                pass
            timestamps = []
        self._flood_state[key] = timestamps

    async def set_rule(self, event: Message, rule_type: str):
        try:
            limit = int(event.pattern_match.group(1))
            window = int(event.pattern_match.group(2))
        except (ValueError, IndexError):
            return await event.edit("❌ Неверный формат: `.флуд <лимит> <окно>`")
        chat_id = event.chat_id
        key = f"flood.{rule_type}.{chat_id}"
        await self.settings.set(key, {"limit": limit, "window": window})
        if chat_id not in self._flood_rules:
            self._flood_rules[chat_id] = {}
        self._flood_rules[chat_id][rule_type] = {"limit": limit, "window": window}

        phrase_map = {
            "stickers": phrase.flood.set_stickers,
            "gifs": phrase.flood.set_gifs,
            "messages": phrase.flood.set_messages,
        }
        await event.edit(phrase_map[rule_type].format(limit=limit, window=window))
        return None

    async def unset_rule(self, event: Message, rule_type: str):
        chat_id = event.chat_id
        key = f"flood.{rule_type}.{chat_id}"
        await self.settings.remove(key)
        if chat_id in self._flood_rules:
            self._flood_rules[chat_id][rule_type] = {}
        prefix = f"_flood.{rule_type}.{chat_id}."
        to_remove = [k for k in self._flood_state if k.startswith(prefix)]
        for k in to_remove:
            self._flood_state.pop(k, None)

        phrase_map = {
            "stickers": phrase.flood.unset_stickers,
            "gifs": phrase.flood.unset_gifs,
            "messages": phrase.flood.unset_messages,
        }
        await event.edit(phrase_map[rule_type])
