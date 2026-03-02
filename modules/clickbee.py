import asyncio
import random
import re
from contextlib import suppress

from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.custom import Message
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from . import settings

logger.info(f"Загружен модуль {__name__}!")
TASK_BUTTONS = ["🤖 Join Bots", "📢 Join Channels", "📄 View Posts"]
MAX_RETRIES = 3
BOT_CONVERSATION_TIMEOUT = 45


class _CyclicIterator:
    def __init__(self, items: list[str]) -> None:
        self._items = items
        self._index = 0

    def next(self) -> str:
        item = self._items[self._index % len(self._items)]
        self._index += 1
        return item

    def current(self) -> str:
        return self._items[(self._index - 1) % len(self._items)]

    def reset(self) -> None:
        self._index = 0

    @property
    def cycle_complete(self) -> bool:
        """True, если прошли все категории по одному кругу."""
        return self._index > 0 and self._index % len(self._items) == 0


class ClickBeeAutomation:
    """Авто-заработок на ClickBee-ботах."""

    def __init__(self, client: TelegramClient, user_settings: "settings.UBSettings") -> None:
        self.client = client
        self.settings = user_settings
        self._active = False
        self._lock = asyncio.Lock()
        self._handler = None
        self._task_iter = _CyclicIterator(TASK_BUTTONS)
        self._retry_count: int = 0

    async def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._retry_count = 0
        self._task_iter.reset()
        self.bot: str = await self.settings.get("clickbee.username")
        self._register_handler()
        logger.info("ClickBee запущен")
        await asyncio.sleep(random.uniform(1.5, 3))
        await self.client.send_message(self.bot, self._task_iter.next())

    def stop(self) -> None:
        self._active = False
        self._unregister_handler()
        self._browser = None
        logger.info("ClickBee остановлен")

    async def toggle(self, event: Message) -> None:
        enabled = not await self.settings.get("clickbee.enabled", False)
        await self.settings.set("clickbee.enabled", enabled)
        if enabled:
            await self.start()
            await event.edit("✅ : Авто ClickBee включено")
        else:
            self.stop()
            await event.edit("❌ : Авто ClickBee выключено")

    def _register_handler(self) -> None:
        self._unregister_handler()

        async def _on_message(event: Message) -> None:
            if not self._active:
                return
            sender = getattr(event, "chat", None)
            if sender is None:
                return
            username = getattr(sender, "username", None)
            if username != self.bot:
                return
            async with self._lock:
                await self._process_message(event)

        self._handler = _on_message
        self.client.add_event_handler(
            self._handler,
            events.NewMessage(chats=self.bot, incoming=True),
        )

    def _unregister_handler(self) -> None:
        if self._handler is not None:
            with suppress(Exception):
                self.client.remove_event_handler(self._handler)
            self._handler = None

    async def _process_message(self, event: Message) -> None:
        if not self._active:
            return None
        text = event.text or ""
        await event.mark_read()
        await asyncio.sleep(random.uniform(1.5, 4))
        handlers = [
            ("You've earned", self._handle_earned),
            ("NO TASKS", self._handle_no_tasks),
            ("then forward any message", self._handle_forward_check),
            ("FORWARD a message from that bot", self._handle_forward_bot),
            ("and join it", self._handle_join_channel),
            ("Read this post", self._handle_view_post),
        ]
        text_lower = text.lower()
        for keyword, handler in handlers:
            if keyword.lower() in text_lower:
                self._retry_count = 0
                return await handler(event)
        if "error" in text_lower:
            return await self._handle_error(event)
        if "new task" in text_lower or "task available" in text_lower:
            return await self._handle_new_task(event)
        return None

    async def _handle_view_post(self, event: Message) -> None:
        """Ждём и нажимаем ✅ Watched."""
        wait = random.randint(10, 20)
        logger.info(f"ClickBee: Читаю пост, жду {wait}с")
        await asyncio.sleep(wait)
        clicked = await self._click_button(event, "✅")
        if not clicked:
            await self._click_button(event, "Watched")
        await self._next_task(event)

    async def _handle_earned(self, event: Message) -> None:
        logger.info(f"ClickBee: Получена награда — {event.text.strip()}")
        await self._next_task(event)

    async def _handle_no_tasks(self, event: Message) -> None:
        logger.info(f"ClickBee: Нет задач в категории «{self._task_iter.current()}»")
        if self._task_iter.cycle_complete:
            await self._switch_bot(event)
        else:
            task = self._task_iter.next()
            await asyncio.sleep(random.uniform(1, 2))
            await event.respond(task)

    async def _handle_forward_check(self, event: Message) -> None:
        """Нажимаем кнопку ✅ для подтверждения пересылки."""
        clicked = await self._click_button(event, "✅")
        if not clicked:
            logger.warning("ClickBee: Кнопка ✅ не найдена, пробую Next")
            await self._click_button_or_next(event)

    async def _handle_forward_bot(self, event: Message) -> None:
        """Задание: переслать сообщение от стороннего бота."""
        mybot = self._parse_bot_username(event.text or "")
        if not mybot:
            logger.warning("ClickBee: Не удалось определить имя бота, пропускаю")
            return await self._skip_or_back(event)
        logger.info(f"ClickBee: Запрашиваю /start у {mybot}")
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                async with self.client.conversation(
                    mybot, timeout=BOT_CONVERSATION_TIMEOUT, total_timeout=BOT_CONVERSATION_TIMEOUT
                ) as conv:
                    await conv.send_message("/start")
                    response = await asyncio.wait_for(
                        conv.get_response(), timeout=BOT_CONVERSATION_TIMEOUT
                    )
                    await self.client.forward_messages(
                        entity=event.sender_id,
                        messages=response.id,
                        from_peer=response.sender_id,
                    )
                    logger.info(f"ClickBee: Сообщение переслано от {mybot}")
                    return None
            except TimeoutError:
                logger.warning(f"ClickBee: {mybot} не ответил (попытка {attempt}/{MAX_RETRIES})")
            except Exception as exc:
                logger.warning(f"ClickBee: Ошибка при работе с {mybot}: {exc} (попытка {attempt})")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(random.uniform(3, 7))
        logger.info(f"ClickBee: {mybot} недоступен, пропускаю задание")
        await self._skip_or_back(event)
        await asyncio.sleep(5)
        await self._next_task(event)
        return None

    async def _handle_join_channel(self, event: Message) -> None:
        """Задание: вступить в канал/группу (публичный или приватный)."""
        channel_link = self._parse_channel_link(event.text or "")
        if channel_link:
            success = await self._join_channel_safe(channel_link)
            if not success:
                logger.warning(f"ClickBee: Не смог вступить в {channel_link}, ищу Skip")
                clicked = await self._click_button(event, "Skip")
                if clicked:
                    return
        await asyncio.sleep(random.uniform(2, 5))
        clicked = await self._click_button(event, "✅")
        if not clicked:
            await self._next_task(event)

    async def _handle_error(self, event: Message) -> None:
        self._retry_count += 1
        logger.warning(f"ClickBee: Ошибка от бота (попытка {self._retry_count}): {event.text[:80]}")
        if self._retry_count >= MAX_RETRIES:
            self._retry_count = 0
            logger.info("ClickBee: Превышен лимит ошибок, перехожу к следующей задаче")
            return await self._next_task(event)
        await asyncio.sleep(random.uniform(5, 10))
        current = self._task_iter.current()
        await event.respond(current)
        return None

    async def _handle_new_task(self, event: Message) -> None:
        logger.info("ClickBee: Новые задачи доступны!")
        await self._next_task(event)

    async def _next_task(self, event: Message) -> None:
        if not self._active:
            return
        task = self._task_iter.next()
        await asyncio.sleep(random.uniform(1, 3))
        await event.respond(task)

    async def _switch_bot(self, event: Message) -> None:
        if not self._active:
            return
        self._task_iter.reset()
        sleep_time = await self.settings.get("clickbee.sleep_between", 300)
        jitter = random.randint(-30, 30)
        actual_sleep = max(30, sleep_time + jitter)
        logger.info(f"ClickBee: Все категории пройдены, сплю {actual_sleep}с")
        await asyncio.sleep(actual_sleep)
        if not self._active:
            return
        first_task = self._task_iter.next()
        await self.client.send_message(self.bot, first_task)

    async def _skip_or_back(self, event: Message) -> None:
        """Нажимает Skip или Back, если есть."""
        for label in ("Skip", "🔙 Back", "Back"):
            if await self._click_button(event, label):
                return
        await event.respond("🔙 Back")

    async def _click_button_or_next(self, event: Message) -> None:
        for label in ("Next", "➡️", "✅", "Skip"):
            if await self._click_button(event, label):
                return
        await self._next_task(event)

    async def _join_channel_safe(self, link: str) -> bool:
        """Пробует вступить публично, затем по инвайту."""
        try:
            await self.client(JoinChannelRequest(link))
            logger.info(f"ClickBee: Вступил в {link}")
            return True
        except Exception:
            pass
        hash_match = re.search(r"[+/]([A-Za-z0-9_-]{10,})", link)
        if hash_match:
            hash_part = hash_match.group(1)
            try:
                await self.client(ImportChatInviteRequest(hash_part))
                logger.info(f"ClickBee: Вступил по инвайту {hash_part}")
                return True
            except Exception as exc:
                logger.warning(f"ClickBee: ImportChatInviteRequest failed: {exc}")
        return False

    @staticmethod
    def _extract_button_url(event: Message, text_fragment: str) -> str | None:
        if not event.reply_markup:
            return None
        for row in event.reply_markup.rows:
            for button in row.buttons:
                if text_fragment in (button.text or ""):
                    return getattr(button, "url", None)
        return None

    @staticmethod
    async def _click_button(event: Message, text_fragment: str) -> bool:
        if not event.reply_markup:
            return False
        for row in event.reply_markup.rows:
            for button in row.buttons:
                if text_fragment in (button.text or ""):
                    with suppress(Exception):
                        await event.click(text=button.text)
                        return True
        return False

    @staticmethod
    def _parse_bot_username(text: str) -> str | None:
        """Извлекает username бота из текста, сохраняя параметры."""

        patterns = [
            r"(?:https?://)?t\.me/([a-zA-Z0-9_]{5,32}(?:\?[^\s)\]]*)?)",
            r"(?:https?://)?telegram\.me/([a-zA-Z0-9_]{5,32}(?:\?[^\s)\]]*)?)",
            r"@([a-zA-Z0-9_]{5,32}(?:\?[^\s)\]]*)?)",
            r"\[.*?\]\((?:https?://)?t\.me/([a-zA-Z0-9_]{5,32}(?:\?[^\s)\]]*)?)\)",
            r"\[.*?\]\((?:https?://)?telegram\.me/([a-zA-Z0-9_]{5,32}(?:\?[^\s)\]]*)?)\)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                username = match.group(1)
                if "_bot" in username.lower() or "bot" in username.lower() or "🔗" in text:
                    return username

        fallback = re.search(r"([a-zA-Z0-9_]{5,32}_bot)(?:[?\s/#)\]]|$)", text, re.IGNORECASE)
        if fallback:
            return fallback.group(1)

        return None

    @staticmethod
    def _parse_channel_link(text: str) -> str | None:
        """Извлекает ссылку/username канала из текста задания."""
        for line in text.split("\n"):
            if "this Telegram channel" in line or "join" in line.lower():
                m = re.search(r"\]\((https?://t\.me/[^\)]+)\)", line)
                if m:
                    return m.group(1)
                m = re.search(r"t\.me/([^\s\)]+)", line)
                if m:
                    return f"https://t.me/{m.group(1)}"
                m = re.search(r"@([A-Za-z0-9_]{5,32})", line)
                if m:
                    return m.group(1)
        return None
