import asyncio
import logging
import random
import re
from dataclasses import dataclass

import aiohttp
from telethon import TelegramClient, events
from telethon.tl.types import Message
from vkbottle import API

from . import settings

SettingsType = settings.UBSettings
LoggerType = logging.Logger


@dataclass
class TaskResult:
    success: bool
    action: str
    message: str


class VKActions:
    """
    Класс для выполнения действий ВКонтакте через официальное API (vkbottle).
    """

    def __init__(self, token: str, logger: LoggerType) -> None:
        self.token = token
        self.logger = logger
        self.api = API(token)
        self._session: aiohttp.ClientSession | None = None

    async def init(self) -> None:
        pass

    async def close(self) -> None:
        await self.api.ctx_api_interceptor.close_session()

    @staticmethod
    async def _human_delay(min_s: float = 1.5, max_s: float = 3.5) -> None:
        """Задержка для эмуляции действий человека (анти-бан)."""
        await asyncio.sleep(random.uniform(min_s, max_s))

    def _extract_ids_from_url(self, url: str) -> tuple[str, str, str]:
        """
        Парсит ссылку ВК и возвращает (owner_id, item_id, type).
        """
        url = url.strip().replace("https://", "").replace("http://", "")
        content_type = "post"
        if "/video" in url:
            content_type = "video"
        elif "/photo" in url:
            content_type = "photo"
        elif "/audio" in url:
            content_type = "audio"
        elif "/market" in url:
            content_type = "market"
        elif "/clip" in url:
            content_type = "clip"
        clean_path = re.sub(r"/(wall|video|photo|audio|market|clip|note)/", "/", url)
        parts = clean_path.split("/")[-1].split("_")
        owner_raw = parts[0]
        item_id = parts[1] if len(parts) > 1 else "0"
        if owner_raw.startswith("id"):
            owner_id = owner_raw[2:]
        elif owner_raw.startswith("club") or owner_raw.startswith("public"):
            nums = re.findall(r"\d+", owner_raw)
            owner_id = "-" + nums[0] if nums else "0"
        elif "-" in owner_raw:
            nums = re.findall(r"-?\d+", owner_raw)
            owner_id = nums[0] if nums else "0"
        elif owner_raw.isdigit():
            owner_id = owner_raw
        else:
            nums = re.findall(r"\d+", owner_raw)
            owner_id = "-" + nums[0] if nums else "0"
        return owner_id, item_id, content_type

    async def like(self, url: str) -> TaskResult:
        await self._human_delay(2.0, 4.0)
        try:
            owner_id, item_id, l_type = self._extract_ids_from_url(url)
            self.logger.info(f"Лайк: owner={owner_id}, id={item_id}, type={l_type}")

            resp = await self.api.request(
                "likes.add",
                data={"type": l_type, "owner_id": owner_id, "item_id": item_id},
            )
            if resp.get("response") and resp["response"].get("likes"):
                return TaskResult(True, "like", "Успешно лайкнуто")
            return TaskResult(False, "like", f"Ошибка API или уже лайкнуто: {resp}")
        except Exception as e:
            self.logger.error(f"Ошибка лайка: {e}")
            return TaskResult(False, "like", str(e))

    async def join_group(self, url: str) -> TaskResult:
        await self._human_delay(3.0, 5.0)
        try:
            match = re.search(r"(club|public)(\d+)", url)
            if not match:
                nums = re.findall(r"\d+", url)
                group_id = nums[-1] if nums else "0"
            else:
                group_id = match.group(2)
            self.logger.info(f"Вступление в группу: {group_id}")

            resp = await self.api.request("groups.join", data={"group_id": group_id})
            if resp.get("response") == 1:
                return TaskResult(True, "join", "Успешно вступил")
            if resp.get("response") == 0:
                return TaskResult(True, "join", "Уже состою в группе")
            return TaskResult(False, "join", f"Ошибка API: {resp}")
        except Exception as e:
            self.logger.error(f"Ошибка вступления: {e}")
            return TaskResult(False, "join", str(e))

    async def add_friend(self, url: str) -> TaskResult:
        await self._human_delay(4.0, 7.0)
        try:
            match = re.search(r"id(\d+)", url)
            if not match:
                nums = re.findall(r"\d+", url)
                user_id = nums[-1] if nums else "0"
            else:
                user_id = match.group(1)
            self.logger.info(f"Добавление в друзья: {user_id}")

            resp = await self.api.request("friends.add", data={"user_id": user_id})
            if resp.get("response") in [1, 2, 3]:
                return TaskResult(True, "friend", "Заявка отправлена/принята")
            return TaskResult(False, "friend", f"Ошибка API: {resp}")
        except Exception as e:
            self.logger.error(f"Ошибка добавления в друзья: {e}")
            return TaskResult(False, "friend", str(e))

    async def subscribe_channel(self, url: str) -> TaskResult:
        return await self.join_group(url)


class VKTargetRefactored:
    """
    Рефакторинг логики vktarget. Базируется на Trassert UserBot (deprecated)
    """

    def __init__(self, client: TelegramClient, settings: SettingsType, logger: LoggerType) -> None:
        self.client = client
        self.settings = settings
        self.logger = logger
        self.vk: VKActions | None = None
        self._poll_task: asyncio.Task | None = None
        self._active = False

    async def start(self) -> None:
        await self.settings._ensure_loaded()
        token = await self.settings.get("vk.token")
        if not token:
            self.logger.error("VK Token не найден в настройках!")
            return
        self.vk = VKActions(token, self.logger)
        await self.vk.init()
        self._active = True

        @self.client.on(
            events.NewMessage(chats="vktarget_bot", func=lambda e: e.text and not e.out)
        )
        async def handler(event: Message) -> None:
            await self._process_message(event)

        self.logger.info("VKTarget Automation запущен")
        self._poll_task = asyncio.create_task(self._poll_loop())

    def stop(self) -> None:
        self._active = False
        if self._poll_task:
            self._poll_task.cancel()
        self.logger.info("VKTarget Automation остановлен")

    async def _poll_loop(self) -> None:
        """Периодически отправляет 'Задания'."""
        try:
            await asyncio.sleep(5)
            while self._active:
                wait_time = await self.settings.get("vktarget.poll_wait")
                delay = max(10, wait_time + random.uniform(-5, 5))
                await asyncio.sleep(delay)
                if not self._active:
                    break
                try:
                    await self.client.send_message("vktarget_bot", "Задания")
                    self.logger.debug("Запрошен список заданий")
                except Exception as e:
                    self.logger.warning(f"Не удалось отправить запрос заданий: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.exception(f"Критическая ошибка в poll_loop: {e}")

    async def _process_message(self, event: Message) -> None:
        if not self.vk or not self._active:
            return
        text = event.text or ""
        if not text:
            return
        await event.mark_read()
        if "Начали поиск заданий" in text:
            self.logger.info("Заданий нет, сплю..")
            return
        self.logger.info(f"Получено задание: {text[:60]}...")
        links = re.findall(r"\]\(([^)]+)\)", text)
        if not links:
            if "Доступны новые задания" in text:
                await asyncio.sleep(2)
                await self.client.send_message("vktarget_bot", "Задания")
            return
        url = links[0]
        result = TaskResult(False, "unknown", "Нет подходящего обработчика")
        if "Вступите в" in text or "группу" in text:
            result = await self.vk.join_group(url)
        elif "Поставьте лайк" in text or "лайк на" in text:
            result = await self.vk.like(url)
        elif "Добавить в друзья" in text or "в друзья" in text:
            result = await self.vk.add_friend(url)
        elif "канал" in text and ("подпишитесь" in text or "Вступите" in text):
            result = await self.vk.subscribe_channel(url)
        else:
            self.logger.debug(f"Неизвестный тип задачи: {text[:50]}")
        await asyncio.sleep(random.uniform(1.5, 3.0))
        try:
            button_text = "Проверить" if result.success else "Скрыть"
            self.logger.info(f"Нажимаю кнопку: {button_text} ({result.message})")
            await event.click(text=button_text)
            await asyncio.sleep(random.uniform(1.0, 2.0))
            if self._active:
                await self.client.send_message("vktarget_bot", "Задания")
        except ValueError:
            self.logger.warning(f"Кнопка '{button_text}' не найдена в сообщении.")
            await self.client.send_message("vktarget_bot", "Задания")
        except Exception as e:
            self.logger.error(f"Ошибка при нажатии кнопки: {e}")

    async def close(self) -> None:
        self.stop()
        if self.vk:
            await self.vk.close()
