import asyncio
import random
import re

from loguru import logger
from telethon import TelegramClient, events
from telethon.tl.custom import Message
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest

from . import settings

logger.info(f"Загружен модуль {__name__}!")
TASK_BUTTONS = ["🤖 Join Bots", "💻 Visit Sites", "📢 Join Channels"]


class _CyclicIterator:
    """Циклический итератор по списку строк с возможностью отслеживать текущую позицию."""

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


class ClickBeeAutomation:
    """Автозаработок на ClickBee-ботах.
    - start() / stop() для управления жизненным циклом
    - toggle() как обработчик команды `.авто clickbee`
    - _process_message() для обработки входящих сообщений от текущего бота
    """

    def __init__(
        self,
        client: TelegramClient,
        user_settings: "settings.UBSettings",
    ) -> None:
        self.client = client
        self.settings = user_settings
        self._active = False
        self._lock = asyncio.Lock()
        self._handler = None
        self._task_iter = _CyclicIterator(TASK_BUTTONS)
    async def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._task_iter.reset()
        self.bot: str = await self.settings.get("clickbee.username")
        self._register_handler()
        logger.info("ClickBee запущен")
        await asyncio.sleep(2)
        await self.client.send_message(self.bot, self._task_iter.next())

    def stop(self) -> None:
        self._active = False
        self._unregister_handler()
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
            self.client.remove_event_handler(self._handler)
            self._handler = None

    async def _process_message(self, event: Message) -> None:
        if not self._active:
            return
        text = event.text or ""
        await event.mark_read()
        await asyncio.sleep(random.uniform(2, 5))
        if "browse the website" in text:
            await self._handle_website(event)
        elif "You've earned" in text:
            await self._handle_earned(event)
        elif "NO TASKS" in text:
            await self._handle_no_tasks(event)
        elif "then forward any message" in text:
            await self._handle_forward_check(event)
        elif "FORWARD a message from that bot" in text:
            await self._handle_forward_bot(event)
        elif "and join it" in text:
            await self._handle_join_channel(event)
        elif "error" in text.lower():
            await self._handle_error(event)
        elif "new task" in text.lower():
            await self._handle_new_task(event)

    async def _handle_website(self, event: Message) -> None:
        """Обработка задания 'visit site': нажимаем Open, ждём таймер, переходим дальше."""
        if not event.reply_markup:
            return await self._next_task(event)
        for row in event.reply_markup.rows:
            for button in row.buttons:
                if "Open" in (button.text or ""):
                    url = getattr(button, "url", "")
                    clean_url = re.sub(r"\?.*", "", url) if url else url
                    logger.info(f"ClickBee: Открываю сайт {clean_url}")
                    sleep_time = await self.settings.get("clickbee.site_wait", 50)
                    await asyncio.sleep(sleep_time + random.randint(3, 10))
                    return await self._next_task(event)
        await self._next_task(event)
        return None

    async def _handle_earned(self, event: Message) -> None:
        logger.info(f"ClickBee: {event.text}")
        logger.info("ClickBee: Проверяю другие задачи")
        await self._next_task(event)

    async def _handle_no_tasks(self, event: Message) -> None:
        logger.info("ClickBee: Нет задач для текущей категории")
        task = self._task_iter.next()
        if self._task_iter._index % (len(TASK_BUTTONS) + 1) == 0:
            await self._switch_bot(event)
        else:
            await event.respond(task)

    async def _handle_forward_check(self, event: Message) -> None:
        """Нажимаем кнопку подтверждения (с галочкой)."""
        if not event.reply_markup:
            return None
        for row in event.reply_markup.rows:
            for button in row.buttons:
                if "✅" in (button.text or ""):
                    return await event.click(text=button.text)
        return None

    async def _handle_forward_bot(self, event: Message) -> None:
        """Задание: пересылка сообщения от стороннего бота."""
        mybot = None
        for line in (event.text or "").split("\n"):
            if "Open the bot" in line:
                mybot = (
                    line.split("](")[1]
                    .replace(")", "")
                    .replace("https://t.me/", "")
                    .split("?")[0]
                    .split("/")[0]
                )
                break
        if not mybot:
            return await self._next_task(event)
        logger.info(f"ClickBee: Отправляю /start боту {mybot}")
        try:
            async with self.client.conversation(mybot, timeout=30, total_timeout=30) as conv:
                await conv.send_message("/start")
                response = await conv.get_response()
                await self.client.forward_messages(
                    entity=event.sender_id,
                    messages=response.id,
                    from_peer=response.sender_id,
                )
        except Exception:
            logger.info("ClickBee: Бот не отвечает, пропускаю")
            await event.respond("🔙 Back")
            await asyncio.sleep(5)
            await self._next_task(event)

    async def _handle_join_channel(self, event: Message) -> None:
        """Задание: вступить в канал."""
        channel_name = None
        for line in (event.text or "").split("\n"):
            if "this Telegram channel" in line:
                channel_name = line.split("](")[1].split(")")[0]
                break
        if channel_name:
            try:
                await self.client(JoinChannelRequest(channel_name))
                logger.info(f"ClickBee: Вступаю в канал {channel_name}")
            except Exception:
                try:
                    hash_part = channel_name.split("/")[-1].replace("+", "")
                    await self.client(ImportChatInviteRequest(hash_part))
                    logger.info(f"ClickBee: Вступаю по инвайту {channel_name}")
                except Exception:
                    logger.info(f"ClickBee: Не смог вступить в {channel_name}")
                    if event.reply_markup:
                        for row in event.reply_markup.rows:
                            for button in row.buttons:
                                if "Skip" in (button.text or ""):
                                    return await event.click(text=button.text)
        if event.reply_markup:
            for row in event.reply_markup.rows:
                for button in row.buttons:
                    if "✅" in (button.text or ""):
                        return await event.click(text=button.text)
        return None

    async def _handle_error(self, event: Message) -> None:
        logger.info("ClickBee: Ошибка от бота, перехожу к следующей задаче")
        await self._next_task(event)

    async def _handle_new_task(self, event: Message) -> None:
        logger.info("ClickBee: Новые задачи доступны!")
        await self._next_task(event)

    async def _next_task(self, event: Message) -> None:
        """Запрашивает следующую категорию задач у текущего бота."""
        if not self._active:
            return
        task = self._task_iter.next()
        await asyncio.sleep(random.uniform(1, 3))
        await event.respond(task)

    async def _switch_bot(self, event: Message) -> None:
        """Сон."""
        if not self._active:
            return
        self._task_iter.reset()
        sleep_time = await self.settings.get("clickbee.sleep_between", 300)
        jitter = random.randint(-30, 30)
        actual_sleep = max(30, sleep_time + jitter)
        logger.info(f"ClickBee: Сплю {actual_sleep}с")
        await asyncio.sleep(actual_sleep)
        if not self._active:
            return
        first_task = self._task_iter.next()
        await self.client.send_message(self.bot, first_task)
