import asyncio
import logging
import random
import re
import contextlib
from sys import stderr
from os import listdir, mkdir, path
from time import time

import aiofiles
import orjson
from loguru import logger

from telethon import events, functions, types
from telethon import TelegramClient
from telethon.tl.custom import Message
from telethon.tl.custom.participantpermissions import ParticipantPermissions
from telethon.tl.types import MessageMediaDocument, PeerUser, User
from telethon.tl.functions.account import UpdateStatusRequest

logger.remove()
logger.add(
    stderr,
    format=(
        "[{time:HH:mm:ss} <level>{level}</level>]: "
        "<green>{file}:{function}</green> <cyan>></cyan> {message}"
    ),
    level="INFO",
    colorize=True,
    backtrace=False,
    diagnose=False,
)

logger.info("LumintoGold запускается...")

try:
    from vkbottle import Bot  # type: ignore
    from vkbottle.tools import PhotoWallUploader  # type: ignore

    import_vkbottle = True
except ModuleNotFoundError:
    import_vkbottle = False
    logger.warning("Нету vkbottle! Транслятор tg->vk не будет работать.")


class InterceptHandler(logging.Handler):
    def emit(self, record):
        level = "TRACE" if record.levelno == 5 else record.levelname
        logger.opt(depth=6, exception=record.exc_info).log(
            level, record.getMessage()
        )


logging.basicConfig(handlers=[InterceptHandler()], level=0)

from modules import (  # noqa: E402
    ai,
    d,
    formatter,
    get_sys,
    task_gen,
    genpass,
    phrase,
    flip_map,
    iterators,
    settings,
    tz,
    db,
    ipman,
    apis,
    notes,
)


def get_args(text: str, skip_first: bool = True) -> list[str]:
    parts = text.split()
    return parts[1:] if skip_first and parts else parts


class UserbotManager:
    def __init__(self, phone: str, api_id: int, api_hash: str):
        self.phone = phone
        self.settings = settings.UBSettings(phone, "clients")
        self.client = TelegramClient(
            session=path.join("sessions", phone),
            api_id=api_id,
            api_hash=api_hash,
            use_ipv6=self.settings.sync_get("use.ipv6", False),
            system_version="4.16.30-vxCUSTOM",
            device_model="LumintoGold",
            system_lang_code="ru",
            lang_code="ru",
            connection_retries=-1,
            retry_delay=3,
        )
        self.iris_task = task_gen.Generator(f"{phone}_iris")
        self.online_task = task_gen.Generator(f"{phone}_online")
        self.iceyes_task = task_gen.Generator(f"{phone}_iceyes")
        self.ai_client = ai.Client(None, None)
        self.notes = notes.Notes(phone)
        self._autochat_running = False
        self._autochat_task = None
        self._flood_state: dict[str, list[float]] = {}
        self._flood_rules: dict[int, dict[str, dict]] = {}

    async def init(self):
        self.client.use_ipv6 = await self.settings.get("use.ipv6")
        self.ai_client = ai.Client(
            await self.settings.get("ai.token"),
            await self.settings.get("ai.proxy"),
        )
        await self.client.start(phone=self.phone)
        logger.info(f"Запущен клиент ({self.phone})")

        self._register_handlers()

        if await self.settings.get("block.voice"):
            self.client.add_event_handler(self.block_voice, events.NewMessage())

        if await self.settings.get("luminto.reactions"):
            for chat in ("lumintoch", "trassert_ch"):
                self.client.add_event_handler(
                    self.reactions, events.NewMessage(chats=chat)
                )

        if await self.settings.get("iris.farm"):
            await self.iris_task.create(
                func=self.iris_farm, task_param=4, random_delay=(5, 360)
            )

        if await self.settings.get("iceyes.bonus"):
            await self.iceyes_task.create(
                func=self.iceyes_bonus, task_param=1, random_delay=(1, 60)
            )

        if await self.settings.get("auto.online"):
            await self.online_task.create(
                func=self.auto_online, task_param=30, unit="seconds"
            )

        if await self.settings.get("autochat.enabled"):
            await self._start_autochat()

        if await self.settings.get("tg2vk.enabled", False):
            target_chat = await self.settings.get("tg2vk.chat")
            if target_chat:
                self.client.add_event_handler(
                    self._handle_tg_to_vk, events.NewMessage(chats=target_chat)
                )

    def _register_handlers(self):
        if import_vkbottle:
            self.client.on(d.cmd(r"\.тгвк$"))(self.toggle_tg_to_vk)

        self.client.on(d.cmd(r"\+нот (.+)\n([\s\S]+)"))(self.add_note)
        self.client.on(d.cmd(r"\-нот (.+)"))(self.rm_note)
        self.client.on(d.cmd(r"\!(.+)"))(self.chk_note)
        self.client.on(d.cmd(r"\.ноты$"))(self.list_notes)

        self.client.on(d.cmd(r"\.чистка"))(self.clean_pm)
        self.client.on(d.cmd(r"\.чатчистка$"))(self.clean_chat)
        self.client.on(d.cmd(r"\.слов"))(self.words)
        self.client.on(d.cmd(r"\.пинг$"))(self.ping)
        self.client.on(d.cmd(r"\.эмоид$"))(self.get_emo_id)
        self.client.on(d.cmd(r"\.флип"))(self.flip_text)
        self.client.on(d.cmd(r"\.гс$"))(self.on_off_block_voice)
        self.client.on(d.cmd(r"\.читать$"))(self.on_off_mask_read)
        self.client.on(d.cmd(r"\.серв$"))(self.server_load)
        self.client.on(d.cmd(r"\.релоадконфиг$"))(self.config_reload)
        self.client.on(d.cmd(r"\.автоферма$"))(self.on_off_farming)
        self.client.on(d.cmd(r"\.онлайн$"))(self.toggle_online)
        self.client.on(d.cmd(r"\.автобонус$"))(self.on_off_bonus)

        self.client.on(d.cmd(r"\.токен (.+)"))(self.ai_token)
        self.client.on(d.cmd(r"\.погода (.+)"))(self.get_weather)
        self.client.on(d.cmd(r"\.ip (.+)"))(self.ipman)
        self.client.on(d.cmd(r"\.аним (.+)"))(self.anim)
        self.client.on(d.cmd(r"\.прокси (.+)"))(self.ai_proxy)
        self.client.on(d.cmd(r"\.ии ([\s\S]+)"))(self.ai_resp)
        self.client.on(d.cmd(r"\.т ([\s\S]+)"))(self.typing)
        self.client.on(d.cmd(r"\.set (.+)"))(self.set_setting)
        self.client.on(d.cmd(r"\.время (.+)"))(self.time_by_city)

        self.client.on(
            d.cmd(
                r"\.genpass(?:\s+(.+))?",
            )
        )(self.gen_pass)
        self.client.on(
            d.cmd(
                r"\.генпасс(?:\s+(.+))?",
            )
        )(self.gen_pass)
        self.client.on(
            d.cmd(
                r"\.пароль(?:\s+(.+))?",
            )
        )(self.gen_pass)

        self.client.on(d.cmd(r"\-флудстики (\d+) (\d+)$"))(
            self.set_flood_stickers
        )
        self.client.on(d.cmd(r"\-флудгиф (\d+) (\d+)$"))(self.set_flood_gifs)
        self.client.on(d.cmd(r"\-флудобщ (\d+) (\d+)$"))(
            self.set_flood_messages
        )

        self.client.on(d.cmd(r"\+флудстики$"))(self.unset_flood_stickers)
        self.client.on(d.cmd(r"\+флудгиф$"))(self.unset_flood_gifs)
        self.client.on(d.cmd(r"\+флудобщ$"))(self.unset_flood_messages)

        self.client.on(d.cmd(r"\+авточат (-?\d+)"))(self.add_autochat)
        self.client.on(d.cmd(r"\-авточат (-?\d+)"))(self.rm_autochat)
        self.client.on(d.cmd(r"\.авточатстарт$"))(self.toggle_autochat)
        self.client.on(d.cmd(r"\.авточатстоп$"))(self.toggle_autochat)
        self.client.on(d.cmd(r"\.авточаттайм (\d+)"))(self.set_autochat_time)

        self.client.on(d.cmd(r"\.калк (.+)"))(self.calc)
        self.client.on(d.cmd(r"\.к (.+)"))(self.calc)
        self.client.on(d.cmd(r"\.calc (.+)"))(self.calc)

        self.client.on(events.NewMessage())(self._flood_monitor)
        self.client.on(events.NewMessage())(self._dynamic_mask_reader)

    async def clean_chat(self, event: Message):
        if event.is_private:
            return await event.edit(phrase.clear.private)

        chat = await event.get_chat()
        if not hasattr(chat, "title"):
            return await event.edit(phrase.not_a_chat)

        try:
            me = await self.client.get_me()
            admin_rights: ParticipantPermissions = (
                await self.client.get_permissions(chat, me)
            )
            if not admin_rights.ban_users:
                return await event.edit(phrase.clear.no_rights)

        except Exception:
            return await event.edit(phrase.clear.no_rights)

        await event.edit(phrase.clear.start)

        kicked = 0
        unbanned = 0

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

        async for ban in self.client.iter_participants(
            chat, filter=types.ChannelParticipantsKicked
        ):
            user: User = ban
            if user and user.deleted:
                try:
                    await self.client.edit_permissions(
                        chat, user, view_messages=True
                    )
                    unbanned += 1
                    if unbanned % 5 == 0:
                        await event.edit(
                            phrase.clear.unban.format(count=unbanned)
                        )
                except Exception:
                    logger.trace("Не могу вынести из бана участника")
            await asyncio.sleep(await self.settings.get("typing.delay"))

        if kicked or unbanned:
            await event.edit(
                phrase.clear.done.format(kicked=kicked, unbanned=unbanned)
            )
        else:
            await event.edit(phrase.clear.not_found)

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
                )
            )
            logger.info("Отправил реакцию!")
        except Exception:
            pass

    async def _start_iris_farm(self):
        await self.iris_task.create(
            func=self.iris_farm, task_param=4, random_delay=(5, 360)
        )

    async def _start_iceyes_bonus(self):
        await self.iceyes_task.create(
            func=self.iceyes_bonus, task_param=1, random_delay=(1, 60)
        )

    async def _start_auto_online(self):
        await self.online_task.create(
            func=self.auto_online, task_param=30, unit="seconds"
        )

    async def _autochat_worker(self):
        while self._autochat_running:
            chat_ids = await self.settings.get("autochat.chats", [])
            ad_chat = await self.settings.get("autochat.ad_chat")
            ad_id = await self.settings.get("autochat.ad_id")
            delay = await self.settings.get("autochat.delay", 1000)

            if not (chat_ids and ad_chat and ad_id):
                await asyncio.sleep(60)
                continue

            for chat_id in chat_ids:
                if not self._autochat_running:
                    return
                try:
                    await self.client.forward_messages(
                        chat_id, int(ad_id), ad_chat
                    )
                    logger.info(f"Автопост: сообщение отправлено в {chat_id}")
                except Exception:
                    logger.trace(f"Автопост: ошибка в {chat_id}")
                logger.info(f"Автопост: жду {delay} сек.")
                await asyncio.sleep(delay)

    async def _start_autochat(self):
        if self._autochat_running:
            return
        self._autochat_running = True
        self._autochat_task = asyncio.create_task(self._autochat_worker())

    async def _stop_autochat(self):
        self._autochat_running = False
        if self._autochat_task:
            await self._autochat_task

    async def _autochat_sender(self):
        chat_ids = await self.settings.get("autochat.chats", [])
        ad_chat = await self.settings.get("autochat.ad_chat")
        ad_id = await self.settings.get("autochat.ad_id")

        if not chat_ids or not ad_chat or not ad_id:
            return

        for chat_id in chat_ids:
            try:
                await self.client.forward_messages(chat_id, int(ad_id), ad_chat)
                logger.info(f"Автопостинг: сообщение отправлено в {chat_id}")
            except Exception:
                logger.trace(f"Автопостинг: ошибка при отправке в {chat_id}")
            await asyncio.sleep(1)

    async def toggle_tg_to_vk(self, event: Message):
        if not import_vkbottle:
            return await event.edit(phrase.tg2vk.no_vkbottle)

        enabled = await self.settings.get("tg2vk.enabled", False)
        target_chat = await self.settings.get("tg2vk.chat")
        vk_group = await self.settings.get("tg2vk.vk_group")
        vk_token = await self.settings.get("tg2vk.vk_token")

        if not target_chat:
            await self.settings.set("tg2vk.enabled", False)
            return await event.edit(phrase.tg2vk.missing_config)

        self.client.remove_event_handler(self._handle_tg_to_vk)

        if not enabled:
            if not vk_group or not vk_token:
                await self.settings.set("tg2vk.enabled", False)
                return await event.edit(phrase.tg2vk.missing_config)
            self.client.add_event_handler(
                self._handle_tg_to_vk, events.NewMessage(chats=target_chat)
            )
            await self.settings.set("tg2vk.enabled", True)
            await event.edit(phrase.tg2vk.on)
        else:
            await self.settings.set("tg2vk.enabled", False)
            await event.edit(phrase.tg2vk.off)

    async def _handle_tg_to_vk(self, event: Message):
        logger.info("tg2vk: Новый пост")
        vk_token = await self.settings.get("tg2vk.vk_token")
        vk_group_id = await self.settings.get("tg2vk.vk_group")
        if not vk_token or not vk_group_id:
            return logger.error("tg2vk: Отсутствует токен или ID группы")

        attachments = []
        bot = Bot(token=vk_token)

        try:
            text = self._format_tg_message(event.text)

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

    def _format_tg_message(self, text: str) -> str:
        if not text:
            text = ""
        text = re.sub(r"\*\*|__", "", text)
        text = re.sub(r"\[.*?\]\(.*?\)", "", text)
        prefix = "📢 Из Telegram\n\n"
        result = (prefix + text.strip())[:4096]
        return result if result.strip() else prefix.strip()

    async def add_autochat(self, event: Message):
        try:
            chat_id = int(event.pattern_match.group(1))
        except (ValueError, TypeError):
            return await event.edit(phrase.autochat.invalid_id)

        chats = await self.settings.get("autochat.chats", [])
        if chat_id not in chats:
            chats.append(chat_id)
            await self.settings.set("autochat.chats", chats)
        await event.edit(phrase.autochat.added.format(chat_id))

    async def rm_autochat(self, event: Message):
        try:
            chat_id = int(event.pattern_match.group(1))
        except (ValueError, TypeError):
            return await event.edit(phrase.autochat.invalid_id)

        chats = await self.settings.get("autochat.chats", [])
        if chat_id in chats:
            chats.remove(chat_id)
            await self.settings.set("autochat.chats", chats)
        await event.edit(phrase.autochat.removed.format(chat_id))

    async def toggle_autochat(self, event: Message):
        enabled = not await self.settings.get("autochat.enabled", False)
        await self.settings.set("autochat.enabled", enabled)

        if enabled:
            await self._start_autochat()
            await event.edit(phrase.autochat.on)
        else:
            await self._stop_autochat()
            await event.edit(phrase.autochat.off)

    async def set_autochat_time(self, event: Message):
        try:
            delay = int(event.pattern_match.group(1))
            if delay < 10:
                return await event.edit(phrase.autochat.too_fast)
        except (ValueError, TypeError):
            return await event.edit(phrase.autochat.invalid_time)

        await self.settings.set("autochat.delay", delay)
        await event.edit(phrase.autochat.time_set.format(delay))

    async def get_emo_id(self, event: Message):
        message: Message = await event.get_reply_message()
        if message is None:
            return await event.edit(phrase.emoji.no_entity)
        if message.entities == []:
            return await event.edit(phrase.emoji.no_entity)
        text = []
        for entity in message.entities or []:
            if hasattr(entity, "document_id"):
                text.append(f"`{entity.document_id}`")
        if text == []:
            return await event.edit(phrase.emoji.no_entity)
        return await event.edit(phrase.emoji.get.format(", ".join(text)))

    async def set_flood_stickers(self, event: Message):
        await self._set_flood_rule(event, "stickers")

    async def set_flood_gifs(self, event: Message):
        await self._set_flood_rule(event, "gifs")

    async def set_flood_messages(self, event: Message):
        await self._set_flood_rule(event, "messages")

    async def _set_flood_rule(self, event: Message, rule_type: str):
        limit = int(event.pattern_match.group(1))
        window = int(event.pattern_match.group(2))
        chat_id = event.chat_id
        key = f"flood.{rule_type}.{chat_id}"

        await self.settings.set(key, {"limit": limit, "window": window})
        if chat_id not in self._flood_rules:
            self._flood_rules[chat_id] = {}
        self._flood_rules[chat_id][rule_type] = {
            "limit": limit,
            "window": window,
        }

        phrase_map = {
            "stickers": phrase.flood.set_stickers,
            "gifs": phrase.flood.set_gifs,
            "messages": phrase.flood.set_messages,
        }
        await event.edit(
            phrase_map[rule_type].format(limit=limit, window=window)
        )

    async def unset_flood_stickers(self, event: Message):
        await self._unset_flood_rule(event, "stickers")

    async def unset_flood_gifs(self, event: Message):
        await self._unset_flood_rule(event, "gifs")

    async def unset_flood_messages(self, event: Message):
        await self._unset_flood_rule(event, "messages")

    async def _unset_flood_rule(self, event: Message, rule_type: str):
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

    async def _load_flood_rules(self, chat_id: int):
        if chat_id not in self._flood_rules:
            stickers = await self.settings.get(f"flood.stickers.{chat_id}", {})
            gifs = await self.settings.get(f"flood.gifs.{chat_id}", {})
            messages = await self.settings.get(f"flood.messages.{chat_id}", {})
            self._flood_rules[chat_id] = {
                "stickers": stickers,
                "gifs": gifs,
                "messages": messages,
            }

    async def _flood_monitor(self, event: Message):
        if event.is_private or not event.sender_id:
            return

        chat_id = event.chat_id
        await self._load_flood_rules(chat_id)
        rules = self._flood_rules[chat_id]
        now = time()

        if rules["stickers"] and isinstance(
            event.media, types.MessageMediaDocument
        ):
            doc = event.media.document
            if doc and any(
                isinstance(a, types.DocumentAttributeSticker)
                for a in (doc.attributes or [])
            ):
                await self._check_flood(
                    event, chat_id, "stickers", rules["stickers"], now
                )

        if rules["gifs"] and isinstance(
            event.media, types.MessageMediaDocument
        ):
            doc = event.media.document
            if doc:
                is_gif = any(
                    isinstance(a, types.DocumentAttributeAnimated)
                    or (
                        isinstance(a, types.DocumentAttributeVideo)
                        and a.supports_streaming
                    )
                    for a in (doc.attributes or [])
                )
                if is_gif:
                    await self._check_flood(
                        event, chat_id, "gifs", rules["gifs"], now
                    )

        if rules["messages"] and event.text and not event.media:
            await self._check_flood(
                event, chat_id, "messages", rules["messages"], now
            )

    async def _check_flood(
        self,
        event: Message,
        chat_id: int,
        flood_type: str,
        rule: dict,
        now: float,
    ):
        limit: int = rule.get("limit", 0)
        window: int = rule.get("window", 0)
        if limit <= 0 or window <= 0:
            return

        key = f"_flood.{flood_type}.{chat_id}.{event.sender_id}"
        timestamps = self._flood_state.get(key, [])
        cutoff = now - window
        timestamps = [ts for ts in timestamps if ts > cutoff]
        timestamps.append(now)

        if len(timestamps) > limit:
            try:
                await event.reply(await self.settings.get("flood.msg"))
            except Exception:
                pass
            timestamps = []

        self._flood_state[key] = timestamps

    async def iris_farm(self):
        target = -1002355128955
        try:
            await self.client.send_message(
                target, random.choice(["/ферма", "/фарма"])
            )
        except Exception:
            await self.client.send_message(
                "iris_cm_bot", random.choice(["/ферма", "/фарма"])
            )
        logger.info(f"{self.phone} - сработала автоферма")

    async def iceyes_bonus(self):
        await self.client.send_message("iceyes_bot", "💸 Бонус")
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

    async def _toggle_setting_and_task(
        self,
        setting_key: str,
        task_attr: str,
        on_phrase,
        off_phrase,
        start_func,
        event: Message,
    ):
        enabled = not await self.settings.get(setting_key)
        await self.settings.set(setting_key, enabled)

        task = getattr(self, task_attr)
        if enabled:
            await start_func()
            await event.edit(on_phrase)
        else:
            task.stop()
            await event.edit(off_phrase)

    async def on_off_farming(self, event: Message):
        await self._toggle_setting_and_task(
            "iris.farm",
            "iris_task",
            phrase.farm.on,
            phrase.farm.off,
            self._start_iris_farm,
            event,
        )

    async def on_off_bonus(self, event: Message):
        await self._toggle_setting_and_task(
            "iceyes.bonus",
            "iceyes_task",
            phrase.bonus.on,
            phrase.bonus.off,
            self._start_iceyes_bonus,
            event,
        )

    async def toggle_online(self, event: Message):
        await self._toggle_setting_and_task(
            "auto.online",
            "online_task",
            phrase.online.on,
            phrase.online.off,
            self._start_auto_online,
            event,
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
            f"Координаты: {response.get('lat')}/{response.get('lon')}"
        )

    async def get_weather(self, event: Message):
        await event.edit(phrase.weather.wait)
        result = await apis.get_weather(
            event.pattern_match.group(1),
            await self.settings.get("token.openweathermap"),
        )
        await event.edit(result)

    async def anim(self, event: Message):
        name = event.text.split(" ", maxsplit=1)[1]
        animation = await db.get_animation(name)
        if not animation:
            return await event.edit(phrase.anim.no)
        for title in animation["text"]:
            await event.edit(title)
            await asyncio.sleep(animation["delay"])

    async def clean_pm(self, event: Message):
        dialogs = await self.client.get_dialogs()
        deleted_count = 0
        msg = await event.edit(phrase.pm.wait.format(0))
        for dialog in dialogs:
            user = dialog.entity
            if isinstance(user, User) and user.deleted:
                await self.client.delete_dialog(dialog.id)
                await asyncio.sleep(await self.settings.get("typing.delay"))
                deleted_count += 1
                if deleted_count % 5 == 0:
                    await msg.edit(phrase.pm.wait.format(deleted_count))
        await event.edit(phrase.pm.cleared.format(deleted_count))

    async def set_setting(self, event: Message):
        key, value = event.pattern_match.group(1).split(" ", maxsplit=1)
        await self.settings.set(key, value)
        await event.edit(phrase.setting.set.format(key=key, value=value))

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
            f"📍 {location.address}\n"
            f"🕒 Время: {city_time.strftime('%H:%M:%S')}\n"
            f"📅 Дата: {city_time.strftime('%d.%m.%Y')}\n"
            f"🌐 Пояс: {tz_name}"
        )

    async def typing(self, event: Message):
        text = event.pattern_match.group(1).strip()
        bep = ""
        while bep != text:
            await event.edit(bep + await self.settings.get("typings"))
            await asyncio.sleep(await self.settings.get("typing.delay"))
            bep += text[len(bep)]
            await event.edit(bep)
            await asyncio.sleep(await self.settings.get("typing.delay"))

    async def words(self, event: Message):
        args = get_args(event.text.lower())
        arg_len = next(
            (
                int(x.replace("л", ""))
                for x in args
                if "л" in x and x.replace("л", "").isdigit()
            ),
            None,
        )
        arg_count = next(
            (
                int(x.replace("в", ""))
                for x in args
                if "в" in x and x.replace("в", "").isdigit()
            ),
            None,
        )

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
                    if clean and not clean.isdigit():
                        if arg_len is None or len(clean) >= arg_len:
                            words[clean.lower()] += 1

            if total % 1000 == 0:
                await asyncio.sleep(await self.settings.get("typing.delay"))

        freq = sorted(words, key=words.get, reverse=True)
        out = phrase.words.out
        maxsize = min(50, len(freq))
        if arg_count is not None:
            maxsize = min(arg_count, len(freq))
        for i in range(maxsize):
            out += f"{i + 1}. {words[freq[i]]}: {freq[i]}\n"

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
            )
        )

    async def flip_text(self, event: Message):
        try:
            text = event.text.split(" ", maxsplit=1)[1]
        except IndexError:
            return await event.edit(phrase.no_text)
        flipped = "".join(flip_map.flip_map.get(c, c) for c in reversed(text))
        await event.edit(flipped)

    async def server_load(self, event: Message):
        await event.edit(await get_sys.get_system_info())

    async def ai_token(self, event: Message):
        token = event.pattern_match.group(1).strip()
        await self.settings.set("ai.token", token)
        self.ai_client.change_api_key(token)
        await event.edit(phrase.ai.token_set)

    async def ai_proxy(self, event: Message):
        proxy = event.pattern_match.group(1).strip()
        await self.settings.set("ai.proxy", proxy)
        self.ai_client.change_proxy(proxy)
        await event.edit(phrase.ai.proxy_set)

    async def ai_resp(self, event: Message):
        if not await self.settings.get("ai.token"):
            return await event.edit(phrase.ai.no_token)
        text = event.pattern_match.group(1).strip()
        try:
            response = await self.ai_client.generate(text)
        except Exception as e:
            return await event.edit(phrase.error.format(e))
        if len(response) > 4096:
            chunks = formatter.splitter(response)
            await event.edit(chunks[0])
            for chunk in chunks[1:]:
                await event.reply(chunk)
        else:
            await event.edit(response)

    async def config_reload(self, event: Message):
        await self.settings._ensure_loaded(forced=True)
        await event.edit(phrase.config.reload)

    async def calc(self, event: Message):
        expr = event.pattern_match.group(1).strip()

        if not re.fullmatch(r"[\d+\-*/().\s]+", expr):
            return await event.edit(phrase.calc.invalid_chars)

        if any(
            c in expr
            for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_"
        ):
            return await event.edit(phrase.calc.forbidden)

        try:
            result = eval(expr, {"__builtins__": {}}, {})
        except ZeroDivisionError:
            return await event.edit(phrase.calc.div_by_zero)
        except Exception:
            return await event.edit(phrase.calc.error)

        if isinstance(result, float) and result.is_integer():
            result = int(result)

        await event.edit(phrase.calc.result.format(expr, result))

    async def gen_pass(self, event: Message):
        args = (event.pattern_match.group(1) or "").strip()
        length = genpass.Default.length
        letters = genpass.Default.letters
        digits = genpass.Default.digits
        special = genpass.Default.special

        if match := re.search(r"д(\d+)", args):
            length = int(match[1])
        letters = (
            True
            if re.search(r"\+б", args)
            else (False if re.search(r"-б", args) else letters)
        )
        digits = (
            True
            if re.search(r"\+ц", args)
            else (False if re.search(r"-ц", args) else digits)
        )
        special = (
            True
            if re.search(r"\+с", args)
            else (False if re.search(r"-с", args) else special)
        )

        try:
            pwd = genpass.gen_pass(length, letters, digits, special)
            await event.edit(phrase.password.done.format(pwd))
        except Exception as ex:
            await event.edit(phrase.error.format(ex))

    async def run(self):
        await self.init()
        await self.client.run_until_disconnected()


async def run_userbot(number: str, api_id: int, api_hash: str):
    try:
        bot = UserbotManager(number, api_id, api_hash)
        await bot.run()
    except Exception:
        logger.exception(f"Критическая ошибка в {number}")


async def main():
    clients_dir = "clients"
    try:
        clients = listdir(clients_dir)
    except FileNotFoundError:
        mkdir(clients_dir)
        clients = []

    if not clients:
        logger.warning("Нет ни одного клиента! Создаём нового..")
        number = input("Введи номер: ")
        api_id = int(input("Введи api_id: "))
        api_hash = input("Введи api_hash: ")
        async with aiofiles.open(
            path.join(clients_dir, f"{number}.json"), "wb"
        ) as f:
            await f.write(
                orjson.dumps(
                    {"api_id": api_id, "api_hash": api_hash},
                    option=orjson.OPT_INDENT_2,
                )
            )
        return await main()

    logger.info(f"Клиенты: {clients}")
    tasks = []
    for client_file in clients:
        try:
            async with aiofiles.open(
                path.join(clients_dir, client_file), "rb"
            ) as f:
                data = orjson.loads(await f.read())
            phone = client_file.replace(".json", "")
            tasks.append(run_userbot(phone, data["api_id"], data["api_hash"]))
        except orjson.JSONDecodeError:
            logger.error(
                f"{client_file} пуст или неправильно размечен! Отключаем клиента.."
            )
    if tasks == []:
        return logger.error("Нет ни одного валидного клиента.")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        try:
            import uvloop

            uvloop.run(main())
        except ModuleNotFoundError:
            logger.warning(
                "Uvloop не найден! Установите его: pip install uvloop"
            )
            asyncio.run(main())
    except KeyboardInterrupt:
        logger.warning("Закрываю бота...")
