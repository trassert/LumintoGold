import asyncio
import contextlib
import logging
import os
import random
import re
import sys
from functools import partial
from pathlib import Path
from time import time

import aiofiles
from loguru import logger
from telethon import TelegramClient, errors, events, functions, types
from telethon.network.connection import ConnectionTcpObfuscated
from telethon.tl.custom import Message
from telethon.tl.functions.account import (
    UpdateProfileRequest,
    UpdateStatusRequest,
)
from telethon.tl.functions.messages import (
    GetChatInviteImportersRequest,
    HideChatJoinRequestRequest,
)
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import (
    MessageMediaDocument,
    MessageService,
    PeerUser,
    User,
)
from vkbottle import Bot
from vkbottle.tools import PhotoWallUploader

from modules import phrase

logger.remove()
logger.add(
    sys.stderr,
    format=(
        "[{time:HH:mm:ss} <level>{level}</level>]: <green>{file}:{function}</green> > {message}"
    ),
    level="INFO",
    colorize=True,
    backtrace=False,
    diagnose=False,
    enqueue=False,
)
logger.info(phrase.misc.startup)


class InterceptHandler(logging.Handler):
    def emit(self, record):
        level = "TRACE" if record.levelno == 5 else record.levelname
        logger.opt(depth=6, exception=record.exc_info).log(
            level, record.getMessage()
        )


logging.basicConfig(handlers=[InterceptHandler()], level=0)
_managers: dict[str, UserbotManager] = {}
_manager_tasks: dict[str, asyncio.Task] = {}
_client_status: dict[str, dict] = {}
_client_locks: dict[str, asyncio.Lock] = {}


class ClientNotAuthorized(Exception):
    pass


def _set_status(phone: str, status: str, error: str | None = None) -> None:
    _client_status[phone] = {
        "status": status,
        "error": error,
        "since": time(),
    }


def _client_lock(phone: str) -> asyncio.Lock:
    if phone not in _client_locks:
        _client_locks[phone] = asyncio.Lock()
    return _client_locks[phone]


def _session_exists(phone: str) -> bool:
    return (pathes.sessions / f"{phone}.session").exists()


def _make_client(
    phone: str,
    api_id: int,
    api_hash: str,
    session_path: Path | None = None,
    connection_retries: int | None = None,
) -> TelegramClient:
    telegram = config.config.telegram
    return TelegramClient(
        session=str(session_path or pathes.sessions / phone),
        api_id=api_id,
        api_hash=api_hash,
        use_ipv6=config.config.use_ipv6,
        system_version=str(telegram.system_version),
        device_model=str(telegram.device_model),
        system_lang_code=str(telegram.system_lang_code),
        lang_code=str(telegram.lang_code),
        connection_retries=(
            connection_retries
            if connection_retries is not None
            else int(telegram.connection_retries)
        ),
        retry_delay=int(telegram.retry_delay),
        connection=ConnectionTcpObfuscated,
    )


def _as_number(value, cast, fallback):
    try:
        return cast(value)
    except TypeError, ValueError:
        return fallback


_TASK_CONFIG = {
    "iris.farm": (4, "hours", (5, 360), (phrase.farm.on, phrase.farm.off)),
    "iceyes.bonus": (1, "hours", (1, 60), (phrase.bonus.on, phrase.bonus.off)),
    "auto.online": (30, "seconds", None, (phrase.online.on, phrase.online.off)),
    "battery.status": (
        15,
        "seconds",
        None,
        (phrase.battmon.on, phrase.battmon.off),
    ),
}


class UserbotManager:
    def __init__(self, phone: str, api_id: int, api_hash: str):
        self.phone = phone
        self.settings = settings.UBSettings(phone, pathes.clients)
        self.voice_path = pathes.voice / phone
        self.client = _make_client(
            phone, api_id, api_hash, pathes.sessions / phone
        )
        self.iris_task = task_gen.Generator(f"{phone}_iris")
        self.online_task = task_gen.Generator(f"{phone}_online")
        self.iceyes_task = task_gen.Generator(f"{phone}_iceyes")
        self.battery_task = task_gen.Generator(f"{phone}_battery")
        self.batt_state = True
        self.notes = notes.Notes(phone)
        self.flood_ctrl = flood.FloodController(self.client, self.settings)
        self.autochat = autochat.AutoChatManager(self.client, self.settings)
        self.vktarget = vktarget_bot.VKTargetRefactored(
            self.client, self.settings, logger
        )
        self.clickbee = clickbee.ClickBeeAutomation(self.client, self.settings)
        self._stopped = False
        self.status = "starting"
        self.error: str | None = None
        self._task_signatures: dict[str, tuple] = {}
        self._ai_signature: tuple | None = None
        self.ai_client = None
        self.ai_chat = None

    async def init(self):
        use_ipv6 = await self.settings.get("use.ipv6")
        self.client.use_ipv6 = use_ipv6
        await self.client.connect()
        if not await self.client.is_user_authorized():
            raise ClientNotAuthorized(
                "Нет авторизации — войдите через веб-панель"
            )
        logger.info(f"Запущен клиент ({self.phone})")
        self._register_handlers()
        await self.apply_features()
        self.telemt_client = telemt.TelemtClient(
            base_url=await self.settings.get("telemt.url"),
            auth_token=await self.settings.get("telemt.token"),
        )
        try:
            await self.telemt_client.health_check()
            logger.info("Успешно подключился к Telemt API")
        except Exception:
            logger.warning(
                "Не удалось подключиться к Telemt API. Проверьте URL и токен."
            )

    async def _sync_task(
        self,
        name,
        generator,
        enabled_key,
        func,
        interval_key,
        unit="hours",
        random_keys=None,
    ):
        if not await self.settings.get(enabled_key):
            generator.stop()
            self._task_signatures.pop(name, None)
            return
        # Если интервал не сохранён в файле клиента, берём дефолт реестра/UI.
        fallback = _TASK_CONFIG[enabled_key][0]
        interval = max(1, int(await self.settings.get(interval_key, fallback)))
        random_delay = None
        if random_keys:
            low = max(0, int(await self.settings.get(random_keys[0], 0)))
            high = max(low, int(await self.settings.get(random_keys[1], low)))
            random_delay = (low, high)
        signature = (interval, random_delay)
        if (
            generator.is_running
            and self._task_signatures.get(name) == signature
        ):
            return
        await generator.create(
            func=func,
            task_param=interval,
            random_delay=random_delay,
            unit=unit,
        )
        self._task_signatures[name] = signature

    async def _sync_iris(self):
        await self._sync_task(
            "iris",
            self.iris_task,
            "iris.farm",
            self.iris_farm,
            "iris.farm.interval",
            "hours",
            ("iris.farm.random_min", "iris.farm.random_max"),
        )

    async def _sync_iceyes(self):
        await self._sync_task(
            "iceyes",
            self.iceyes_task,
            "iceyes.bonus",
            self.iceyes_bonus,
            "iceyes.bonus.interval",
            "hours",
            ("iceyes.bonus.random_min", "iceyes.bonus.random_max"),
        )

    async def _sync_online(self):
        await self._sync_task(
            "online",
            self.online_task,
            "auto.online",
            self.auto_online,
            "auto.online.interval",
            "seconds",
        )

    async def _sync_battery(self):
        await self._sync_task(
            "battery",
            self.battery_task,
            "battery.status",
            self.chk_battery,
            "battery.status.interval",
            "seconds",
        )

    async def _sync_ai(self):
        token = await self.settings.get("token.groq")
        proxy = await self.settings.get("groq.proxy")
        model = await self.settings.get("ai.model") or "openai/gpt-oss-120b"
        voice_model = (
            await self.settings.get("ai.voice_model")
            or "whisper-large-v3-turbo"
        )
        temperature = _as_number(
            await self.settings.get("ai.temperature", 1.0), float, 1.0
        )
        max_tokens = _as_number(
            await self.settings.get("ai.max_tokens", 2048), int, 2048
        )
        signature = (
            str(token or ""),
            str(proxy or ""),
            str(model),
            str(voice_model),
            temperature,
            max_tokens,
        )
        if (
            token
            and self.ai_client is not None
            and self._ai_signature == signature
        ):
            return
        old_client = self.ai_client
        if old_client is not None:
            with contextlib.suppress(Exception):
                await old_client.close()
        self.ai_client = None
        self.ai_chat = None
        self._ai_signature = None
        if not token:
            logger.warning("Установите Groq-токен (.иитокен <токен>)")
            return
        try:
            client = ai.GroqClient(
                api_key=token,
                proxy=proxy,
                chat_model=model,
                voice_model=voice_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            client.init_client()
            self.ai_client = client
            self.ai_chat = client.chat(self.phone)
            self._ai_signature = signature
        except Exception:
            logger.exception("Не удалось инициализировать Groq-клиент")

    async def _sync_block_voice(self):
        with contextlib.suppress(Exception):
            self.client.remove_event_handler(self.block_voice)
        if await self.settings.get("block.voice"):
            self.client.add_event_handler(self.block_voice, events.NewMessage())

    async def _sync_reactions(self):
        with contextlib.suppress(Exception):
            self.client.remove_event_handler(self.reactions)
        if await self.settings.get("luminto.reactions"):
            for chat in ("lumintoch", "luminto_faq"):
                self.client.add_event_handler(
                    self.reactions, events.NewMessage(chats=chat)
                )

    async def _sync_tg2vk(self):
        with contextlib.suppress(Exception):
            self.client.remove_event_handler(self._handle_tg_to_vk)
        if not await self.settings.get("tg2vk.enabled"):
            return
        target_chat = await self.settings.get("tg2vk.chat")
        if isinstance(target_chat, str):
            raw_chat = target_chat.strip()
            if raw_chat.lstrip("-").isdigit():
                target_chat = int(raw_chat)
        if not target_chat:
            logger.warning(f"tg2vk ({self.phone}): не задан tg2vk.chat")
            return
        self.client.add_event_handler(
            self._handle_tg_to_vk,
            events.NewMessage(chats=target_chat),
        )

    async def _sync_vktarget(self):
        enabled = bool(await self.settings.get("vktarget.enabled"))
        active = bool(getattr(self.vktarget, "_active", False))
        if enabled and not active:
            await self.vktarget.start()
        elif not enabled and active:
            self.vktarget.stop()

    async def _sync_autochat(self):
        enabled = bool(await self.settings.get("autochat.enabled"))
        running = bool(getattr(self.autochat, "_running", False))
        if enabled and not running:
            await self.autochat.start()
        elif not enabled and running:
            await self.autochat.stop()

    async def _sync_clickbee(self):
        enabled = bool(await self.settings.get("clickbee.enabled"))
        active = bool(getattr(self.clickbee, "_active", False))
        if enabled and not active:
            await self.clickbee.start()
        elif not enabled and active:
            self.clickbee.stop()

    async def apply_features(self) -> None:
        """Применяет функции клиента без полного перезапуска."""
        if self._stopped:
            return
        steps = (
            ("AI", self._sync_ai),
            ("Iris", self._sync_iris),
            ("Iceyes", self._sync_iceyes),
            ("Онлайн", self._sync_online),
            ("Батарея", self._sync_battery),
            ("Голосовые", self._sync_block_voice),
            ("Реакции", self._sync_reactions),
            ("TG → VK", self._sync_tg2vk),
            ("VKTarget", self._sync_vktarget),
            ("AutoChat", self._sync_autochat),
            ("ClickBee", self._sync_clickbee),
        )
        for label, step in steps:
            try:
                await step()
            except Exception:
                logger.exception(f"Не удалось применить {label} у {self.phone}")

    def _register_handlers(self):
        def on(pattern, handler):
            self.client.on(d.cmd(pattern))(handler)

        on(r"\.тгвк$", self.toggle_tg_to_vk)
        on(r"\.\$(.+)", self.run_shell)
        on(r"\+зам (.+)\n([\s\S]+)", self.add_note)
        on(r"\-зам (.+)", self.rm_note)
        on(r"\!(.+)", self.chk_note)
        on(r"\.замы$", self.list_notes)
        on(r"\.чистка$", self.clean_pm)
        on(r"\.(?:help|помощь)$", self.help)
        on(r"\.чсчистка$", self.clean_blacklist)
        on(r"\.voice$", self.voice2text)
        on(r"\.баттмон$", self.toggle_batt)
        on(r"\.чатчистка$", self.clean_chat)
        on(r"\.слов", self.words)
        on(r"\.пинг$", self.ping)
        on(r"\.эмоид$", self.get_emo_id)
        on(r"\.флип", self.flip_text)
        on(r"\.гс$", self.on_off_block_voice)
        on(r"\.читать$", self.on_off_mask_read)
        on(r"\.серв$", self.server_load)
        on(r"\.релоадконфиг$", self.config_reload)
        on(r"\.автоферма$", self.on_off_farming)
        on(r"\.афк$", self.afk_bio)
        on(r"\.онлайн$", self.toggle_online)
        on(r"\.автобонус$", self.on_off_bonus)
        on(r"\.авто vktarget_bot$", self.toggle_vktarget)
        on(r"\.авто clickbee$", self.clickbee.toggle)
        on(r"\.id (.+)", self.get_id)
        on(r"\.иичистка", self.ai_clear)
        on(r"\.иипрокси (.+)", self.ai_proxy)
        on(r"\.иипрокси$", self.ai_proxy_delete)
        on(r"\.иитокен (.+)", self.ai_token)
        on(r"\.иимодель (.+)", self.ai_model)
        on(r"\.прокси(.*)", self.fp)
        on(r"\.погода (.+)", self.get_weather)
        on(r"\.ip (.+)", self.ipman)
        on(r"\.кв (.+)", self.currencyconventer)
        on(r"\.аним (.+)", self.anim)
        on(r"\.ии ([\s\S]+)", self.ai_resp)
        on(r"\.т ([\s\S]+)", self.typing)
        on(r"\.set (.+)", self.set_setting)
        on(r"\.setint (.+)", self.set_int_setting)
        on(r"\.время (.+)", self.time_by_city)
        on(r"\.ад(?:\s|$)", self.autodelmsg)
        on(r"\+авточат (-?\d+)", self.autochat.add_chat)
        on(r"\-авточат (-?\d+)", self.autochat.remove_chat)
        on(r"\.авточат$", self.autochat.toggle)
        on(r"\.авточаттайм (\d+)", self.autochat.set_delay)
        on(r"\.(?:калк|к|calc) (.+)", self.calc)
        on(r"\.(?:телемт|telemt)$", self.telemt_info)
        on(r"\+(?:телемт юзер|telemt user) (.+)", self.telemt_adduser)
        on(r"\-(?:телемт юзер|telemt user) (.+)", self.telemt_deluser)
        self.client.on(events.NewMessage())(self._dynamic_mask_reader)
        on(r"\.(?:genpass|генпасс|пароль)(?:\s+(.+))?", self.gen_pass)
        self.client.on(events.NewMessage())(self.flood_ctrl.monitor)
        for kind, rule in (
            ("стики", "stickers"),
            ("гиф", "gifs"),
            ("общ", "messages"),
        ):
            on(
                rf"\-флуд{kind} (\d+) (\d+)$",
                partial(self.flood_ctrl.set_rule, rule_type=rule),
            )
            on(
                rf"\+флуд{kind}$",
                partial(self.flood_ctrl.unset_rule, rule_type=rule),
            )

    async def afk_bio(self, event: Message):
        if await self.settings.get("toggle.afk") is True:
            await self.settings.set("toggle.afk", False)
            await self.client(
                UpdateProfileRequest(
                    about=await self.settings.get("bio.normal")
                )
            )
            return await event.edit(phrase.afk.unset)
        bio = (
            await self.client(
                GetFullUserRequest((await self.client.get_me()).id)
            )
        ).full_user.about
        await self.settings.set("bio.normal", bio)
        await self.settings.set("toggle.afk", True)
        await self.client(
            UpdateProfileRequest(about=await self.settings.get("bio.afk"))
        )
        return await event.edit(phrase.afk.set)

    async def stop(self):
        """Disconnect the client and cancel background tasks."""
        if self._stopped:
            return
        self._stopped = True
        self.status = "stopping"
        logger.info(f"Останавливаю клиент ({self.phone})…")
        for task in (
            self.iris_task,
            self.online_task,
            self.iceyes_task,
            self.battery_task,
        ):
            with contextlib.suppress(Exception):
                task.stop()
        for action in (self.vktarget.stop, self.clickbee.stop):
            with contextlib.suppress(Exception):
                action()
        with contextlib.suppress(Exception):
            await self.autochat.stop()
        for handler in (
            self.block_voice,
            self.reactions,
            self._handle_tg_to_vk,
        ):
            with contextlib.suppress(Exception):
                self.client.remove_event_handler(handler)
        self._task_signatures.clear()
        if self.ai_client is not None:
            with contextlib.suppress(Exception):
                await self.ai_client.close()
            self.ai_client = None
            self.ai_chat = None
        with contextlib.suppress(Exception):
            await self.client.disconnect()
        self.status = "stopped"
        logger.info(f"Клиент ({self.phone}) остановлен.")

    async def telemt_adduser(self, event: Message):
        username = event.pattern_match.group(1).strip()
        if not re.match(r"^[a-zA-Z0-9_]{3,32}$", username):
            return await event.edit(phrase.telemt.incorrect_username)
        reg = telemt.CreateUserRequest(username=username)
        user, secret, links = await self.telemt_client.create_user_with_links(
            reg
        )
        link_dd = links.get("secure", "Недоступно")
        link_tls = links.get("tls", "Недоступно")
        return await event.edit(
            phrase.telemt.new_user.format(
                user=user.username, secret=secret, tls=link_tls, dd=link_dd
            )
        )

    async def telemt_deluser(self, event: Message):
        username = event.pattern_match.group(1).strip()
        if not re.match(r"^[a-zA-Z0-9_]{3,32}$", username):
            return await event.edit(phrase.telemt.incorrect_username)
        user = await self.telemt_client.delete_user(username)
        return await event.edit(phrase.telemt.del_user.format(user=user))

    async def telemt_info(self, event: Message):
        users = await self.telemt_client.list_users()
        info = await self.telemt_client.get_system_info()
        users_list = [
            f"» **{user.username}** - {get_sys.human(user.total_octets)}"
            for user in sorted(
                users, key=lambda u: u.total_octets, reverse=True
            )
        ]
        return await event.edit(
            phrase.telemt.info.format(
                version=info.get("version"),
                arch=info.get("target_arch"),
                users="\n".join(users_list),
            )
        )

    async def currencyconventer(self, event: Message):
        arg = event.pattern_match.group(1).strip().split()
        if len(arg) == 2 and arg[1].isdigit():
            currency, count = format.normalize_currency(arg[0]), int(arg[1])
        elif len(arg) == 1:
            currency, count = format.normalize_currency(arg[0]), 1
        else:
            return await event.edit(phrase.currency.invalid)
        result = await apis.conv_currency(
            currency,
            count,
            await self.settings.get("default.currency"),
            token=await self.settings.get("token.exchangerate"),
        )
        return await event.edit(result)

    async def fp(self, event: Message):
        arg = event.pattern_match.group(1).strip().lower()
        proxy_type = arg if arg in ("http", "socks4", "socks5") else None
        await event.edit(phrase.fp.wait)
        proxies = await ipman.get_working_proxies(proxy_type=proxy_type)
        if not proxies:
            return await event.edit(phrase.fp.not_found)
        text = ""
        for proxy in proxies:
            ip, port = proxy[1].split(":")
            text += f"**{proxy[0]}** - `{ip}`:`{port}` ({proxy[2]} мс)\n"
        return await event.edit(
            phrase.fp.result.format(count=len(proxies), proxys=text)
        )

    async def help(self, event: Message):
        return await event.edit(phrase.help.text, link_preview=False)

    async def clean_chat(self, event: Message):
        if event.is_private:
            return await event.edit(phrase.clear.private)
        chat = await event.get_chat()
        if not hasattr(chat, "title"):
            return await event.edit(phrase.not_a_chat)
        try:
            me = await self.client.get_me()
            admin_rights = await self.client.get_permissions(chat, me)
            if not admin_rights.ban_users:
                return await event.edit(phrase.clear.no_rights)
        except Exception:
            return await event.edit(phrase.clear.no_rights)
        await event.edit(phrase.clear.start)
        kicked = 0
        unbanned = 0
        rejected = 0

        try:
            invite_importers = await self.client(
                GetChatInviteImportersRequest(
                    peer=chat,
                    requested=True,
                    offset_date=None,
                    offset_user=types.InputUserEmpty(),
                    limit=1000,
                )
            )
            for importer in invite_importers.importers:
                uid = importer.user_id
                user = await self.client.get_entity(uid)
                if uid and user.deleted:
                    with contextlib.suppress(Exception):
                        await self.client(
                            HideChatJoinRequestRequest(
                                peer=chat, user_id=uid, approved=False
                            )
                        )
                    rejected += 1
                    if rejected % 5 == 0:
                        await event.edit(
                            phrase.clear.reject.format(count=rejected)
                        )
                await asyncio.sleep(await self.settings.get("typing.delay"))
        except Exception as e:
            logger.error(f"Не удалось проверить заявки: {e}")

        async for user in self.client.iter_participants(chat):
            if user.deleted:
                try:
                    await self.client.kick_participant(chat, user.id)
                    kicked += 1
                    if kicked % 5 == 0:
                        await event.edit(phrase.clear.kick.format(count=kicked))
                except Exception:
                    logger.trace("Не могу удалить участника")
            await asyncio.sleep(await self.settings.get("typing.delay"))
        async for user in self.client.iter_participants(
            chat, filter=types.ChannelParticipantsKicked
        ):
            if user and user.deleted:
                try:
                    await self.client.edit_permission(
                        chat, user.id, view_messages=True
                    )
                    unbanned += 1
                    if unbanned % 5 == 0:
                        await event.edit(
                            phrase.clear.unban.format(count=unbanned)
                        )
                except Exception:
                    logger.trace("Не могу вынести из бана участника")
            await asyncio.sleep(await self.settings.get("typing.delay"))
        if kicked or unbanned or rejected:
            await event.edit(
                phrase.clear.done.format(
                    kicked=kicked, unbanned=unbanned, rejected=rejected
                )
            )
        else:
            await event.edit(phrase.clear.not_found)
        return None

    async def chk_battery(self):
        async with aiofiles.open(config.config.battery_path) as f:
            discharging = "Discharging" in await f.read()
        if discharging == self.batt_state:
            key = "battery.msg_no" if discharging else "battery.msg_yes"
            if discharging:
                logger.warning("Нет зарядки!")
            await self.client.send_message(
                entity=int(await self.settings.get("battery.chat")),
                message=await self.settings.get(key),
            )
            self.batt_state = not discharging

    async def reactions(self, event: Message):
        await asyncio.sleep(random.randint(0, 1000))
        try:
            await self.client(
                functions.messages.SendReactionRequest(
                    peer=event.peer_id,
                    msg_id=event.message.id,
                    big=True,
                    add_to_recent=True,
                    reaction=[types.ReactionEmoji(emoticon="❤️")],
                ),
            )
            logger.info("Отправил реакцию!")
        except Exception:
            pass

    async def toggle_tg_to_vk(self, event: Message):
        enabled = await self.settings.get("tg2vk.enabled", False)
        target_chat = await self.settings.get("tg2vk.chat")
        vk_group = await self.settings.get("tg2vk.vk_group")
        vk_token = await self.settings.get("vk.token")
        if not target_chat:
            await self.settings.set("tg2vk.enabled", False)
            return await event.edit(phrase.tg2vk.missing_config)
        if not enabled:
            if not vk_group or not vk_token:
                await self.settings.set("tg2vk.enabled", False)
                return await event.edit(phrase.tg2vk.missing_config)
            logger.debug("tg2vk: enabled")
            self.client.add_event_handler(
                self._handle_tg_to_vk,
                events.NewMessage(chats=target_chat),
            )
            await self.settings.set("tg2vk.enabled", True)
            await event.edit(phrase.tg2vk.on)
        else:
            logger.debug("tg2vk: disabled")
            self.client.remove_event_handler(self._handle_tg_to_vk)
            await self.settings.set("tg2vk.enabled", False)
            await event.edit(phrase.tg2vk.off)
        return None

    async def _handle_tg_to_vk(self, event: Message):
        logger.info("tg2vk: Новый пост")
        vk_token = await self.settings.get("vk.token")
        vk_group_id = await self.settings.get("tg2vk.vk_group")
        if not vk_token or not vk_group_id:
            return logger.error("tg2vk: Отсутствует токен или ID группы")
        attachments = []
        bot = Bot(token=vk_token)
        try:
            text = format.f2vk(event.text)
            if event.photo:
                path = await event.download_media(file=bytes)
                uploader = PhotoWallUploader(bot.api)
                photo = await uploader.upload(path)
                attachments.append(photo)
            resp = await bot.api.wall.post(
                owner_id=-abs(int(vk_group_id)),
                message=text,
                attachments=attachments,
            )
            logger.info(f"tg2vk: Пост опубликован (ID={resp.post_id})")
        except Exception:
            logger.trace("tg2vk: Ошибка публикации")

    async def get_emo_id(self, event: Message):
        message: Message = await event.get_reply_message()
        if message is None or not message.entities:
            return await event.edit(phrase.emoji.no_entity)
        text = [
            f"`{entity.document_id}`"
            for entity in message.entities
            if hasattr(entity, "document_id")
        ]
        if not text:
            return await event.edit(phrase.emoji.no_entity)
        return await event.edit(phrase.emoji.get.format(", ".join(text)))

    async def iris_farm(self):
        target = int(
            await self.settings.get("iris.farm.target", -1002355128955)
        )
        bot = str(await self.settings.get("iris.farm.bot", "iris_cm_bot"))
        try:
            await self.client.send_message(
                target, random.choice(phrase.iris.farm_cmds)
            )
        except Exception:
            await self.client.send_message(
                bot, random.choice(phrase.iris.farm_cmds)
            )
        logger.info(f"{self.phone} - сработала автоферма")

    async def iceyes_bonus(self):
        await self.client.send_message("iceyes_bot", phrase.iceyes.bonus_msg)
        await self.client.send_message("icetik_bot", phrase.iceyes.bonus_msg)
        logger.info(f"{self.phone} - сработал автобонус")

    async def add_note(self, event: Message):
        full_text = event.message.message or ""
        name = event.pattern_match.group(1).strip().lower()
        note_text = ""
        if "\n" in full_text:
            note_text = full_text.split("\n", maxsplit=1)[1]
        media = None
        if event.photo:
            media = event.photo
        elif event.is_reply:
            reply = await event.get_reply_message()
            if reply and reply.photo:
                media = reply.photo
        result = await self.notes.add(
            name, note_text, media=media, client=self.client
        )
        if result is False:
            return await event.edit(
                phrase.notes.error.format(phrase.notes.err_cr)
            )
        return await event.edit(phrase.notes.new.format(name))

    async def rm_note(self, event: Message):
        name = event.pattern_match.group(1).strip().lower()
        if (await self.notes.delete(name)) is False:
            return await event.edit(
                phrase.notes.error.format(phrase.notes.err_rm)
            )
        return await event.edit(phrase.notes.deleted)

    async def chk_note(self, event: Message):
        arg: str = event.pattern_match.group(1)
        if arg.isdigit():
            note = await self.notes.get_by_index(int(arg))
        else:
            note = await self.notes.get(arg)
        if not note:
            return await event.edit(phrase.notes.not_found)
        if note.get("media"):
            return await event.edit(note["text"], file=note["media"])
        return await event.edit(note["text"])

    async def list_notes(self, event: Message):
        list_notes = await self.notes.get_list()
        if not list_notes:
            return await event.edit(phrase.notes.allnotext)
        text = [
            f"{i + 1}. {name.capitalize()}" for i, name in enumerate(list_notes)
        ]
        return await event.edit(phrase.notes.alltext.format("\n".join(text)))

    async def auto_online(self):
        await self.client(UpdateStatusRequest(offline=False))

    async def _toggle_setting_and_task(self, setting_key, task, event, func):
        enabled = not await self.settings.get(setting_key)
        await self.settings.set(setting_key, enabled)
        param, unit, delay, phrases = _TASK_CONFIG[setting_key]
        if enabled:
            options = {"random_delay": delay} if delay else {}
            await task.create(func=func, task_param=param, unit=unit, **options)
        else:
            task.stop()
        await event.edit(phrases[0] if enabled else phrases[1])

    async def on_off_farming(self, event: Message):
        await self._toggle_setting_and_task(
            "iris.farm", self.iris_task, event, self.iris_farm
        )

    async def on_off_bonus(self, event: Message):
        await self._toggle_setting_and_task(
            "iceyes.bonus", self.iceyes_task, event, self.iceyes_bonus
        )

    async def toggle_online(self, event: Message):
        await self._toggle_setting_and_task(
            "auto.online", self.online_task, event, self.auto_online
        )

    async def toggle_vktarget(self, event: Message):
        enabled = not await self.settings.get("vktarget.enabled", False)
        await self.settings.set("vktarget.enabled", enabled)
        if enabled:
            await self.vktarget.start()
            await event.edit(phrase.vktarget.on)
        else:
            self.vktarget.stop()
            await event.edit(phrase.vktarget.off)

    async def toggle_batt(self, event: Message):
        await self._toggle_setting_and_task(
            "battery.status", self.battery_task, event, self.chk_battery
        )

    async def on_off_block_voice(self, event: Message):
        enabled = not await self.settings.get("block.voice")
        await self.settings.set("block.voice", enabled)
        if enabled:
            self.client.add_event_handler(self.block_voice, events.NewMessage())
            await event.edit(phrase.voice.block)
        else:
            self.client.remove_event_handler(self.block_voice)
            await event.edit(phrase.voice.unblock)

    async def on_off_mask_read(self, event: Message):
        mask_read_chats = await self.settings.get("mask.read") or []
        if event.chat_id in mask_read_chats:
            mask_read_chats.remove(event.chat_id)
            await event.edit(phrase.read.off)
        else:
            mask_read_chats.append(event.chat_id)
            await event.edit(phrase.read.on)
        await self.settings.set("mask.read", mask_read_chats)

    async def _dynamic_mask_reader(self, event: Message):
        mask_read_chats = await self.settings.get("mask.read") or []
        if event.chat_id in mask_read_chats:
            await event.mark_read()

    async def block_voice(self, event: Message):
        if not isinstance(event.peer_id, PeerUser):
            return
        me = await self.client.get_me()
        if me.id == event.sender_id:
            return
        if isinstance(event.media, MessageMediaDocument) and event.media.voice:
            await event.delete()
            msg = await self.settings.get(
                "voice.message", phrase.voice.default_message
            )
            await event.respond(msg)

    async def voice2text(self, event: Message):
        reply: Message = await event.get_reply_message()
        if not reply or not reply.voice:
            return await event.edit(phrase.voicerec.no_reply)
        file_path = self.voice_path / f"voice_{event.id}.ogg"
        await reply.download_media(file=str(file_path))
        try:
            return await event.edit(
                phrase.voicerec.done.format(
                    await self.ai_client.transcribe_voice(self.phone, event.id),
                ),
            )
        except Exception as e:
            logger.exception("Ошибка при распознавании голоса")
            msg = phrase.voicerec.error.format(error=str(e)[:200])
            return await event.edit(msg)

    async def ai_proxy(self, event: Message):
        arg = event.pattern_match.group(1).strip()
        self.ai_client.proxy = arg
        await self.settings.set("groq.proxy", arg)
        self.ai_client.init_client()
        return await event.edit(phrase.voicerec.proxy)

    async def ai_proxy_delete(self, event: Message):
        self.ai_client.proxy = None
        await self.settings.set("groq.proxy", None)
        self.ai_client.init_client()
        return await event.edit(phrase.voicerec.delete_proxy)

    async def ai_token(self, event: Message):
        arg = event.pattern_match.group(1).strip()
        self.ai_client.api_key = arg
        await self.settings.set("token.groq", arg)
        self.ai_client.init_client()
        return await event.edit(phrase.voicerec.token)

    async def get_id(self, event: Message):
        arg = event.pattern_match.group(1).strip()
        result = [
            f"🆔 » {index} - `{await d.get_info(self.client, index)}`"
            for index in map(str.strip, arg.split())
        ]
        if result == []:
            return await event.edit(phrase.result_empty)
        return await event.edit("\n".join(result))

    async def ipman(self, event: Message):
        arg = event.pattern_match.group(1)
        if not ipman.is_valid_ip(arg):
            return await event.edit(phrase.ip.dont_match)
        response = await ipman.get_ip_info(arg)
        await event.edit(
            f"🌐 : IP: `{response.get('query')}`\n\n"
            f"Страна: {response.get('country')}\n"
            f"Регион: {response.get('regionName')}\n"
            f"Город: {response.get('city')}\n"
            f"Провайдер: {response.get('isp')}\n"
            f"Координаты: {response.get('lat')}/{response.get('lon')}",
        )
        return None

    async def get_weather(self, event: Message):
        await event.edit(phrase.weather.wait)
        result = await apis.get_weather(
            event.pattern_match.group(1),
            await self.settings.get("token.openweathermap"),
        )
        await event.edit(result)

    async def anim(self, event: Message):
        name = event.text.split(" ", maxsplit=1)[1]
        animation: dict = await db.get_animation(name)
        if not animation:
            return await event.edit(phrase.anim.no)
        for title in animation["text"]:
            await event.edit(title)
            await asyncio.sleep(animation["delay"])
        return None

    async def clean_pm(self, event: Message):
        dialogs = await self.client.get_dialogs()
        deleted_count = 0
        msg = await event.edit(phrase.pm.wait.format(0))
        deleted = []
        for dialog in dialogs:
            user: User = dialog.entity
            if not isinstance(user, User):
                continue
            if user.deleted or all(
                isinstance(item, MessageService)
                for item in await self.client.get_messages(user.id, limit=10)
            ):
                if user.first_name:
                    deleted.append(
                        f"[{user.first_name}](tg://user?id={user.id})"
                    )
                await self.client.delete_dialog(dialog.id)
                await asyncio.sleep(await self.settings.get("typing.delay"))
                deleted_count += 1
                if deleted_count % 5 == 0:
                    await msg.edit(phrase.pm.wait.format(deleted_count))
        await event.edit(
            phrase.pm.cleared.format(
                chats=deleted_count, list=", ".join(deleted)
            )
        )

    async def clean_blacklist(self, event: Message):
        blocked = []
        offset = 0
        limit = 1000
        msg = await event.edit(phrase.blacklist.scanning)
        while True:
            await asyncio.sleep(await self.settings.get("typing.delay"))
            result = await self.client(
                functions.contacts.GetBlockedRequest(
                    offset=offset, limit=limit
                ),
            )
            blocked.extend(result.users)
            if len(result.users) < limit:
                break
            offset += limit
        removed_count = 0
        removed_names = []
        for user in blocked:
            logger.info(f"BL scan @{user.id}")
            if not user.deleted:
                continue
            logger.info(f"Deleting @{user.id} from BL..")
            name = user.first_name or f"@{user.id}"
            removed_names.append(f"[{name}](tg://user?id={user.id})")
            try:
                await self.client(functions.contacts.UnblockRequest(id=user.id))
                removed_count += 1
            except errors.FloodWaitError as e:
                await asyncio.sleep(e.seconds)
                await self.client(functions.contacts.UnblockRequest(id=user.id))
                removed_count += 1
            if removed_count % 25 == 0 and removed_count > 0:
                await msg.edit(
                    phrase.blacklist.progress.format(count=removed_count)
                )
        names_str = ", ".join(removed_names[:20])
        if len(removed_names) > 20:
            names_str += f" и ещё {len(removed_names) - 20}"
        await msg.edit(
            phrase.blacklist.done.format(
                removed_count=removed_count,
                names_str=(names_str or "нет"),
            ),
        )

    async def set_setting(self, event: Message):
        key, value = event.pattern_match.group(1).split(" ", maxsplit=1)
        await self.settings.set(key, value)
        await event.edit(phrase.setting.set.format(key=key, value=value))

    async def set_int_setting(self, event: Message):
        key, value = event.pattern_match.group(1).split(" ", maxsplit=1)
        await self.settings.set(key, float(value))
        await event.edit(phrase.setting.setint.format(key=key, value=value))

    async def time_by_city(self, event: Message):
        city = event.pattern_match.group(1)
        location = tz.geolocator.geocode(city)
        if not location:
            return await event.edit(phrase.time.not_found.format(city))
        tz_name = await tz.get_timezone(
            location.latitude,
            location.longitude,
            await self.settings.get("token.geoapify"),
        )
        if not tz_name:
            return await event.edit(phrase.time.not_timezone.format(city))
        tzz = tz.pytz.timezone(tz_name)
        city_time = tz.datetime.now(tzz)
        await event.edit(
            phrase.time.location_info.format(
                address=location.address,
                time=city_time.strftime("%H:%M:%S"),
                date=city_time.strftime("%d.%m.%Y"),
                tz=tz_name,
            ),
        )
        return None

    async def typing(self, event: Message):
        text = event.pattern_match.group(1).strip()
        bep = ""
        delay = float(await self.settings.get("typing.delay"))
        typings = await self.settings.get("typings")
        while bep != text:
            await event.edit(bep + typings)
            await asyncio.sleep(delay)
            bep += text[len(bep)]
            await event.edit(bep)
            await asyncio.sleep(delay)

    async def words(self, event: Message):
        args = format.get_args(event.text.lower())

        def find_number(marker):
            for value in args:
                number = value.replace(marker, "")
                if marker in value and number.isdigit():
                    return int(number)
            return None

        arg_len, arg_count = find_number("л"), find_number("в")
        words = iterators.Counter()
        total = 0
        dots = ""
        msg = await event.edit(phrase.words.all.format(words=total, dots=dots))
        async for message in self.client.iter_messages(event.chat_id):
            total += 1
            if total % 200 == 0:
                dots = dots + "." if len(dots) < 3 else ""
                try:
                    await msg.edit(
                        phrase.words.all.format(words=total, dots=dots)
                    )
                except Exception:
                    await asyncio.sleep(await self.settings.get("typing.delay"))
                    with contextlib.suppress(Exception):
                        msg = await event.reply(
                            phrase.words.except_all.format(total)
                        )
            if message.text:
                for word in message.text.split():
                    clean = re.sub(r"\W+", "", word).strip()
                    if (clean and not clean.isdigit()) and (
                        arg_len is None or len(clean) >= arg_len
                    ):
                        words[clean.lower()] += 1
            if total % 1000 == 0:
                await asyncio.sleep(await self.settings.get("typing.delay"))
        freq = sorted(words, key=words.get, reverse=True)
        out = phrase.words.out
        maxsize = min(arg_count if arg_count is not None else 50, len(freq))
        for index, word in enumerate(freq[:maxsize], 1):
            out += f"{index}. {words[word]}: {word}\n"
        try:
            await msg.edit(out)
        except Exception:
            await event.reply(out)

    async def ping(self, event: Message):
        timestamp = event.date.timestamp()
        timedel = round(time() - timestamp, 2)
        t1 = time()
        await event.edit(phrase.ping.pong)
        pingtime = round(time() - t1, 2)
        await event.edit(
            phrase.ping.ping.format(
                timedel=f"{timedel} сек.", ping=f"{pingtime} сек."
            ),
        )

    async def flip_text(self, event: Message):
        try:
            text = event.text.split(" ", maxsplit=1)[1]
        except IndexError:
            return await event.edit(phrase.no_text)
        flipped = "".join(flip_map.flip_map.get(c, c) for c in reversed(text))
        await event.edit(flipped)
        return None

    async def server_load(self, event: Message):
        await event.edit(await get_sys.get_system_info())

    async def ai_model(self, event: Message):
        model: str = event.pattern_match.group(1).strip()
        await self.settings.set("ai.model", model)
        self.ai_client.chat_model = model
        self.ai_chat = self.ai_client.chat(self.phone)
        await event.edit(phrase.ai.model_set)

    async def ai_clear(self, event: Message):
        await self.ai_chat.clear()
        await event.edit(phrase.ai.clear)

    async def ai_resp(self, event: Message):
        if not await self.settings.get("token.groq"):
            return await event.edit(phrase.ai.no_token)
        text = event.pattern_match.group(1).strip()
        try:
            response = await self.ai_chat.send(text)
        except Exception as e:
            return await event.edit(phrase.error.format(e))
        if len(response) > 4096:
            chunks = format.splitter(response)
            await event.edit(chunks[0])
            for chunk in chunks[1:]:
                await event.reply(chunk)
        else:
            await event.edit(response)
        return None

    async def config_reload(self, event: Message):
        await self.settings._ensure_loaded(forced=True)
        await event.edit(phrase.config.reload)

    async def calc(self, event: Message):
        expr = event.pattern_match.group(1).strip()
        if not re.fullmatch(r"[\d+\-*/().\s]+", expr):
            return await event.edit(phrase.calc.invalid_chars)
        try:
            result = eval(expr, {"__builtins__": {}}, {})
        except ZeroDivisionError:
            return await event.edit(phrase.calc.div_by_zero)
        except Exception:
            return await event.edit(phrase.calc.error)
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        await event.edit(phrase.calc.result.format(expr, result))
        return None

    async def autodelmsg(self, event: Message):
        lines = event.text.splitlines()
        first_line = lines[0]
        rest_text = "\n".join(lines[1:]).strip()
        parts = first_line.split(maxsplit=2)
        if len(parts) < 2:
            return await event.edit(phrase.autodel.args)
        try:
            delay = int(parts[1])
            text = rest_text or (parts[2] if len(parts) > 2 else "")
        except ValueError:
            delay = config.config.wait_delete
            text = " ".join(parts[1:]) + ("\n" + rest_text if rest_text else "")
        if not text.strip():
            return await event.edit(phrase.autodel.empty)
        msg: Message = await event.edit(text.strip())
        await asyncio.sleep(delay)
        await msg.edit(phrase.autodel.deleting)
        await asyncio.sleep(1)
        await msg.delete()
        return None

    async def gen_pass(self, event: Message):
        args = (event.pattern_match.group(1) or "").strip()
        length = genpass.Default.length
        options = {
            "letters": genpass.Default.letters,
            "digits": genpass.Default.digits,
            "special": genpass.Default.special,
        }
        if match := re.search(r"д(\d+)", args):
            length = int(match[1])
        for flag, key in (("б", "letters"), ("ц", "digits"), ("с", "special")):
            options[key] = bool(re.search(rf"\+{flag}", args)) or (
                options[key] and not re.search(rf"-{flag}", args)
            )
        try:
            pwd = genpass.gen_pass(length, **options)
            await event.edit(phrase.password.done.format(pwd))
        except Exception as ex:
            await event.edit(phrase.error.format(ex))

    async def run_shell(self, event: Message):
        cmd = event.pattern_match.group(1).strip()
        if self.phone not in config.tokens.admins:
            return await event.edit(phrase.shell.not_admin)
        if not cmd:
            return await event.edit(phrase.shell.no_command)
        msg = await event.edit(phrase.shell.started.format(cmd))
        full_output = ""
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            while proc.stdout and not proc.stdout.at_eof():
                try:
                    chunk = await asyncio.wait_for(
                        proc.stdout.read(1024), timeout=1.0
                    )
                    if not chunk:
                        break
                    decoded = chunk.decode("utf-8", errors="replace")
                    full_output += decoded
                    display = full_output[-3000:]
                    with contextlib.suppress(Exception):
                        await msg.edit(phrase.shell.live.format(cmd, display))
                except TimeoutError:
                    continue
            await proc.wait()
            final = (full_output or "[no output]").strip()
            if len(final) > 4000:
                final = final[-4000:] + phrase.shell.truncated
            await msg.edit(phrase.shell.finished.format(cmd, final))
        except Exception as e:
            await msg.edit(phrase.shell.error.format(e))

    async def run(self):
        try:
            await self.init()
            self.status = "running"
            _set_status(self.phone, "running")
            await self.client.run_until_disconnected()
        except ClientNotAuthorized as exc:
            self.status = "unauthorized"
            self.error = str(exc)
            logger.warning(f"Клиент ({self.phone}): {exc}")
        except asyncio.CancelledError:
            self.status = "stopped"
            raise
        except Exception as exc:
            self.status = "error"
            self.error = str(exc) or type(exc).__name__
            logger.exception(f"Критическая ошибка в {self.phone}")
        finally:
            if self.status == "running":
                self.status = "stopped"
            _managers.pop(self.phone, None)
            _manager_tasks.pop(self.phone, None)
            _set_status(self.phone, self.status, self.error)
            with contextlib.suppress(Exception):
                await self.client.disconnect()


async def _read_client_config(phone: str) -> dict | None:
    try:
        return await settings.UBSettings(phone, pathes.clients).all()
    except Exception:
        return None


async def _launch_manager(phone: str) -> bool:
    """Создаёт и запускает UserbotManager в фоне."""
    async with _client_lock(phone):
        manager = _managers.get(phone)
        task = _manager_tasks.get(phone)
        if manager and task and not task.done():
            return False
        _managers.pop(phone, None)
        _manager_tasks.pop(phone, None)
        data = await _read_client_config(phone)
        if not data:
            _set_status(phone, "error", "Конфиг не найден или повреждён")
            return False
        try:
            api_id = int(data["api_id"])
            api_hash = str(data["api_hash"])
        except KeyError, TypeError, ValueError:
            _set_status(phone, "error", "В конфиге нет api_id/api_hash")
            return False
        manager = UserbotManager(phone, api_id, api_hash)
        _managers[phone] = manager
        _set_status(phone, "starting")
        _manager_tasks[phone] = asyncio.create_task(
            manager.run(), name=f"ub_{phone}"
        )
        return True


async def _stop_manager(phone: str) -> bool:
    async with _client_lock(phone):
        manager = _managers.pop(phone, None)
        task = _manager_tasks.pop(phone, None)
        if manager is None and task is None:
            _set_status(phone, "stopped")
            return False
        _set_status(phone, "stopping")
        if manager:
            with contextlib.suppress(Exception):
                await manager.stop()
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        _set_status(phone, "stopped")
        return True


async def _restart_manager(phone: str) -> bool:
    await _stop_manager(phone)
    return await _launch_manager(phone)


async def _stop_all_managers() -> int:
    phones = list(_managers)
    if not phones:
        return 0
    await asyncio.gather(
        *(_stop_manager(phone) for phone in phones),
        return_exceptions=True,
    )
    return len(phones)


async def main():
    import signal

    pathes.clients.mkdir(exist_ok=True)
    pathes.sessions.mkdir(exist_ok=True)
    loop = asyncio.get_running_loop()
    log_broker = web.LogBroker(loop, int(config.config.web.log_buffer_size))
    logger.add(log_broker, level="INFO")

    panel = web.Panel(
        host=str(config.config.web.host),
        port=int(config.config.web.port),
        password=str(config.config.web.password or ""),
        managers=_managers,
        statuses=_client_status,
        launch=_launch_manager,
        stop=_stop_manager,
        restart=_restart_manager,
        stop_all=_stop_all_managers,
        make_client=_make_client,
        log_broker=log_broker,
    )
    try:
        await panel.start()
    except OSError as exc:
        logger.error(
            "Не удалось запустить веб-панель "
            f"{config.config.web.host}:{config.config.web.port}: {exc}"
        )
        raise

    client_files = sorted(pathes.clients.glob("*.json"))
    if client_files:
        logger.info(f"Clients: {[f.name for f in client_files]}")
    for client_file in client_files:
        result = await config.load_client(pathes.clients, client_file.name)
        if not result:
            _set_status(
                client_file.stem,
                "error",
                "Некорректный JSON клиентского конфига",
            )
            continue
        phone = result[0]
        data = await _read_client_config(phone)
        if data and data.get("disabled"):
            _set_status(phone, "disabled")
            continue
        if not _session_exists(phone):
            _set_status(
                phone,
                "unauthorized",
                "Нет сессии — требуется вход через панель",
            )
            logger.warning(
                f"Клиент ({phone}) без сессии: войдите через веб-панель"
            )
            continue
        await _launch_manager(phone)

    stop_event = asyncio.Event()
    stopping = False

    def request_stop(*_args) -> None:
        nonlocal stopping
        if stopping:
            logger.warning("Повторный сигнал — принудительный выход")
            os._exit(130)
        stopping = True
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
            loop.add_signal_handler(sig, request_stop)

    try:
        await stop_event.wait()
    finally:
        logger.info("Останавливаю веб-панель и клиентов…")
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    panel.stop(),
                    _stop_all_managers(),
                    return_exceptions=True,
                ),
                timeout=20,
            )
        except TimeoutError:
            logger.warning("Остановка зависла — принудительный выход")
            os._exit(1)


if __name__ == "__main__":
    from modules import (
        ai,
        apis,
        autochat,
        clickbee,
        config,
        d,
        db,
        flip_map,
        flood,
        format,
        genpass,
        get_sys,
        ipman,
        iterators,
        notes,
        pathes,
        settings,
        task_gen,
        telemt,
        tz,
        vktarget_bot,
        web,
    )

    try:
        try:
            import uvloop

            uvloop.run(main())
        except ModuleNotFoundError:
            logger.warning(phrase.misc.uvloop_missing)
            asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning(phrase.misc.shutting_down)
