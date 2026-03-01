import asyncio
import logging
import random
import re
from dataclasses import dataclass
from typing import Any

from telethon import TelegramClient, events
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import Message
from vkbottle import API

SettingsType = Any
LoggerType = logging.Logger


@dataclass
class TaskResult:
    success: bool
    action: str
    message: str


class VKActions:
    def __init__(self, token: str, logger: LoggerType) -> None:
        self.token = token
        self.logger = logger
        self.api = API(token)

    async def init(self) -> None:
        pass

    async def close(self) -> None:
        try:
            await self.api.ctx_api_interceptor.close_session()
        except Exception:
            pass

    @staticmethod
    async def _human_delay(min_s: float = 1.5, max_s: float = 3.5) -> None:
        await asyncio.sleep(random.uniform(min_s, max_s))

    def _extract_ids_from_url(self, url: str) -> tuple[str, str, str]:
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
                "likes.add", data={"type": l_type, "owner_id": owner_id, "item_id": item_id}
            )
            if resp.get("response") and resp["response"].get("likes"):
                return TaskResult(True, "like", "Успешно лайкнуто")
            return TaskResult(True, "like", "Уже лайкнуто или ок")
        except Exception as e:
            self.logger.error(f"Ошибка лайка: {e}")
            return TaskResult(False, "like", str(e))

    async def join_group(self, url: str) -> TaskResult:
        await self._human_delay(3.0, 5.0)
        try:
            match = re.search(r"(club|public)(\d+)", url)
            group_id = (
                match.group(2)
                if match
                else (re.findall(r"\d+", url)[-1] if re.findall(r"\d+", url) else "0")
            )
            self.logger.info(f"Вступление в группу: {group_id}")
            resp = await self.api.request("groups.join", data={"group_id": group_id})
            if resp.get("response") == 1:
                return TaskResult(True, "join", "Успешно вступил")
            return TaskResult(True, "join", "Уже в группе")
        except Exception as e:
            err_str = str(e)
            if "already in this community" in err_str or "Error 15" in err_str:
                return TaskResult(True, "join", "Уже в группе")
            self.logger.error(f"Ошибка вступления: {e}")
            return TaskResult(False, "join", str(e))

    async def add_friend(self, url: str) -> TaskResult:
        await self._human_delay(4.0, 7.0)
        try:
            match = re.search(r"id(\d+)", url)
            user_id = (
                match.group(1)
                if match
                else (re.findall(r"\d+", url)[-1] if re.findall(r"\d+", url) else "0")
            )
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

    async def subscribe_telegram_channel(self, url: str, client: TelegramClient) -> TaskResult:
        """Подписка на канал/чат Telegram (включая приватные по ссылке +)."""
        await self._human_delay(2.0, 4.0)
        try:
            self.logger.info(f"TG: Подписка на канал: {url}")
            if "+/" in url or "joinchat" in url:
                invite_hash = url.split("/")[-1]
                invite_hash = invite_hash.split("?")[0]
                await client(ImportChatInviteRequest(invite_hash))
            else:
                username = (
                    url.replace("https://t.me/", "").replace("http://t.me/", "").split("/")[0]
                )
                await client(JoinChannelRequest(username))
            return TaskResult(True, "tg_join", "Успешно подписан на TG")
        except Exception as e:
            err_str = str(e)
            if "USER_ALREADY_PARTICIPANT" in err_str or "already a member" in err_str.lower():
                return TaskResult(True, "tg_join", "Уже подписан на TG")
            self.logger.error(f"TG: Ошибка подписки: {e}")
            return TaskResult(False, "tg_join", str(e))

    async def view_telegram_post(self, url: str, client: TelegramClient) -> TaskResult:
        """Просмотр записи в Telegram (эмуляция открытия)."""
        await self._human_delay(1.5, 3.0)
        try:
            self.logger.info(f"TG: Просмотр записи: {url}")
            parts = url.rstrip("/").split("/")
            if len(parts) < 2:
                return TaskResult(False, "tg_view", "Неверный формат ссылки TG")
            post_id = int(parts[-1])
            chat_ref = parts[-2]
            entity = None
            if chat_ref == "c":
                chat_id = int(parts[-3]) if len(parts) > 3 else int(parts[-2])
                try:
                    entity = await client.get_entity(chat_id)
                except Exception:
                    entity = await client.get_entity(int(parts[-3]))
            else:
                entity = await client.get_entity(chat_ref)
            if entity:
                await client.get_messages(entity, ids=post_id)
                return TaskResult(True, "tg_view", "Пост просмотрен")
            return TaskResult(False, "tg_view", "Не удалось получить сущность")
        except Exception as e:
            self.logger.warning(f"TG: Нюанс при просмотре (возможно уже засчитано): {e}")
            return TaskResult(True, "tg_view", "Попытка просмотра выполнена")


class VKTargetRefactored:
    def __init__(self, client: TelegramClient, settings: SettingsType, logger: LoggerType) -> None:
        self.client = client
        self.settings = settings
        self.logger = logger
        self.vk: VKActions | None = None
        self._poll_task: asyncio.Task | None = None
        self._active = False
        self._lock = asyncio.Lock()
        self._empty_count = 0

    async def start(self) -> None:
        await self.settings._ensure_loaded()
        token = await self.settings.get("vk.token")
        if not token:
            self.logger.error("❌ VK Token не найден!")
            return
        self.vk = VKActions(token, self.logger)
        await self.vk.init()
        self._active = True

        @self.client.on(
            events.NewMessage(chats="vktarget_bot", func=lambda e: e.text and not e.out)
        )
        async def handler(event: Message) -> None:
            async with self._lock:
                if self._active:
                    await self._process_message(event)

        self.logger.info("VKTarget Automation запущен (Safe Mode)")
        self._poll_task = asyncio.create_task(self._poll_loop())

    def stop(self) -> None:
        self._active = False
        if self._poll_task:
            self._poll_task.cancel()
        self.logger.info("VKTarget Automation остановлен")

    async def _poll_loop(self) -> None:
        try:
            await asyncio.sleep(5)
            while self._active:
                base_wait = await self.settings.get("vktarget.poll_wait")
                delay = base_wait * 60 + random.uniform(-30, 30)
                await asyncio.sleep(max(10, delay))
                if not self._active:
                    break
                if not self._lock.locked():
                    try:
                        await self.client.send_message("vktarget_bot", "Задания")
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.exception(f"Poll error: {e}")

    async def _process_message(self, event: Message) -> None:
        if not self.vk:
            return
        text = event.text or ""
        if not text:
            return
        await event.mark_read()
        lower_text = text.lower()
        if any(
            k in lower_text
            for k in ["начали поиск", "нет доступных", "задания закончились", "скрыли данное"]
        ):
            self.logger.debug("Заданий нет, жду...")
            self._empty_count += 1
            return
        if "доступны новые задания" in lower_text:
            await asyncio.sleep(1)
            if not self._lock.locked():
                await self.client.send_message("vktarget_bot", "Задания")
            return
        links = re.findall(r"\]\(([^)]+)\)", text)
        if not links:
            self.logger.warning(f"Ссылка не найдена в тексте: {text[:30]}...")
            return
        url = links[0].strip()
        self.logger.info(f"Обработка задачи: {text[:40]}...")
        self._empty_count = 0
        result = TaskResult(False, "unknown", "")
        if "t.me/" in url:
            if (
                "подпишитесь" in lower_text
                or "вступите" in lower_text
                or "канал" in lower_text
                or "чат" in lower_text
            ):
                result = await self.vk.subscribe_telegram_channel(url, self.client)
            elif (
                "просмотр" in lower_text
                or "посмотрите" in lower_text
                or "запись" in lower_text
                or "пост" in lower_text
            ):
                result = await self.vk.view_telegram_post(url, self.client)
            else:
                result = await self.vk.subscribe_telegram_channel(url, self.client)
        elif "vk.com" in url:
            if "Вступите в" in text or "группу" in text or "сообщество" in text:
                result = await self.vk.join_group(url)
            elif "Поставьте лайк" in text or "лайк на" in text or "оцените" in text:
                result = await self.vk.like(url)
            elif "Добавить в друзья" in text or "в друзья" in text:
                result = await self.vk.add_friend(url)
            elif "канал" in text and ("подпишитесь" in text or "Вступите" in text):
                result = await self.vk.subscribe_channel(url)
            else:
                self.logger.debug(f"Неизвестный тип задачи VK: {text[:30]}")
                return
        else:
            self.logger.warning(f"Неподдерживаемый домен ссылки: {url}")
            return
        await asyncio.sleep(random.uniform(1.0, 2.0))
        try:
            btn_text = "Проверить" if result.success else "Скрыть"
            self.logger.info(f"Нажимаю: {btn_text} ({result.message})")
            await event.click(text=btn_text)
            await asyncio.sleep(random.uniform(1.5, 2.5))
            if self._active and not self._lock.locked():
                await self.client.send_message("vktarget_bot", "Задания")
        except ValueError:
            self.logger.warning(f"Кнопка '{btn_text}' не найдена. Возможно, сообщение обновилось.")
        except Exception as e:
            if "GetBotCallbackAnswerRequest" in str(e) or "invalid" in str(e).lower():
                self.logger.warning(f"Сообщение устарело, пропускаем клик. Ошибка: {e}")
            else:
                self.logger.error(f"Ошибка клика: {e}")
            await asyncio.sleep(2)
            if self._active:
                await self.client.send_message("vktarget_bot", "Задания")

    async def close(self) -> None:
        self.stop()
        if self.vk:
            await self.vk.close()
