import asyncio
import re
from typing import Any

import aiohttp
from telethon import events
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest


class VKMethods:
    def __init__(self, logger: Any, token: str | None = None) -> None:
        self.token: str | None = token
        self.logger: Any = logger
        self.session: aiohttp.ClientSession | None = None

    async def init(self) -> None:
        if self.session is None:
            self.session = aiohttp.ClientSession()

    async def close(self) -> None:
        if self.session is not None and not self.session.closed:
            await self.session.close()
            self.session = None

    async def _request(self, url: str) -> dict[str, Any]:
        if self.session is None:
            await self.init()
        try:
            async with self.session.get(url, timeout=30) as resp:
                try:
                    return await resp.json()
                except Exception:
                    text = await resp.text()
                    self.logger.warning(f"VK: could not parse json, body={text[:200]}")
                    return {}
        except Exception as e:
            self.logger.exception(f"HTTP request failed: {e}")
            return {}

    async def like_vk_post(self, url: str) -> int:
        self.logger.info("Лайкаю пост..")
        if not self.token:
            self.logger.warning("vk.token is not set, skipping like")
            return 0
        if "vk.com" not in url:
            return 0
        group = "-" in url
        if "wall" in url:
            type_ = "post"
        elif "video" in url:
            type_ = "video"
        elif "photo" in url:
            type_ = "photo"
        elif "audio" in url:
            type_ = "audio"
        elif "note" in url:
            type_ = "note"
        elif "market" in url:
            type_ = "market"
        elif "photo_comment" in url:
            type_ = "photo_comment"
        elif "video_comment" in url:
            type_ = "video_comment"
        elif "topic_comment" in url:
            type_ = "topic_comment"
        elif "market_comment" in url:
            type_ = "market_comment"
        elif "clip" in url:
            type_ = "clip"
        else:
            type_ = "post"
        url = url.replace("https://vk.com/", "").split("_")
        owner_id = re.findall("\\d+", url[0])[0]
        if group:
            owner_id = "-" + owner_id
        post_id = re.findall("\\d+", url[1])[0]
        resp = await self._request(
            "https://api.vk.com/method/likes.add"
            f"?type={type_}"
            f"&owner_id={owner_id}"
            f"&item_id={post_id}"
            f"&access_token={self.token}"
            "&v=5.131"
        )
        self.logger.info(f"Ответ вк: {resp}")
        if resp.get("response") and resp.get("response").get("likes") is not None:
            return 1
        return 0

    async def join_vk_group(self, url: str) -> int:
        self.logger.info("Присоединяюсь к группе..")
        if not self.token:
            self.logger.warning("vk.token is not set, skipping join group")
            return 0
        if "vk.com" not in url:
            return 0
        group_id = url.split("/")[-1].replace("club", "")
        resp = await self._request(
            "https://api.vk.com/method/groups.join"
            f"?group_id={group_id}"
            f"&access_token={self.token}"
            "&v=5.131"
        )
        self.logger.info(f"Ответ вк: {resp}")
        if resp.get("response") == 1:
            return 1
        return 0

    async def add_vk_friend(self, url: str) -> int:
        self.logger.info("Добавляю в друзья")
        if not self.token:
            self.logger.warning("vk.token is not set, skipping add friend")
            return 0
        if "vk.com" not in url:
            return 0
        user_id = url.split("/")[-1].replace("id", "")
        resp = await self._request(
            "https://api.vk.com/method/friends.add"
            f"?user_id={user_id}"
            f"&access_token={self.token}"
            "&v=5.131"
        )
        self.logger.info(f"Ответ ВК: {resp}")
        if resp.get("response") == 1:
            return 1
        return 0

    async def get_vk_post(self, url: str) -> int:
        self.logger.info("Получаю информацию о посте")
        if not self.token:
            self.logger.warning("vk.token is not set, skipping get post")
            return 0
        if "vk.com" not in url:
            return 0
        post_id = url.split("_")[-1]
        resp = await self._request(
            "https://api.vk.com/method/wall.getById"
            f"?posts={post_id}"
            f"&access_token={self.token}"
            "&v=5.131"
        )
        self.logger.info(f"Ответ ВК: {resp}")
        if "response" in resp:
            return 1
        return 0


class VKTargetAutomation:
    """Автоматическая обработка сообщений от vktarget_bot."""

    def __init__(self, client: Any, settings: Any, logger: Any) -> None:
        self.client: Any = client
        self.settings: Any = settings
        self.logger: Any = logger
        self._handler: Any | None = None
        self.vk: VKMethods | None = None

    async def start(self) -> None:
        if self._handler is None:
            self._handler = self._on_message
            # подготовим VKMethods сессии
            await self.settings._ensure_loaded()
            token = await self.settings.get("vk.token")
            self.vk = VKMethods(self.logger, token=token)
            await self.vk.init()
            self.client.add_event_handler(self._handler, events.NewMessage(chats="vktarget_bot"))
            self.logger.info("VKTarget automation started")

    def stop(self) -> None:
        if self._handler is not None:
            try:
                self.client.remove_event_handler(self._handler)
            except Exception:
                self.logger.exception("Не удалось удалить handler vktarget")
            self._handler = None
            # закрываем aiohttp-сессию асинхронно
            try:
                if self.vk is not None:
                    asyncio.create_task(self.vk.close())
            except Exception:
                self.logger.exception("Ошибка при закрытии сессии vktarget")
            self.logger.info("VKTarget automation stopped")

    async def _on_message(self, event: Any) -> None:
        # используем подготовленный экземпляр VKMethods
        vk = getattr(self, "vk", None)
        if vk is None:
            await self.settings._ensure_loaded()
            token = await self.settings.get("vk.token")
            vk = VKMethods(self.logger, token=token)
            await vk.init()

        await event.mark_read()
        await asyncio.sleep(4)
        text = event.text or ""
        if "Вступите в" in text:
            url = text.split("](")[1].split(")")[0]
            if await vk.join_vk_group(url) == 0:
                await event.click(text="Скрыть")
                return await event.respond("Задания")
            await event.click(text="Проверить")
            return await event.respond("Задания")

        if "Поставьте лайк на" in text or "Посмотреть" in text:
            url = text.split("](")[1].split(")")[0]
            if await vk.like_vk_post(url) == 0:
                await event.click(text="Скрыть")
                return await event.respond("Задания")
            await event.click(text="Проверить")
            return await event.respond("Задания")

        if "Добавить в" in text:
            url = text.split("](")[1].split(")")[0]
            if await vk.add_vk_friend(url) == 0:
                await event.click(text="Скрыть")
                return await event.respond("Задания")
            await event.click(text="Проверить")
            return await event.respond("Задания")

        if "канал" in text:
            channelname = None
            for line in text.split("\n"):
                if "канал" in line:
                    try:
                        channelname = line.split("](")[1].split(")")[0]
                    except Exception:
                        channelname = None
            if not channelname:
                try:
                    await event.click(text="Скрыть")
                except Exception:
                    await event.respond("Задания")
                return None
            try:
                await self.client(JoinChannelRequest(channelname))
                self.logger.info(f"Подписываюсь на канал {channelname}")
                await asyncio.sleep(20)
                await event.click(text="Проверить")
            except Exception:
                try:
                    await self.client(ImportChatInviteRequest(channelname))
                    self.logger.info(f"Подписываюсь на канал {channelname}")
                    await asyncio.sleep(20)
                    await event.click(text="Проверить")
                except Exception:
                    await event.click(text="Скрыть")
                    self.logger.info(f"Не смог подписаться на канал {channelname}")
                    return await event.respond("Задания")
            return await event.respond("Задания")

        if "Доступны новые задания!" in text and "исчезнуть" not in text:
            self.logger.info("Доступны новые задания!")
            return await event.respond("Задания")

        try:
            await event.click(text="Скрыть")
        except Exception:
            await event.respond("Задания")
